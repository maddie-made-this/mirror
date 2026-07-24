import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator

from config.loader import APP_CONFIG
from core import request_context
from llm.client import chat, chat_stream
from llm.prompts import (
    build_author_director_messages,
    build_author_director_messages_debug,
    build_author_renderer_messages,
    build_conversational_director_messages,
    build_conversational_renderer_messages,
    build_director_messages,
    build_director_messages_debug,
    build_dual_director_messages,
    build_renderer_messages,
    build_response_messages,
    build_response_messages_debug,
    build_segment_renderer_messages,
)
from schemas.graph import GraphContext, GraphNode
from schemas.message import ConversationTurn
from schemas.response_stance import ResponseStance
from schemas.piece_brief import PieceBrief, SegmentedPlan

logger = logging.getLogger(__name__)

# Temperatures: the director PLANS (lower — we want a crisp decision), the renderer
# WRITES (higher — prose variety). The single-model path keeps the prior 0.7.
_DIRECTOR_TEMP = 0.4
_RENDERER_TEMP = 0.85
_SINGLE_TEMP = 0.7

# Anti-loop guard: if the renderer's draft shares more than this fraction of its
# word n-grams with the PREVIOUS beat, treat it as a verbatim loop and regenerate
# once. The split's whole value is killing the repetition loop; a smaller renderer does not reliably
# obey the brief's do_not_repeat, so this is the backstop that does.
_REPEAT_NGRAM = 6
_REPEAT_THRESHOLD = 0.25

# Semantic anti-loop (Change 5): the n-gram check only catches VERBATIM repeats; a
# beat that re-does the previous activity in fresh words (the semantic loop) sails under
# it. Back it with an embedding-cosine check against the previous beat. Conservative
# default — same-activity/fresh-words tends to land high on text-embedding-3-small;
# NEEDS LIVE CALIBRATION (logged when it fires so the dump can show it). Set > 1.0 to
# disable the semantic pass.
_SEMANTIC_REPEAT_THRESHOLD = 0.93


def _ms_since(start: float) -> int:
    """Whole-millisecond elapsed since a perf_counter() reading (Change 5 timing)."""
    return int((time.perf_counter() - start) * 1000)


# The session types that get the heavy director/renderer piece apparatus. An explicit
# allowlist (insight-synthesis addendum) is safer than the old "anything but analytic":
# a new session_type defaults OUT of the split instead of silently INTO it. Since C3 the
# piece paths are reached only when render_mode=="piece" (which already implies a primary
# session); this keeps the predicate correct independent of that routing.
_COWRITE_SESSION_TYPES = {"primary"}


def _split_on(session_type: str) -> bool:
    """
    The director/renderer split runs for piece turns only. The analytic branch is
    reasoning/explanation with no explicit rendering, so it stays director-only —
    served by the single-model path pointed at the frontier response model.
    """
    return APP_CONFIG.use_director_split and session_type in _COWRITE_SESSION_TYPES


def _dual_on(session_type: str) -> bool:
    """Dual-model render (Change 6): only on piece turns, and only when both the split
    and dual flags are set. Otherwise the standard split (or single model) runs."""
    return APP_CONFIG.use_dual_render and _split_on(session_type)


def _response_model() -> str:
    """The response model for THIS turn: the user's validated choice when they have
    one, else the deployment default. Read here rather than threaded through every
    generate/stream signature — see core.request_context."""
    return request_context.get_response_model() or APP_CONFIG.response_model_resolved


def _resolve_segment_model(label: str) -> str:
    """Map a segment's model LABEL to the actual model string: 'reasoner' -> the
    reasoner (response_model_resolved, strong connective prose), anything else
    ('stylist') -> the prose renderer (renderer_model_resolved)."""
    if label == "reasoner":
        return _response_model()
    return APP_CONFIG.renderer_model_resolved


def _ngrams(text: str, n: int) -> list[tuple[str, ...]]:
    words = re.findall(r"\w+", (text or "").lower())
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


def _repetition_ratio(new: str, prev: str, n: int = _REPEAT_NGRAM) -> float:
    """Fraction of the NEW text's word n-grams that also appear in the previous beat.
    ~0 for a fresh beat; high when the renderer parroted the last reply verbatim."""
    grams = _ngrams(new, n)
    if not grams:
        return 0.0
    prev_set = set(_ngrams(prev, n))
    if not prev_set:
        return 0.0
    return sum(1 for g in grams if g in prev_set) / len(grams)


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 on a degenerate input."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


async def _semantic_similarity(a: str, b: str) -> float | None:
    """Cosine between two beats' embeddings (Change 5 semantic backstop). Returns
    None on empty input or any embedding failure, so the check degrades to a no-op
    rather than breaking generation."""
    if not a.strip() or not b.strip():
        return None
    try:
        from services.embedding import embed_batch
        vecs = await embed_batch([a, b])
    except Exception:
        logger.warning("semantic repetition check: embedding failed", exc_info=True)
        return None
    if len(vecs) != 2:
        return None
    return _cosine(vecs[0], vecs[1])


def _fallback_brief(prev_brief: dict | PieceBrief | None = None) -> PieceBrief:
    """
    Brief used when the director output won't parse. When the last good brief is
    available, CARRY IT FORWARD — keep its piece_frame and do_not_repeat so the
    renderer still has who/where and the anti-loop list — and just force advancement.
    Falls back to a minimal stub only when there's no prior brief.
    """
    advance = (
        "Move the piece forward from the last beat — introduce a new action or "
        "detail; do NOT restate or paraphrase the previous beat."
    )
    if prev_brief is not None:
        try:
            base = (
                prev_brief
                if isinstance(prev_brief, PieceBrief)
                else PieceBrief.model_validate(prev_brief)
            )
            base = base.model_copy(deep=True)
            base.action = "write"
            base.question = None
            base.advance_directive = advance
            return base
        except Exception:
            logger.warning("carry-forward fallback failed; using minimal stub", exc_info=True)
    return PieceBrief(action="write", advance_directive=advance)


_MAX_DO_NOT_REPEAT = 6  # bound the anti-repeat list server-side (Change 2)


def _finalize_brief(brief, prev_brief: dict | None) -> None:
    """Server-side finalization (Changes 1 & 2). Mutates brief in place; works on a
    PieceBrief or a SegmentedPlan (both carry the fields):
      - Bounded memory (Change 1): grow beat_history by appending this turn's
        next_beat to the prior log, so the director never re-emits the growing list.
        Only arc_synopsis + the tail re-enter the prompt → director latency stays flat.
      - Brief compression (Change 2): keep only the most recent do_not_repeat entries
        so that list can't grow unboundedly into the prompt either."""
    prev = list((prev_brief or {}).get("beat_history") or [])
    nb = (getattr(brief, "next_beat", "") or "").strip()
    if nb and (not prev or prev[-1] != nb):
        prev.append(nb)
    brief.beat_history = prev
    dnr = getattr(brief, "do_not_repeat", None)
    if isinstance(dnr, list) and len(dnr) > _MAX_DO_NOT_REPEAT:
        brief.do_not_repeat = dnr[-_MAX_DO_NOT_REPEAT:]


async def _run_director(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> PieceBrief:
    """Director call: emit a PieceBrief. Capped by director_max_tokens (generous —
    a brief is short, so it never truncates; but a cap bounds OpenRouter's worst-case
    credit reserve, which otherwise 402s an expensive uncapped reasoner). On a parse
    failure, retry ONCE with a 'JSON only' corrective turn before falling back.
    locked_piece_frame (Change 2) is the persisted subject/POV/figures the director must
    treat as fixed; prev_brief (Change 1) carries the arc forward."""
    messages = build_director_messages(
        message, graph_context, history, pref_nodes, session_type,
        prev_brief=prev_brief, locked_piece_frame=locked_piece_frame,
    )
    raw = await chat(
        messages, model=APP_CONFIG.director_model_resolved, temperature=_DIRECTOR_TEMP,
        max_tokens=APP_CONFIG.director_max_tokens,
    )
    brief = PieceBrief.parse(raw)
    if brief is None:
        logger.warning("director brief unparseable; retrying once. raw=%r", (raw or "")[:300])
        retry = messages + [
            {"role": "assistant", "content": raw or ""},
            {"role": "user", "content": (
                "That was not valid. Output ONLY the PieceBrief JSON object — no "
                "prose, no preamble, no markdown fence."
            )},
        ]
        raw2 = await chat(
            retry, model=APP_CONFIG.director_model_resolved, temperature=_DIRECTOR_TEMP,
            max_tokens=APP_CONFIG.director_max_tokens,
        )
        brief = PieceBrief.parse(raw2)
    if brief is None:
        logger.warning("director brief still unparseable; using carry-forward fallback")
        return _fallback_brief(prev_brief)
    _finalize_brief(brief, prev_brief)
    return brief


async def _render(
    brief: PieceBrief,
    message: str,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
) -> str:
    """Renderer call: brief -> prose. Backstops the renderer's unreliable do_not_repeat
    obedience with a post-generation repetition check against the previous beat; on
    a detected loop, regenerate ONCE with an explicit anti-repeat nudge."""
    messages = build_renderer_messages(brief, message, history, pref_nodes, session_type)
    text = await chat(
        messages,
        model=APP_CONFIG.renderer_model_resolved,
        temperature=_RENDERER_TEMP,
        max_tokens=APP_CONFIG.response_max_tokens,
        role="renderer",
    )
    prev = history[-1].response_text if history else ""
    if not (prev or "").strip():
        return text

    # Two-pass anti-loop, at most ONE regeneration. Cheap verbatim n-gram first; if
    # that's clean, the semantic backstop (Change 5) catches the same-activity-fresh-
    # words loop the n-gram check can't see.
    regen_reason = ""
    ratio = _repetition_ratio(text, prev)
    if ratio > _REPEAT_THRESHOLD:
        regen_reason = f"verbatim {ratio:.2f}"
    else:
        sim = await _semantic_similarity(text, prev)
        if sim is not None and sim > _SEMANTIC_REPEAT_THRESHOLD:
            regen_reason = f"semantic {sim:.2f}"

    if regen_reason:
        logger.info("renderer repetition (%s); regenerating once", regen_reason)
        nudge = {"role": "system", "content": (
            "Your draft re-did the previous beat — the same ground, whether or not the "
            "words differ. That is the one thing you must not do. Write a DIFFERENT "
            "beat that MOVES THE PIECE FORWARD — a new action, a new observation, a new "
            "place in the arc. Do not restate or paraphrase the last reply."
        )}
        text = await chat(
            messages + [nudge],
            model=APP_CONFIG.renderer_model_resolved,
            temperature=min(0.95, _RENDERER_TEMP + 0.1),
            max_tokens=APP_CONFIG.response_max_tokens,
            role="renderer",
        )
    return text


async def _run_author(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
) -> tuple[str, PieceBrief, dict]:
    """AUTHOR-MODE one-shot (Option A): one full-arc director brief -> one complete-piece
    render. Bypasses the beat machine entirely — no prev_brief carry-forward, no
    _finalize_brief beat append, no repetition-check-against-previous-beat (there is no
    previous beat). This is the long-form authoring primary function."""
    t0 = time.perf_counter()
    messages = build_author_director_messages(
        message, graph_context, history, pref_nodes, session_type,
    )
    raw = await chat(
        messages, model=APP_CONFIG.author_director_model_resolved,
        temperature=_DIRECTOR_TEMP,
        max_tokens=APP_CONFIG.author_director_max_tokens,
    )
    brief = PieceBrief.parse(raw)
    if brief is None:
        logger.warning("author director brief unparseable; retrying once. raw=%r", (raw or "")[:300])
        retry = messages + [
            {"role": "assistant", "content": raw or ""},
            {"role": "user", "content": (
                "That was not valid. Output ONLY the PieceBrief JSON object — no prose, "
                "no preamble, no markdown fence."
            )},
        ]
        raw2 = await chat(
            retry, model=APP_CONFIG.author_director_model_resolved,
            temperature=_DIRECTOR_TEMP,
            max_tokens=APP_CONFIG.author_director_max_tokens,
        )
        brief = PieceBrief.parse(raw2) or PieceBrief(action="write")
    # FORCE author invariants regardless of what the director emitted — the envelope
    # discourages asking; this makes a surviving ask impossible (the variance-run failure).
    brief.action = "write"
    brief.question = None
    # NO _finalize_brief — that appends to beat_history (beat-machine bookkeeping).
    director_ms = _ms_since(t0)

    t1 = time.perf_counter()
    text = await _render_author(brief, message, history, pref_nodes, session_type)
    render_ms = _ms_since(t1)
    return text, brief, {"director_ms": director_ms, "render_ms": render_ms}


# Leaked-scaffolding patterns the renderer sometimes emits despite the system text
# forbidding them (observed in BAKEOFF_20260624_132316 run 4).
_PREAMBLE_RE = re.compile(
    r"^\s*(here\s+is\s+(a|the|your)\b[^\n]*\n+|sure[,!]?\s*[^\n]*\n+|"
    r"```[a-z]*\n?)",
    re.I,
)
# A beat header line: optional leading space, a number, dot/paren, then the beat clause.
# Matches the "1. Opening statement of the problem — ..." headers leaked from piece_beats.
_BEAT_HEADER_RE = re.compile(r"^\s*\d{1,2}[.)]\s+.*$", re.M)


def _strip_render_scaffolding(text: str, beats: list[str]) -> str:
    """Remove leaked preamble and beat-number headers the renderer printed despite the
    prompt forbidding them. Conservative: only strips a numbered line if it closely
    matches a brief beat clause (so genuine in-prose numbers like dialogue '...for the
    third time' aren't touched)."""
    if not text:
        return text
    out = _PREAMBLE_RE.sub("", text, count=1).strip()
    if beats:
        # Normalize the SAME way as the line body below — the author-director emits
        # piece_beats WITH their own leading "N." numbering, so match on the clause.
        beat_keys = [
            re.sub(r"^\s*\d{1,2}[.)]\s+", "", b).strip().lower()[:25]
            for b in beats
            if b.strip()
        ]
        kept = []
        for line in out.splitlines():
            if _BEAT_HEADER_RE.match(line):
                # strip the leading "N. " and see if the remainder echoes a beat clause
                body = re.sub(r"^\s*\d{1,2}[.)]\s+", "", line).strip().lower()
                if any(body[:25] == k or k in body[:40] for k in beat_keys):
                    continue  # drop the leaked header line
            kept.append(line)
        out = "\n".join(kept).strip()
    return out


def _looks_complete(text: str, brief: PieceBrief) -> bool:
    """Heuristic: did the render reach the payoff? A complete author piece should clear the
    length floor — the strongest available signal without a classifier. Truncated runs
    measured 334/533/554w and stopped at ~beat 6; the complete one was 1144w."""
    words = len((text or "").split())
    return words >= APP_CONFIG.author_render_word_floor


_SENTENCE_END_RE = re.compile(r'[.!?]"?(?=\s|$)')


def _trim_to_sentence(text: str) -> str:
    """Trim a render back to its last COMPLETE sentence. The author max_tokens cap can clip
    mid-sentence (the 'doorknob' truncation); if the text doesn't end on terminal punctuation,
    cut back to the last sentence boundary so the piece ends cleanly (SPEC 3b)."""
    if not text:
        return text
    t = text.rstrip()
    if not t or t[-1] in '.!?"':
        return t
    ends = list(_SENTENCE_END_RE.finditer(t))
    if ends:
        cut = ends[-1].end()
        if cut >= len(t) * 0.6:  # only trim a genuine tail fragment, never gut the piece
            return t[:cut].rstrip()
    return t


async def _render_author(
    brief: PieceBrief,
    message: str,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
) -> str:
    """Render the COMPLETE piece at the VALIDATED config (SPEC_production_renderer_backend 3),
    then ENFORCE what the prompt asks for and the model intermittently ignores: the
    validated sampler (LOW rep-penalty + temp/top_p, 1400 cap — 3a), a banned-phrase
    instruction (3c),
    strip leaked scaffolding, regenerate ONCE if short of the floor, and trim to the last
    complete sentence so the cap never leaves a mid-sentence clip (3b). No anti-loop pass —
    there is no previous beat to loop against in a one-shot render."""
    beats = [b.strip() for b in (brief.piece_beats or []) if b.strip()]
    messages = build_author_renderer_messages(brief, message, history, pref_nodes, session_type)
    banned = APP_CONFIG.author_render_banned_phrases
    if banned:
        messages = messages + [{"role": "system", "content":
            "Avoid these overused phrases entirely; vary the wording: " + "; ".join(banned) + "."}]
    # Validated sampler (3a). Skip no-op values so a strict provider isn't sent params it rejects.
    sampling: dict = {"top_p": APP_CONFIG.author_render_top_p}
    if APP_CONFIG.author_render_rep_penalty and APP_CONFIG.author_render_rep_penalty != 1.0:
        sampling["repetition_penalty"] = APP_CONFIG.author_render_rep_penalty
    if APP_CONFIG.author_render_freq_penalty:
        sampling["frequency_penalty"] = APP_CONFIG.author_render_freq_penalty
    if APP_CONFIG.author_render_presence_penalty:
        sampling["presence_penalty"] = APP_CONFIG.author_render_presence_penalty
    render_kw = dict(
        model=APP_CONFIG.renderer_model_resolved,
        temperature=APP_CONFIG.author_render_temperature,
        sampling=sampling,
        max_tokens=APP_CONFIG.author_response_max_tokens,
        role="renderer",
    )
    text = await chat(messages, **render_kw)
    text = _strip_render_scaffolding(text, beats)
    if not _looks_complete(text, brief):
        logger.info("author render short (%d words); regenerating once", len(text.split()))
        # Regenerate (not continue — avoids a visible seam). A short, firm reminder is
        # appended; the base prompt already carries the full instruction.
        retry_messages = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": (
                "That stopped short of the full piece. Write the COMPLETE piece again, "
                "rendering every beat through the final payoff — do not stop early, do "
                "not print beat numbers or any preamble. One continuous story."
            )},
        ]
        retry = await chat(retry_messages, **render_kw)
        retry = _strip_render_scaffolding(retry, beats)
        # Keep whichever is longer — the retry can occasionally also short; never return
        # the shorter of the two.
        if len(retry.split()) > len(text.split()):
            text = retry
    return _trim_to_sentence(text)


async def _run_dual_director(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> SegmentedPlan | None:
    """Dual-model director call: emit a SegmentedPlan. Capped + parse-retry like the
    split director. Returns None if still unparseable (caller degrades to the split)."""
    messages = build_dual_director_messages(
        message, graph_context, history, pref_nodes, session_type,
        prev_brief=prev_brief, locked_piece_frame=locked_piece_frame,
    )
    raw = await chat(
        messages, model=APP_CONFIG.director_model_resolved, temperature=_DIRECTOR_TEMP,
        max_tokens=APP_CONFIG.director_max_tokens,
    )
    plan = SegmentedPlan.parse(raw)
    if plan is None:
        logger.warning("dual plan unparseable; retrying once. raw=%r", (raw or "")[:300])
        retry = messages + [
            {"role": "assistant", "content": raw or ""},
            {"role": "user", "content": (
                "That was not valid. Output ONLY the SegmentedPlan JSON object — no "
                "prose, no preamble, no markdown fence."
            )},
        ]
        raw2 = await chat(
            retry, model=APP_CONFIG.director_model_resolved, temperature=_DIRECTOR_TEMP,
            max_tokens=APP_CONFIG.director_max_tokens,
        )
        plan = SegmentedPlan.parse(raw2)
    if plan is not None:
        _finalize_brief(plan, prev_brief)  # bounded memory + compression (Changes 1-2)
    return plan


async def _run_dual(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> tuple[str, PieceBrief | SegmentedPlan, dict]:
    """
    Dual-model generation (Change 6): the director emits a SegmentedPlan; a RULE
    (role -> model, NOT the director's self-pick) assigns each segment's writer;
    segments render CONCURRENTLY (each from its own directive + the shared smoothing,
    never each other's prose) and are concatenated in index order. Latency ~= the
    director plus the SLOWEST single segment, not the serial sum.

    Returns (text, plan, timings). On an unusable plan, degrades to the proven
    standard split and returns its (text, brief, timings) instead. timings carries
    director_ms, render_ms (gather wall-clock ~= max), and render_reasoner_ms /
    render_stylist_ms (max within each model group) for the per-architecture compare.
    """
    timings: dict[str, int] = {}
    t = time.perf_counter()
    plan = await _run_dual_director(
        message, graph_context, history, pref_nodes, session_type,
        prev_brief, locked_piece_frame,
    )
    timings["director_ms"] = _ms_since(t)

    if plan is None or not plan.segments:
        logger.warning("dual director gave no usable plan; falling back to standard split")
        t = time.perf_counter()
        brief = await _run_director(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
        timings["director_ms"] += _ms_since(t)
        t = time.perf_counter()
        text = await _render(brief, message, history, pref_nodes, session_type)
        timings["render_ms"] = _ms_since(t)
        return text, brief, timings

    # The RULE sets the writer per segment — overriding the director's self-pick so an
    # expressive beat can never be kept by the connective model and flattened.
    for seg in plan.segments:
        seg.model = APP_CONFIG.segment_role_model.get(seg.role, "stylist")
    ordered = sorted(plan.segments, key=lambda s: s.index)

    async def _render_seg(seg):
        s = time.perf_counter()
        try:
            piece = await chat(
                build_segment_renderer_messages(
                    seg, plan, message, history, pref_nodes, session_type
                ),
                model=_resolve_segment_model(seg.model),
                temperature=_RENDERER_TEMP,
                max_tokens=APP_CONFIG.response_max_tokens,
                role="renderer",
            )
        except Exception:
            logger.exception("dual segment render failed", extra={"index": seg.index})
            piece = None
        return seg, piece, _ms_since(s)

    t = time.perf_counter()
    results = await asyncio.gather(*[_render_seg(s) for s in ordered])
    timings["render_ms"] = _ms_since(t)
    # Per-model wall-clock contribution = max within each group (they ran in parallel).
    rea = [ms for seg, _, ms in results if seg.model == "reasoner"]
    sty = [ms for seg, _, ms in results if seg.model != "reasoner"]
    if rea:
        timings["render_reasoner_ms"] = max(rea)
    if sty:
        timings["render_stylist_ms"] = max(sty)

    pieces = [p.strip() for _, p, _ in results if p and p.strip()]
    return "\n\n".join(pieces), plan, timings


# --------------------------------------------------------------------------- #
# Conversational + analysis modes (master spec C3)
# --------------------------------------------------------------------------- #

_CONVERSATIONAL_TEMP = 0.8


async def _run_conversational_director(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
) -> ResponseStance:
    """Cheap conversational director: emit a ResponseStance (capped + parse-retry).
    Falls back to a plain 'engage' stance so the turn always renders."""
    messages = build_conversational_director_messages(
        message, graph_context, history, pref_nodes, session_type
    )
    raw = await chat(
        messages, model=APP_CONFIG.director_model_resolved, temperature=_DIRECTOR_TEMP,
        max_tokens=APP_CONFIG.director_max_tokens,
    )
    stance = ResponseStance.parse(raw)
    if stance is None:
        retry = messages + [
            {"role": "assistant", "content": raw or ""},
            {"role": "user", "content": (
                "Output ONLY the ResponseStance JSON object — no prose, no fence."
            )},
        ]
        raw2 = await chat(
            retry, model=APP_CONFIG.director_model_resolved, temperature=_DIRECTOR_TEMP,
            max_tokens=APP_CONFIG.director_max_tokens,
        )
        stance = ResponseStance.parse(raw2)
    if stance is None:
        logger.warning("conversational stance unparseable; using plain engage")
        stance = ResponseStance(move="engage")
    return stance


async def _run_conversational(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
) -> tuple[str, ResponseStance, dict]:
    """Conversational generation (C3): cheap director -> ResponseStance -> ONE renderer
    call (the prose voice). No generation apparatus. Returns (text, stance, timings)."""
    timings: dict[str, int] = {}
    t = time.perf_counter()
    stance = await _run_conversational_director(
        message, graph_context, history, pref_nodes, session_type
    )
    timings["director_ms"] = _ms_since(t)
    t = time.perf_counter()
    text = await chat(
        build_conversational_renderer_messages(
            stance, message, history, pref_nodes, session_type
        ),
        model=APP_CONFIG.renderer_model_resolved,
        temperature=_CONVERSATIONAL_TEMP,
        max_tokens=APP_CONFIG.response_max_tokens,
        role="renderer",
    )
    timings["render_ms"] = _ms_since(t)
    return text, stance, timings


async def _run_analysis(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
) -> tuple[str, None, dict]:
    """Analysis mode (C3): a single Sonnet call in the analytic register — no renderer
    hand-off. Reuses the single-call fusion + the analytic
    capability layer (session_type='analytic')."""
    messages = build_response_messages(message, graph_context, history, pref_nodes, "analytic")
    t = time.perf_counter()
    text = await chat(
        messages,
        model=_response_model(),
        temperature=_SINGLE_TEMP,
        max_tokens=APP_CONFIG.response_max_tokens,
    )
    return text, None, {"generate_ms": _ms_since(t)}


async def generate_response(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
    render_mode: str = "cowrite",
) -> tuple[str, PieceBrief | ResponseStance | None, dict]:
    """
    Generate the reply, routed by render_mode (master spec C3):
      - "conversational": cheap ResponseStance director -> one renderer call (default
        for conversational non-generation turns). Returns (text, stance, timings).
      - "analysis": single Sonnet call in the analytic register. Returns (text, None, …).
      - "cowrite": the heavy paths — dual / split / single per the config flags. Returns
        (text, brief, timings).
    The "second" element ("brief") may be a PieceBrief, a SegmentedPlan, a
    ResponseStance, or None; the handler persists it and only locks piece_frame when it
    carries one. prev_brief / locked_piece_frame feed the piece director (Changes 1-2).

    timings (Change 5) is a per-stage latency map. The handler adds the guard timings.
    """
    if render_mode == "author":
        return await _run_author(message, graph_context, history, pref_nodes, session_type)
    if render_mode == "conversational":
        return await _run_conversational(message, graph_context, history, pref_nodes, session_type)
    if render_mode == "analysis":
        return await _run_analysis(message, graph_context, history, pref_nodes)
    # render_mode == "cowrite": the heavy apparatus, gated by the config flags.
    if _dual_on(session_type):
        return await _run_dual(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
    if _split_on(session_type):
        timings: dict[str, int] = {}
        t = time.perf_counter()
        brief = await _run_director(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
        timings["director_ms"] = _ms_since(t)
        t = time.perf_counter()
        text = await _render(brief, message, history, pref_nodes, session_type)
        timings["render_ms"] = _ms_since(t)
        return text, brief, timings

    messages = build_response_messages(
        message, graph_context, history, pref_nodes, session_type
    )
    t = time.perf_counter()
    text = await chat(
        messages,
        model=_response_model(),
        temperature=_SINGLE_TEMP,
        max_tokens=APP_CONFIG.response_max_tokens,
    )
    return text, None, {"generate_ms": _ms_since(t)}


async def generate_response_with_debug(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
    render_mode: str = "cowrite",
) -> tuple[str, PieceBrief | ResponseStance | None, dict, dict]:
    """Like generate_response, but also returns the labeled prompt breakdown. Routed by
    render_mode (C3); returns (text, brief|stance|None, breakdown, timings)."""
    if render_mode == "author":
        _, breakdown = build_author_director_messages_debug(
            message, graph_context, history, pref_nodes, session_type,
        )
        text, brief, timings = await _run_author(
            message, graph_context, history, pref_nodes, session_type
        )
        breakdown["brief"] = brief.model_dump(mode="json")
        breakdown["renderer_model"] = APP_CONFIG.renderer_model_resolved
        return text, brief, breakdown, timings
    if render_mode == "conversational":
        text, stance, timings = await _run_conversational(
            message, graph_context, history, pref_nodes, session_type
        )
        breakdown = {
            "stage": "conversational_director",
            "stance": stance.model_dump(mode="json") if stance else None,
            "director_model": APP_CONFIG.director_model_resolved,
            "renderer_model": APP_CONFIG.renderer_model_resolved,
        }
        return text, stance, breakdown, timings
    if render_mode == "analysis":
        text, _, timings = await _run_analysis(message, graph_context, history, pref_nodes)
        breakdown = {"stage": "analysis", "model": _response_model()}
        return text, None, breakdown, timings
    if _dual_on(session_type):
        text, plan, timings = await _run_dual(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
        breakdown = {
            "stage": "dual_director",
            "plan": plan.model_dump(mode="json") if plan else None,
            "segment_role_model": APP_CONFIG.segment_role_model,
            "director_model": APP_CONFIG.director_model_resolved,
        }
        return text, plan, breakdown, timings
    if _split_on(session_type):
        _, breakdown = build_director_messages_debug(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief=prev_brief, locked_piece_frame=locked_piece_frame,
        )
        timings: dict[str, int] = {}
        t = time.perf_counter()
        brief = await _run_director(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
        timings["director_ms"] = _ms_since(t)
        t = time.perf_counter()
        text = await _render(brief, message, history, pref_nodes, session_type)
        timings["render_ms"] = _ms_since(t)
        breakdown["brief"] = brief.model_dump(mode="json")
        breakdown["renderer_model"] = APP_CONFIG.renderer_model_resolved
        return text, brief, breakdown, timings

    messages, breakdown = build_response_messages_debug(
        message, graph_context, history, pref_nodes, session_type
    )
    t = time.perf_counter()
    text = await chat(
        messages,
        model=_response_model(),
        temperature=_SINGLE_TEMP,
        max_tokens=APP_CONFIG.response_max_tokens,
    )
    return text, None, breakdown, {"generate_ms": _ms_since(t)}


async def _single_stream(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str,
) -> AsyncIterator[str]:
    messages = build_response_messages(
        message, graph_context, history, pref_nodes, session_type
    )
    async for chunk in chat_stream(
        messages,
        model=_response_model(),
        temperature=_SINGLE_TEMP,
        max_tokens=APP_CONFIG.response_max_tokens,
    ):
        yield chunk


async def _chunk_text(text: str, size: int = 48) -> AsyncIterator[str]:
    """Yield a finished string in chunk-sized pieces, so the split path still
    satisfies the SSE token contract after the renderer was buffered for the
    anti-loop check."""
    for i in range(0, len(text), size):
        yield text[i : i + size]


async def open_response_stream(
    message: str,
    graph_context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
    render_mode: str = "cowrite",
) -> tuple[PieceBrief | ResponseStance | None, AsyncIterator[str], dict]:
    """
    Split-aware streaming entry, routed by render_mode (C3). Returns (brief|stance|None,
    token_iterator, timings).

    Conversational: cheap director + one renderer, buffered then chunked (stance is the
    "brief"). Analysis: single Sonnet (analytic) streamed progressively. Piece: the
    existing dual/split/single behaviour below.

    On the split path the director runs first (so the brief is ready before any
    token) AND the renderer is generated in FULL — the post-generation anti-loop
    check + possible regeneration (in _render) needs the whole draft, which can't be
    done mid-stream — then the final text is chunked to satisfy the SSE contract.
    Because both stages have already run by the time we return, timings carries
    {director_ms, render_ms} here (Change 5).

    True progressive streaming is kept on the single-model path, where there is no
    brief to honor and nothing to re-check. There the tokens are produced lazily as
    the caller consumes them, so generate_ms is not knowable at open time — timings
    is empty and the handler times the token loop and records generate_ms itself.
    """
    if render_mode == "author":
        # One-shot author render is one large generation (no post-gen anti-loop), so
        # like the split it is buffered then chunked to satisfy the SSE contract.
        text, brief, timings = await _run_author(
            message, graph_context, history, pref_nodes, session_type
        )
        return brief, _chunk_text(text), timings
    if render_mode == "conversational":
        text, stance, timings = await _run_conversational(
            message, graph_context, history, pref_nodes, session_type
        )
        return stance, _chunk_text(text), timings
    if render_mode == "analysis":
        # Single Sonnet in the analytic register — stream progressively like single.
        return None, _single_stream(
            message, graph_context, history, pref_nodes, "analytic"
        ), {}
    if _dual_on(session_type):
        # Dual render is fully buffered (segments gathered + assembled) before any
        # token, like the split — then chunked to satisfy the SSE contract.
        text, plan, timings = await _run_dual(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
        return plan, _chunk_text(text), timings
    if _split_on(session_type):
        timings: dict[str, int] = {}
        t = time.perf_counter()
        brief = await _run_director(
            message, graph_context, history, pref_nodes, session_type,
            prev_brief, locked_piece_frame,
        )
        timings["director_ms"] = _ms_since(t)
        t = time.perf_counter()
        text = await _render(brief, message, history, pref_nodes, session_type)
        timings["render_ms"] = _ms_since(t)
        return brief, _chunk_text(text), timings
    return None, _single_stream(message, graph_context, history, pref_nodes, session_type), {}
