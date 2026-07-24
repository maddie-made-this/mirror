import asyncio
import json
import logging
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.deps import CurrentUserID
from config.loader import APP_CONFIG
from core import request_context
from core.rate_limit import limiter
from llm.prompts import build_response_messages_debug
from schemas.graph import GraphContext
from schemas.piece_brief import PieceBrief
from schemas.message import (
    ChipAcceptRequest,
    ChipRequest,
    ChipResponse,
    FeedbackRequest,
    LengthRequest,
    MessageRequest,
    MessageResponse,
    RetryNoteRequest,
    TestPieceRequest,
)
from services import actions
from services import feedback as feedback_service
from services import (
    dynamics,
    extraction_queue,
    graph_service,
    render_prefs,
    retry_note_classifier,
    sessions,
    steering,
    test_piece,
)
from services import history as history_service
from services import account as account_service
from services import models
from services.render_mode import detect_render_mode
from services.idempotency import claim_or_get_cached_response, store_response
from services.response_gen import (
    generate_response,
    generate_response_with_debug,
    open_response_stream,
)
from services.safety import SafetyDecision, check_input, check_output

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/messages", tags=["messages"])


def _ms_since(start: float) -> int:
    """Whole-millisecond elapsed since a perf_counter() reading (Change 5 timing)."""
    return int((time.perf_counter() - start) * 1000)


def _skip_input_guard() -> bool:
    """Change 4: skip the redundant input guard when the split is active — the
    (Sonnet) director is the bright-line floor, so a separate input-guard LLM call
    adds latency for no coverage. Re-enabled by config if the director is swapped."""
    return APP_CONFIG.use_director_split and APP_CONFIG.skip_input_guard_on_split


def _run_input_guard() -> bool:
    """Whether to make the input-guard call this turn: only if the guard is enabled
    AND we're not skipping it on the split path."""
    return APP_CONFIG.use_input_guardrail and not _skip_input_guard()


# Registers that count as GENERATIVE — the ones that produce a piece rather than
# a reply. The client shows reaction chips for exactly these.
GENERATIVE_MODES = frozenset({"author", "cowrite"})


def _resolve_render_mode(body, session_type: str) -> str:
    """The register for this turn.

    Detection reads the message text alone, which is right for a fresh request but
    wrong for a continuation: a chip instruction ("Move to the next phase…") looks
    like ordinary conversation, so a piece dropped out of the generative register
    on its second beat and never came back. When the client says it is continuing
    a piece, keep it generative.

    'author' rather than 'cowrite' deliberately: cowrite routes to the
    director/renderer split, which is disabled here (use_director_split), and
    would fall through to the single-model path with no brief at all.

    Only 'conversational' is promoted — it is the fall-through default, so it is
    the only mode that means "nothing matched". A detected 'analysis' is a real
    self-understanding bid (and the analytic branch is analysis unconditionally);
    promoting that would turn the analytic surface into a piece generator.
    """
    mode = detect_render_mode(body.message, session_type)
    if getattr(body, "continue_piece", False) and mode == "conversational":
        return "author"
    return mode


async def _apply_length_pref(user_id: UUID, render_mode: str) -> None:
    """P4.1: resolve the user's learned per-mode length target and publish it as
    request-ambient state (read by format_rules at prompt-build time). Best-effort —
    a failure must never break a turn; None target simply injects no directive."""
    try:
        prefs = await render_prefs.get_render_prefs(user_id)
        request_context.set_target_words(render_prefs.target_words(prefs, render_mode))
    except Exception:
        request_context.set_target_words(None)


async def _apply_model_pref(user_id: UUID) -> None:
    """Resolve the user's chosen response model and publish it as request-ambient
    state (read by response_gen at each generation call site). Best-effort and
    VALIDATED: an unknown/retired id resolves to None so the turn falls back to the
    configured default rather than 404-ing at the provider."""
    try:
        chosen = await account_service.get_preferred_model(user_id)
        request_context.set_response_model(models.resolve(chosen))
    except Exception:
        # Log it: a silent except here would make a broken preference lookup
        # indistinguishable from "user has no preference", and the feature would
        # look wired while never actually taking effect.
        logger.warning("model preference lookup failed; using config default", exc_info=True)
        request_context.set_response_model(None)


async def _enqueue_extraction(
    body: MessageRequest,
    user_id: UUID,
    session_number: int,
    message_id: UUID,
    graph_ctx: GraphContext,
    active_predicates: list[str],
    display_name: str,
    self_node_id: str,
    steer: dict | None,
    *,
    clearly_engaged: bool = True,
    depth_ramp: str = "",
) -> None:
    """Hand this turn's extraction + graph-mutation tail (ingest → uptake judging →
    recluster → offer recording) to the background worker (Change 1). Returns at
    once; the response path never waits on it. relevant_nodes is the PRE-turn graph
    context — a turn's reply was already generated from it, so this work serves only
    future turns.

    A CHIP-DRIVEN turn carries no user disclosure: `message` is the reaction
    chip's steering instruction ("redo this beat but pick a specific track",
    "move to the next phase"), not something the user said about themselves.
    Extracting it writes the user's own UI steering back into the graph as if it
    were self-report — which produced a false `avoidance` node from the phrase
    "stop arguing in the abstract".

    Two signals mark these turns: `regenerate_of` (a redo, in place) and
    `continue_piece` (an advance/wildcard chip carries this without a redo). The
    gate lives here, not at the call sites, so a future caller cannot reintroduce
    the leak by forgetting. A message the user actually TYPED — even mid-piece —
    carries neither flag and is still extracted.
    """
    if body.regenerate_of or getattr(body, "continue_piece", False):
        logger.debug(
            "skipping extraction for chip-driven turn",
            extra={"message_id": str(message_id)},
        )
        return

    await extraction_queue.enqueue(
        extraction_queue.ExtractionJob(
            user_id=user_id,
            conversation_id=body.conversation_id,
            message_id=message_id,
            session_number=session_number,
            message=body.message,
            relevant_nodes=graph_ctx.relevant_nodes,
            active_predicates=active_predicates,
            active_node_ids=body.active_node_ids,
            display_name=display_name,
            self_node_id=self_node_id,
            depth_ramp=depth_ramp,
            clearly_engaged=clearly_engaged,
            steer=steer,
        )
    )


@router.post("", response_model=MessageResponse, status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def post_message(
    request: Request,
    body: MessageRequest,
    current_user_id: CurrentUserID,
) -> MessageResponse:
    # Idempotency (E): a retry with the same client_message_id replays the
    # cached response instead of re-processing and re-mutating the graph.
    cached = await claim_or_get_cached_response(
        current_user_id, body.conversation_id, body.client_message_id
    )
    if cached is not None:
        return MessageResponse(**cached)

    t0 = time.perf_counter()  # B4: response latency

    # B5: session number is authoritative — never accepted from client.
    session_number = await sessions.get_or_create_current_session(current_user_id)

    # Input guard + graph context (Change 4). The input guard is SKIPPED on the
    # split path — the Sonnet director is the bright-line floor, so the separate
    # input-guard LLM call is redundant for its scoped purpose.
    # When it DOES run (config-gated), it fires
    # CONCURRENTLY with context build: the verdict is only needed before generation,
    # not before context, so there is zero added latency. H9: context degrades
    # gracefully if Qdrant is unreachable.
    async def _ctx() -> GraphContext:
        try:
            return await graph_service.build_graph_context(
                body.message, current_user_id, session_number
            )
        except Exception:
            logger.warning(
                "Graph context unavailable, proceeding without",
                extra={"user_id": str(current_user_id)},
            )
            return GraphContext(relevant_nodes=[], relevant_edges=[])

    input_guard_ms: int | None = None
    if _run_input_guard():
        ig_t = time.perf_counter()
        input_check, graph_ctx = await asyncio.gather(check_input(body.message), _ctx())
        input_guard_ms = _ms_since(ig_t)
        if input_check.decision == SafetyDecision.UNSAFE:
            logger.warning(
                "Input guardrail tripped",
                extra={
                    "user_id": str(current_user_id),
                    "categories": input_check.categories,
                    "reasoning": input_check.reasoning,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=APP_CONFIG.guardrail_refusal_message,
            )
    else:
        graph_ctx = await _ctx()

    # Flow 2 (B5): inject idiographic interpretations relevant to this turn.
    try:
        graph_ctx.interpretations = await graph_service.get_interpretations_for_nodes(
            current_user_id, [n.id for n in graph_ctx.relevant_nodes]
        )
    except Exception:
        graph_ctx.interpretations = []

    # Display name for self-node bootstrap and self-reference resolution.
    display_name = body.user_display_name or "Me"

    # Fetch history, preferences, top predicates, session type, and ensure the
    # self-node exists — all independent, run in parallel.
    history, pref_nodes, active_predicates, self_node_id, session_type = (
        await asyncio.gather(
            history_service.get_recent_turns(
                body.conversation_id, current_user_id, APP_CONFIG.recent_messages_limit
            ),
            graph_service.get_preference_nodes(current_user_id),
            graph_service.get_top_predicates(current_user_id, limit=15),
            graph_service.ensure_self_node(current_user_id, display_name),
            history_service.get_session_type(body.conversation_id, current_user_id),
        )
    )

    # Session dials (§4): coarse per-turn read — feeds the dynamics prompt layer,
    # the steering gate, and ingest's mention stamping. Never persisted.
    try:
        session_state = await dynamics.get_session_state(
            current_user_id, body.conversation_id, session_type
        )
        if graph_ctx.relevant_nodes:
            session_state.active_region = graph_ctx.relevant_nodes[0].name
        graph_ctx.session_state = session_state.model_dump(mode="json")
    except Exception:
        logger.warning("session state unavailable", extra={"user_id": str(current_user_id)})
        session_state = None

    clearly_engaged = bool(
        session_state is None or session_state.gate_position.value != "guarded"
    )
    depth_ramp = session_state.depth_ramp.value if session_state else ""

    # Flow 3/4 (B5, §5): select a steering objective — gates filtered, dial-aware.
    try:
        steer = await steering.select_objective(
            current_user_id,
            session_number,
            gate_position=session_state.gate_position.value if session_state else "neutral",
        )
    except Exception:
        steer = None
    graph_ctx.steering_objective = steer["objective"] if steer else None

    # Generate a message_id now so it provenance-stamps the queued extraction.
    message_id = uuid4()

    # Change 1: extraction + the whole graph-mutation tail (ingest → uptake judging
    # → recluster → offer recording) go to the background worker, OFF the response
    # path. The reply is built from the graph as it stood BEFORE the turn, so this
    # turn's extraction only serves FUTURE turns — generation no longer waits on it,
    # and new nodes land in the UI within seconds (polled at /processing).
    await _enqueue_extraction(
        body, current_user_id, session_number, message_id, graph_ctx,
        active_predicates, display_name, self_node_id, steer,
        clearly_engaged=clearly_engaged, depth_ramp=depth_ramp,
    )

    # Prior-turn state fed to the director: the carry-forward brief (arc + parse-
    # failure base, Change 1) and the LOCKED piece-state for this conversation
    # (Change 2 — fixed subject/POV/figures so it doesn't drift). Both None on turn one.
    prev_brief, locked_piece_frame = await asyncio.gather(
        history_service.get_last_piece_brief(body.conversation_id, current_user_id),
        history_service.get_conversation_piece_frame(body.conversation_id, current_user_id),
    )

    # C3: infer the render mode (conversational default | piece | analysis) — only the
    # piece mode loads the heavy director/arc apparatus.
    render_mode = _resolve_render_mode(body, session_type)

    # P4.1: publish the user's learned length target for this mode as request-ambient
    # state; format_rules.render reads it at prompt-build time. Best-effort.
    await _apply_length_pref(current_user_id, render_mode)
    await _apply_model_pref(current_user_id)

    async def generate():
        if APP_CONFIG.expose_prompt_debug:
            text, brief, breakdown, timings = await generate_response_with_debug(
                body.message, graph_ctx, history, pref_nodes, session_type,
                prev_brief, locked_piece_frame, render_mode,
            )
            return text, brief, breakdown, timings
        text, brief, timings = await generate_response(
            body.message, graph_ctx, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame, render_mode,
        )
        return text, brief, None, timings

    response_text, piece_brief, prompt_breakdown, gen_timings = await generate()

    # B1: output guardrail — the only watcher of the prose renderer's actual
    # output, never skipped (Change 4). Timed for the per-stage breakdown (Change 5).
    og_t = time.perf_counter()
    output_check = await check_output(response_text, body.message)
    output_guard_ms = _ms_since(og_t)
    if output_check.decision == SafetyDecision.UNSAFE:
        logger.warning(
            "Output guardrail tripped",
            extra={
                "user_id": str(current_user_id),
                "categories": output_check.categories,
                "reasoning": output_check.reasoning,
            },
        )
        response_text = APP_CONFIG.guardrail_refusal_message

    # Per-stage latency (Change 5): generation sub-timings + the guard timings.
    stage_timings = {**gen_timings, "output_guard_ms": output_guard_ms}
    if input_guard_ms is not None:
        stage_timings["input_guard_ms"] = input_guard_ms

    # C2/K: persist the turn + B2 generation inputs + B4 observational signal.
    await history_service.save_turn(
        body.conversation_id,
        current_user_id,
        message_id,
        body.client_message_id,
        body.message,
        response_text,
        input_node_ids=[n.id for n in graph_ctx.relevant_nodes],
        input_interpretation_ids=[i["id"] for i in graph_ctx.interpretations],
        steering_objective=steer["tag"] if steer else None,
        msg_char_len=len(body.message),
        msg_token_len=len(body.message.split()),  # cheap proxy until a tokenizer is wired
        response_latency_ms=int((time.perf_counter() - t0) * 1000),
        piece_brief=piece_brief.model_dump(mode="json") if piece_brief else None,
        stage_timings=stage_timings,
        regenerate_of=body.regenerate_of,
        render_mode=render_mode,
    )

    # Change 2: persist the director's (possibly re-framed) piece-state as this
    # conversation's lock, so next turn receives it as a fixed invariant instead of
    # re-guessing subject/POV/figures. Only piece briefs carry piece_frame — a
    # conversational ResponseStance (or single-model None) has none, so skip those.
    if getattr(piece_brief, "piece_frame", None) is not None:
        try:
            await history_service.set_conversation_piece_frame(
                body.conversation_id, current_user_id,
                piece_brief.piece_frame.model_dump(mode="json"),
            )
        except Exception:
            logger.warning(
                "piece-state lock persist failed", extra={"user_id": str(current_user_id)}
            )

    # Change 1: graph mutations are produced asynchronously by the worker, so they
    # are no longer available to return here — the client polls /processing for new
    # nodes. The mutation fields are intentionally empty.
    response = MessageResponse(
        message_id=message_id,
        conversation_id=body.conversation_id,
        session_number=session_number,
        response_text=response_text,
        propositions=[],
        propositions_skipped=[],
        nodes_created=[],
        nodes_updated=[],
        edges_created=[],
        edges_updated=[],
        prompt_context=prompt_breakdown,
        piece_brief=(
            piece_brief
            if APP_CONFIG.expose_prompt_debug and isinstance(piece_brief, PieceBrief)
            else None
        ),
        is_piece=render_mode in GENERATIVE_MODES,
    )

    # E: cache the response so a retry replays it instead of re-processing.
    await store_response(
        current_user_id, body.client_message_id, response.model_dump(mode="json")
    )
    return response


@router.post("/{message_id}/supersede", status_code=status.HTTP_204_NO_CONTENT)
async def supersede_message(
    message_id: UUID,
    current_user_id: CurrentUserID,
) -> None:
    """
    Drop a beat from canon (it was regenerated away). It stays in the full
    stream but no longer appears in the canon view or prompt history.
    """
    await history_service.supersede_turn(current_user_id, message_id)


@router.post("/{message_id}/feedback")
async def post_feedback(
    message_id: UUID,
    body: FeedbackRequest,
    current_user_id: CurrentUserID,
) -> dict:
    """
    Per-message check/x feedback (B3). 'check' reinforces the nodes/interpretations
    that fed this generation and unlocks the analytic-branch affordance; 'x' stores
    a delivery-tuning note (never psychoanalyzed — A1.5).
    """
    return await feedback_service.record_feedback(
        current_user_id, message_id, body.reaction, body.note
    )


@router.post("/chips/accept", status_code=status.HTTP_204_NO_CONTENT)
async def accept_chip(
    body: ChipAcceptRequest,
    current_user_id: CurrentUserID,
) -> None:
    """
    Directional-chip tap (P0.3A / P2.5). Logs an accept_chip action and reinforces the
    offered concept at REDUCED weight (0.3) with provenance offered_and_accepted — a tap
    is weaker evidence than a volunteered ask (anti-passivity). No Mention (no verbatim
    user words).
    """
    await actions.record_action(
        current_user_id, body.conversation_id, "accept_chip",
        payload={"concept_slug": body.concept_slug, "chip_text": body.chip_text},
    )
    slugs = [body.concept_slug]
    await graph_service.reinforce_nodes(
        current_user_id, slugs, weight=graph_service.CHIP_REINFORCE_WEIGHT
    )
    await graph_service.stamp_provenance(
        current_user_id, slugs,
        source="offered_chip", elicited="offered_and_accepted",
    )


@router.post("/{message_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_with_note(
    message_id: UUID,
    body: RetryNoteRequest,
    current_user_id: CurrentUserID,
) -> dict:
    """
    Retry a beat, optionally with a note (P0.3B / P2.5). Logs the retry action; when a note
    is present, fires the classifier fire-and-forget to route GRAPH-FEEDING (content →
    extraction with the original message + rejected beat as relative context; delivery →
    #10a later; discard → dropped). The reroll itself is a separate message POST
    (regenerate_of) that consumes the whole raw note — never gated on this.
    """
    note = (body.note or "").strip()
    turn = await history_service.get_turn_for_retry(current_user_id, message_id)
    if turn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turn not found")

    await actions.record_action(
        current_user_id, turn["conversation_id"], "retry",
        target_turn_id=message_id, render_mode=turn.get("render_mode"),
        payload={"has_note": bool(note)},
    )

    if note:
        session_number = await sessions.get_or_create_current_session(current_user_id)
        # Fire-and-forget: graph-feeding must never make the user's reroll wait (§P0.3B).
        asyncio.create_task(
            retry_note_classifier.route_retry_note(
                current_user_id,
                turn["conversation_id"],
                message_id,
                note,
                turn["user_message"] or "",
                turn["response_text"] or "",
                session_number=session_number,
            )
        )
    return {"ok": True, "has_note": bool(note)}


@router.post("/{message_id}/length")
async def adapt_length(
    message_id: UUID,
    body: LengthRequest,
    current_user_id: CurrentUserID,
) -> dict:
    """
    Longer/shorter reaction (P4.1). Logs the action and moves the per-mode word target one
    damped, clamped step. Returns the new target so the client can regenerate at the
    adapted length. Delivery-tuning only — never touches the graph.
    """
    turn = await history_service.get_turn_for_retry(current_user_id, message_id)
    if turn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turn not found")
    render_mode = turn.get("render_mode")
    await actions.record_action(
        current_user_id, turn["conversation_id"], body.direction,
        target_turn_id=message_id, render_mode=render_mode,
    )
    new_target = await render_prefs.bump(current_user_id, render_mode, body.direction)
    return {"direction": body.direction, "render_mode": render_mode, "target_words": new_target}


@router.post("/test-piece")
@limiter.limit("20/minute")
async def post_test_piece(
    request: Request,
    body: TestPieceRequest,
    current_user_id: CurrentUserID,
) -> dict:
    """
    B9: the engine offers a short piece targeting the thinnest dimension, as an
    experience to react to. Saved as a turn that records its target, so the user's
    check/x (B3) maps to coverage (positive) or a boundary (negative — equally useful).
    """
    session_number = await sessions.get_or_create_current_session(current_user_id)
    result = await test_piece.generate(current_user_id, session_number)
    if not result:
        return {"offered": False}

    message_id = uuid4()
    await history_service.save_turn(
        body.conversation_id,
        current_user_id,
        message_id,
        uuid4(),                      # synthetic client_message_id (engine-offered)
        "",                           # no user message — the engine initiated this
        result["piece"],
        input_node_ids=result["node_ids"],
        steering_objective=result["tag"],
        render_mode="author",  # engine-offered piece — generative by construction
    )
    return {
        "offered": True,
        "message_id": str(message_id),
        "response_text": result["piece"],
    }


@router.post("/chips", response_model=ChipResponse)
@limiter.limit("60/minute")
async def post_chips(
    request: Request,
    body: ChipRequest,
    current_user_id: CurrentUserID,
) -> ChipResponse:
    """
    Generate three graph-informed reaction chips for the current beat
    (advance / regenerate / wildcard) — the single-stream cowriter's reaction model.
    """
    from services.chips import generate_chips

    session_number = await sessions.get_or_create_current_session(current_user_id)
    chips = await generate_chips(
        body.beat, current_user_id, session_number,
        conversation_id=body.conversation_id,
    )
    return ChipResponse(chips=chips)


def _sse(obj: dict) -> str:
    """Serialize a dict as a single SSE 'data:' frame."""
    return f"data: {json.dumps(obj)}\n\n"


async def _tokens_with_warming(token_iter, threshold: float):
    """Wrap a token stream (P5.4): yield ('warming', None) once if the FIRST token doesn't
    arrive within `threshold` seconds, then ('token', chunk) for every token. Uses
    asyncio.wait (not wait_for) so a slow first token is NOT cancelled — the pending
    __anext__ keeps running and its token is still delivered. threshold<=0 disables it."""
    it = token_iter.__aiter__()
    first = asyncio.ensure_future(it.__anext__())
    if threshold and threshold > 0:
        done, _pending = await asyncio.wait({first}, timeout=threshold)
        if not done:
            yield ("warming", None)
    try:
        chunk = await first          # completes whether it was fast or slow
    except StopAsyncIteration:
        return
    yield ("token", chunk)
    async for chunk in it:
        yield ("token", chunk)


# Anti-buffering headers so intermediaries (Cloudflare tunnel, nginx) flush each
# SSE frame immediately instead of holding the response until completion — which
# is what makes a working token stream still appear "all at once" to the client.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


@router.post("/stream")
@limiter.limit("30/minute")
async def post_message_stream(
    request: Request,
    body: MessageRequest,
    current_user_id: CurrentUserID,
) -> StreamingResponse:
    """
    Server-Sent Events variant of POST /messages. Event types:
      - {"type": "context", "payload": {...}}  labeled prompt breakdown (debug only)
      - {"type": "token", "text": "..."}       incremental response text
      - {"type": "safety_override", "text": ...} discard buffered text, show refusal
      - {"type": "done", "payload": {...}}      final MessageResponse
      - {"type": "error", "detail": "..."}      something failed

    The existing non-streaming POST /messages is kept intact for idempotency
    replay and any non-streaming caller.
    """
    # Idempotency replay — stream the cached text then done.
    cached = await claim_or_get_cached_response(
        current_user_id, body.conversation_id, body.client_message_id
    )
    if cached is not None:
        async def replay():
            yield _sse({"type": "token", "text": cached["response_text"]})
            yield _sse({"type": "done", "payload": cached})
        return StreamingResponse(
            replay(), media_type="text/event-stream", headers=_SSE_HEADERS
        )

    t0 = time.perf_counter()  # B4: response latency
    session_number = await sessions.get_or_create_current_session(current_user_id)

    # Input guard + graph context (Change 4): the input guard is SKIPPED on the
    # split path (Sonnet director is the bright-line floor); when it runs it fires
    # CONCURRENTLY with context build, for zero added latency. H9: context degrades
    # gracefully if Qdrant is unreachable.
    async def _ctx() -> GraphContext:
        try:
            return await graph_service.build_graph_context(
                body.message, current_user_id, session_number
            )
        except Exception:
            return GraphContext(relevant_nodes=[], relevant_edges=[])

    input_guard_ms: int | None = None
    if _run_input_guard():
        ig_t = time.perf_counter()
        input_check, graph_ctx = await asyncio.gather(check_input(body.message), _ctx())
        input_guard_ms = _ms_since(ig_t)
        if input_check.decision == SafetyDecision.UNSAFE:
            logger.warning(
                "Input guardrail tripped (stream)",
                extra={"user_id": str(current_user_id), "categories": input_check.categories},
            )

            async def refuse():
                yield _sse({"type": "token", "text": APP_CONFIG.guardrail_refusal_message})
                yield _sse({"type": "done", "payload": None})
            return StreamingResponse(
                refuse(), media_type="text/event-stream", headers=_SSE_HEADERS
            )
    else:
        graph_ctx = await _ctx()

    # Flow 2 (B5): inject idiographic interpretations relevant to this turn.
    try:
        graph_ctx.interpretations = await graph_service.get_interpretations_for_nodes(
            current_user_id, [n.id for n in graph_ctx.relevant_nodes]
        )
    except Exception:
        graph_ctx.interpretations = []

    display_name = body.user_display_name or "Me"

    history, pref_nodes, active_predicates, self_node_id, session_type = (
        await asyncio.gather(
            history_service.get_recent_turns(
                body.conversation_id, current_user_id, APP_CONFIG.recent_messages_limit
            ),
            graph_service.get_preference_nodes(current_user_id),
            graph_service.get_top_predicates(current_user_id, limit=15),
            graph_service.ensure_self_node(current_user_id, display_name),
            history_service.get_session_type(body.conversation_id, current_user_id),
        )
    )

    # C3: infer the render mode (conversational default | piece | analysis).
    render_mode = _resolve_render_mode(body, session_type)

    # P4.1: publish the learned length target for this mode (request-ambient). Best-effort.
    await _apply_length_pref(current_user_id, render_mode)
    await _apply_model_pref(current_user_id)

    # Session dials (§4) — feeds the dynamics layer, steering gate, ingest stamping.
    try:
        session_state = await dynamics.get_session_state(
            current_user_id, body.conversation_id, session_type
        )
        if graph_ctx.relevant_nodes:
            session_state.active_region = graph_ctx.relevant_nodes[0].name
        graph_ctx.session_state = session_state.model_dump(mode="json")
    except Exception:
        logger.warning("session state unavailable (stream)")
        session_state = None

    clearly_engaged = bool(
        session_state is None or session_state.gate_position.value != "guarded"
    )
    depth_ramp = session_state.depth_ramp.value if session_state else ""

    # Flow 3/4 (B5, §5): steering — gates filtered, dial-aware.
    try:
        steer = await steering.select_objective(
            current_user_id,
            session_number,
            gate_position=session_state.gate_position.value if session_state else "neutral",
        )
    except Exception:
        steer = None
    graph_ctx.steering_objective = steer["objective"] if steer else None

    # Prior-turn director state: carry-forward brief (arc, Change 1) + locked
    # piece-state (Change 2). Both None on turn one.
    prev_brief, locked_piece_frame = await asyncio.gather(
        history_service.get_last_piece_brief(body.conversation_id, current_user_id),
        history_service.get_conversation_piece_frame(body.conversation_id, current_user_id),
    )

    message_id = uuid4()

    # Change 1: hand extraction + the graph-mutation tail to the background worker
    # (the same queue as the non-stream path) — off the token path entirely. Done
    # here (not inside the generator) so it's enqueued even if the client never
    # consumes the stream; the worker drains it regardless of streaming outcome.
    await _enqueue_extraction(
        body, current_user_id, session_number, message_id, graph_ctx,
        active_predicates, display_name, self_node_id, steer,
        clearly_engaged=clearly_engaged, depth_ramp=depth_ramp,
    )

    async def event_stream():
        # Debug context event — emitted once, before tokens.
        if APP_CONFIG.expose_prompt_debug:
            _, prompt_breakdown = build_response_messages_debug(
                body.message, graph_ctx, history, pref_nodes, session_type
            )
            yield _sse({"type": "context", "payload": prompt_breakdown})

        # Stream tokens into a buffer AND to the client. With the split on, the
        # director runs first (inside open_response_stream) and the brief is ready
        # before any token — emit it as a debug event, then stream the renderer.
        buffer: list[str] = []
        piece_brief = None
        gen_timings: dict = {}
        gen_start = time.perf_counter()
        try:
            piece_brief, token_iter, gen_timings = await open_response_stream(
                body.message, graph_ctx, history, pref_nodes, session_type,
                prev_brief, locked_piece_frame, render_mode,
            )
            if APP_CONFIG.expose_prompt_debug and piece_brief is not None:
                yield _sse({"type": "brief", "payload": piece_brief.model_dump(mode="json")})
            # P5.4: if the first token is slow (serverless cold start), emit an honest
            # 'warming' event before it — never a fake progress bar.
            async for kind, chunk in _tokens_with_warming(
                token_iter, APP_CONFIG.warming_ttft_s
            ):
                if kind == "warming":
                    yield _sse({"type": "warming"})
                    continue
                buffer.append(chunk)
                yield _sse({"type": "token", "text": chunk})
        except Exception:
            logger.exception("Stream generation failed")
            yield _sse({"type": "error", "detail": "generation failed"})
            return

        # The single-model stream generates lazily as it's consumed, so its time is
        # only known now (Change 5); the split path already returned director/render.
        if not gen_timings:
            gen_timings = {"generate_ms": _ms_since(gen_start)}

        full_text = "".join(buffer)

        # Post-hoc output guardrail (timed — Change 5). Never skipped: it is the only
        # watcher of the prose renderer's actual output (Change 4).
        og_t = time.perf_counter()
        output_check = await check_output(full_text, body.message)
        output_guard_ms = _ms_since(og_t)
        if output_check.decision == SafetyDecision.UNSAFE:
            logger.warning(
                "Output guardrail tripped (stream)",
                extra={"user_id": str(current_user_id)},
            )
            full_text = APP_CONFIG.guardrail_refusal_message
            yield _sse({"type": "safety_override", "text": full_text})

        stage_timings = {**gen_timings, "output_guard_ms": output_guard_ms}
        if input_guard_ms is not None:
            stage_timings["input_guard_ms"] = input_guard_ms

        await history_service.save_turn(
            body.conversation_id, current_user_id, message_id,
            body.client_message_id, body.message, full_text,
            input_node_ids=[n.id for n in graph_ctx.relevant_nodes],
            input_interpretation_ids=[i["id"] for i in graph_ctx.interpretations],
            steering_objective=steer["tag"] if steer else None,
            msg_char_len=len(body.message),
            msg_token_len=len(body.message.split()),
            response_latency_ms=int((time.perf_counter() - t0) * 1000),
            piece_brief=piece_brief.model_dump(mode="json") if piece_brief else None,
            stage_timings=stage_timings,
            regenerate_of=body.regenerate_of,
            render_mode=render_mode,
        )

        # Change 2: persist the piece-state lock for next turn — piece briefs only
        # (a conversational ResponseStance / analysis None has no piece_frame).
        if getattr(piece_brief, "piece_frame", None) is not None:
            try:
                await history_service.set_conversation_piece_frame(
                    body.conversation_id, current_user_id,
                    piece_brief.piece_frame.model_dump(mode="json"),
                )
            except Exception:
                logger.warning("piece-state lock persist failed (stream)")

        # Change 1: graph mutations are produced asynchronously by the worker, so the
        # mutation fields are intentionally empty — the client polls /processing.
        response = MessageResponse(
            message_id=message_id,
            conversation_id=body.conversation_id,
            session_number=session_number,
            response_text=full_text,
            propositions=[],
            propositions_skipped=[],
            nodes_created=[],
            nodes_updated=[],
            edges_created=[],
            edges_updated=[],
            piece_brief=(
                piece_brief
                if APP_CONFIG.expose_prompt_debug and isinstance(piece_brief, PieceBrief)
                else None
            ),
            is_piece=render_mode in GENERATIVE_MODES,
        )
        payload = response.model_dump(mode="json")

        await store_response(current_user_id, body.client_message_id, payload)

        yield _sse({"type": "done", "payload": payload})

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
