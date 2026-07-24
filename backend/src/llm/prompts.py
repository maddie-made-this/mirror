import json

from config.loader import APP_CONFIG
from core import request_context
from config.personas import get_active_persona
from llm.layers import (
    capability_rules,
    core_identity,
    dynamics,
    format_rules,
    function_insight,
    graph_context,
    recent_messages,
    safety_rules,
    steering,
    user_preferences,
)
from schemas.graph import GraphContext, GraphNode
from schemas.message import ConversationTurn
from schemas.response_stance import ResponseStance
from schemas.piece_brief import PlanSegment, PieceBrief, SegmentedPlan


def build_extraction_messages(
    user_message: str,
    active_nodes: list[GraphNode],
    active_predicates: list[str],
) -> list[dict[str, str]]:
    """
    Compose the extraction request: system prompt, few-shot demonstrations, and
    a final user turn carrying the active-node / active-predicate hints alongside
    the message itself so the LLM treats them as live context.
    """
    system = APP_CONFIG.extraction_system_prompt.format(
        entity_types=", ".join(APP_CONFIG.entity_types)
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for ex in APP_CONFIG.extraction_examples:
        messages.append({"role": "user", "content": ex.user_message})
        messages.append({"role": "assistant", "content": ex.expected_json})

    parts: list[str] = []
    if active_nodes:
        listing = "\n".join(
            f"- {n.name} ({n.entity_type})" for n in active_nodes[:15]
        )
        parts.append(f"{APP_CONFIG.extraction_active_nodes_hint}\n{listing}")
    if active_predicates:
        parts.append(
            f"{APP_CONFIG.extraction_active_predicates_hint}\n"
            + "\n".join(f"- {p}" for p in active_predicates[:15])
        )
    parts.append(f"Message:\n{user_message}")

    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


def build_reflection_messages(
    user_message: str,
    pass1_propositions: list[dict],
    active_nodes: list[GraphNode] | None = None,
) -> list[dict[str, str]]:
    """
    Compose the Pass 2 reflection request. Receives the original message, Pass 1
    output, and the active nodes so it can focus on the implied layer instead of
    restating — and so its GROUNDED-inference rule has concrete existing concepts
    to reference (extraction redesign §8). Returns [] when reflection is disabled.
    """
    if not APP_CONFIG.reflection_system_prompt:
        return []

    system = APP_CONFIG.reflection_system_prompt.format(
        entity_types=", ".join(APP_CONFIG.entity_types)
    )
    parts = [
        f"Original message:\n{user_message}",
        f"Pass 1 propositions already extracted:\n{json.dumps(pass1_propositions, indent=2)}",
    ]
    if active_nodes:
        node_list = "\n".join(f"- {n.name}" for n in active_nodes[:25])
        parts.append(
            "Existing nodes you may ground inferences in (reference these by name; "
            "do NOT invent vague placeholders):\n" + node_list
        )
    parts.append("Now extract the implied layer (Pass 2).")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _response_layers(
    context: GraphContext,
    pref_nodes: list[GraphNode],
    session_type: str,
) -> dict[str, str | None]:
    """
    The ordered layer stack shared by the single-model generator and the director
    (the director inherits the same understanding, then gets an output-contract
    envelope appended). Insertion order is the system-prompt priority order.
    Returned as a dict so the debug inspector can label each layer; callers that
    only need the text iterate .values().
    """
    return {
        "core_identity": core_identity.render(),
        "safety_rules": safety_rules.render(),
        "capability_rules": capability_rules.render(session_type),
        "format_rules": format_rules.render(pref_nodes),
        "graph_context": graph_context.render(context),
        "function_insight": function_insight.render(context),  # flow 2: idiographic
        "steering": steering.render(context),                  # flow 3/4 + B6 gate
        "dynamics": dynamics.render(context),                  # §4 ramp/gate/frame
        "user_preferences": user_preferences.render(pref_nodes),
    }


def build_response_messages(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """
    Compose the full messages list from layered prompt components (C1).
    Each layer is independently enabled/disabled by AppConfig flags.
    Layer order determines priority in the system prompt. session_type selects the
    register (analytic branch swaps the capability layer — B10).
    """
    layers = _response_layers(context, pref_nodes, session_type)
    system_content = "\n\n".join(s for s in layers.values() if s)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

    # History goes into the messages array, not the system prompt.
    history_messages = recent_messages.render(history) or []
    messages.extend(history_messages)

    messages.append({"role": "user", "content": user_message})
    return messages


def build_response_messages_debug(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> tuple[list[dict[str, str]], dict]:
    """
    Same as build_response_messages, but also returns a labeled breakdown of
    every layer for the dev-panel context inspector.
    """
    layers = _response_layers(context, pref_nodes, session_type)
    system_content = "\n\n".join(s for s in layers.values() if s)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    history_messages = recent_messages.render(history) or []
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    breakdown = {
        "system_layers": dict(layers),  # None where the layer is disabled
        "history_messages": history_messages,
        "user_message": user_message,
        # the per-request override when the user picked one (see request_context)
        "model": request_context.get_response_model() or APP_CONFIG.response_model_resolved,
        "temperature": 0.7,
    }
    return messages, breakdown


# --------------------------------------------------------------------------- #
# Director / renderer split (Part B)
# --------------------------------------------------------------------------- #

def _director_dynamic_block(
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> str | None:
    """
    Per-turn dynamic state injected into the director prompt AFTER the envelope:
      - the PRIOR ARC to carry forward (Change 1) — arc_position + beat_history from
        the last brief, so the piece builds instead of resetting each turn;
      - the LOCKED piece-frame invariants (Change 2) — the fixed subject/POV/subjects/
        setting the director must NOT recompute or contradict.
    Returns None when there's no prior state (e.g. turn one).
    """
    lines: list[str] = []

    if prev_brief:
        arc = prev_brief.get("arc_position")
        synopsis = (prev_brief.get("arc_synopsis") or "").strip()
        beats = prev_brief.get("beat_history") or []
        if arc or synopsis or beats:
            lines.append("[PRIOR ARC — carry forward and ADVANCE, do not restart]")
            if arc:
                lines.append(f"  arc_position so far: {arc}")
            if synopsis:
                lines.append(f"  arc so far (REVISE this, do not regrow it): {synopsis}")
            if beats:
                # Bounded memory (Change 1): only the tail re-enters the prompt, for
                # local anti-repetition — NOT the whole growing list.
                shown = "; ".join(str(b) for b in beats[-5:])
                lines.append(f"  recent beats (local anti-repetition only): {shown}")
            lines.append(
                "  -> REVISE arc_synopsis to fold in this turn (one-two sentences; do NOT "
                "rebuild it from the beat list). Emit next_beat = one short clause for THIS "
                "turn only. Do NOT reproduce or re-emit the beat list — the system appends "
                "it. Set arc_position."
            )

    if locked_piece_frame:
        bits = [
            f"{label}: {str(val).strip()}"
            for label, val in (
                ("subject/POV", locked_piece_frame.get("subject_pov")),
                ("other subjects", locked_piece_frame.get("subjects")),
                ("setting", locked_piece_frame.get("setting")),
            )
            if str(val or "").strip()
        ]
        if bits:
            if lines:
                lines.append("")
            lines.append(
                "[LOCKED PIECE FRAME — FIXED INVARIANTS, established earlier in this "
                "piece. Echo them UNCHANGED in piece_frame. Contradicting the frame the "
                "user set is the HIGHEST-PRIORITY error, above every stylistic concern. "
                "Do NOT re-guess or drift them.]"
            )
            lines.extend(f"  {b}" for b in bits)
            lines.append(
                "  -> Update these ONLY if the USER explicitly re-frames the piece this "
                "turn (\"make it an essay this time\"); otherwise keep them exactly."
            )

    return "\n".join(lines) if lines else None


def build_director_messages(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> list[dict[str, str]]:
    """
    The DIRECTOR prompt: the full understanding stack (same layers the single-model
    generator sees) plus the output-contract envelope appended LAST, so the model's
    final instruction is "decide the move and emit a PieceBrief" rather than "write
    the reply." The interested-reader role lives in the inherited capability layer.

    prev_brief / locked_piece_frame inject the per-turn dynamic state (prior arc to
    advance; locked piece-frame invariants) after the envelope — see
    _director_dynamic_block (Changes 1 & 2).
    """
    layers = _response_layers(context, pref_nodes, session_type)
    sections = [s for s in layers.values() if s]
    if APP_CONFIG.director_envelope_text:
        sections.append(APP_CONFIG.director_envelope_text)  # output contract, last
    dyn = _director_dynamic_block(prev_brief, locked_piece_frame)
    if dyn:
        sections.append(dyn)
    system_content = "\n\n".join(sections)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


def build_director_messages_debug(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> tuple[list[dict[str, str]], dict]:
    """build_director_messages + a labeled breakdown for the inspector."""
    layers = _response_layers(context, pref_nodes, session_type)
    layers["director_envelope"] = APP_CONFIG.director_envelope_text or None
    layers["director_dynamic_state"] = _director_dynamic_block(prev_brief, locked_piece_frame)
    system_content = "\n\n".join(s for s in layers.values() if s)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    history_messages = recent_messages.render(history) or []
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})

    breakdown = {
        "system_layers": dict(layers),
        "history_messages": history_messages,
        "user_message": user_message,
        "model": APP_CONFIG.director_model_resolved,
        "temperature": 0.4,
        "stage": "director",
    }
    return messages, breakdown


def build_author_director_messages(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """AUTHOR-MODE director prompt (Option A): the understanding stack + the one-shot
    author envelope appended last. No _director_dynamic_block — there is no prior turn
    and the author decides piece_frame itself, planning the whole piece from scratch in
    a single full-arc brief, deciding every unspecified gap."""
    layers = _response_layers(context, pref_nodes, session_type)
    sections = [s for s in layers.values() if s]
    if APP_CONFIG.author_director_envelope_text:
        sections.append(APP_CONFIG.author_director_envelope_text)  # output contract, last
    system_content = "\n\n".join(sections)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


def build_author_director_messages_debug(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> tuple[list[dict[str, str]], dict]:
    """build_author_director_messages + a labeled breakdown for the inspector."""
    layers = _response_layers(context, pref_nodes, session_type)
    layers["author_director_envelope"] = APP_CONFIG.author_director_envelope_text or None
    system_content = "\n\n".join(s for s in layers.values() if s)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    history_messages = recent_messages.render(history) or []
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_message})
    breakdown = {
        "system_layers": dict(layers),
        "history_messages": history_messages,
        "user_message": user_message,
        "model": APP_CONFIG.director_model_resolved,
        "temperature": 0.4,
        "stage": "author_director",
    }
    return messages, breakdown


def _render_brief_block(brief: PieceBrief) -> str:
    """
    Render a PieceBrief into the renderer's directive block, with a hard wall
    (Change 3) between STAGING (directions to ACT on, never speak) and CONTENT (what
    actually goes into the piece). The question is handed as an instruction to
    EXPRESS in-voice, never a line to paste; next_beat/arc are staging, not prose.
    """
    staging: list[str] = []
    content: list[str] = []

    # ---- STAGING — act on these; they are NOTES, never words in the reply ----
    if brief.next_beat.strip():
        staging.append(f"THE MOVE this beat makes: {brief.next_beat.strip()}")
    if brief.arc_position:
        staging.append(f"ARC: the piece is at '{brief.arc_position}' — write to that stage")

    if brief.action in ("ask", "ask_then_write") and (brief.question or "").strip():
        tail = (
            "and let it lead the beat"
            if brief.action == "ask"
            else "then move into the piece"
        )
        staging.append(
            "EXPRESS as natural in-character dialogue (your OWN words, never this "
            f"literal text) {tail} — the character wants to know: {brief.question.strip()}"
        )

    if brief.advance_directive.strip():
        staging.append(f"MUST ADVANCE (vs. the last beat): {brief.advance_directive.strip()}")

    dnr = [x.strip() for x in brief.do_not_repeat if x.strip()]
    if dnr:
        staging.append(
            "FORBIDDEN — already used; do NOT repeat or merely rephrase, write something "
            "genuinely new instead: " + "; ".join(dnr)
        )

    prereq = [x.strip() for x in brief.prerequisites_to_establish if x.strip()]
    if prereq:
        staging.append(
            "STILL UNKNOWN (don't invent these — leave open or let the character find out): "
            + "; ".join(prereq)
        )

    if brief.function_to_serve.strip():
        staging.append(
            "INTEREST TO SERVE (render as experience on the page, NEVER name or state it): "
            + brief.function_to_serve.strip()
        )

    if brief.pacing:
        staging.append(f"PACING: {brief.pacing}")
    if brief.interest_anchor.strip():
        staging.append(f"KEEP CENTRAL (embody it, don't say it): {brief.interest_anchor.strip()}")

    avoid = [x.strip() for x in brief.hard_avoid if x.strip()]
    if avoid:
        staging.append("NEVER INCLUDE: " + "; ".join(avoid))

    # ---- CONTENT — render this into the piece ----
    ss = brief.piece_frame
    state_bits = [
        f"{label}: {val.strip()}"
        for label, val in (
            ("subject/POV", ss.subject_pov),
            ("other subjects", ss.subjects),
            ("setting", ss.context),
            ("beat", ss.current_section),
        )
        if val.strip()
    ]
    if state_bits:
        content.append("PIECE FRAME — show as concrete detail, never recite: " + "; ".join(state_bits))

    reg = brief.delivery
    reg_bits = [
        f"{label}={val.strip()}"
        for label, val in (
            ("vividness", reg.vividness),
            ("density", reg.prose_density),
            ("voice", reg.person_tense),
            ("emphasis", reg.emphasis),
        )
        if val.strip()
    ]
    if reg_bits:
        content.append("REGISTER: " + ", ".join(reg_bits))

    lines: list[str] = ["[PIECE BRIEF — render the next beat from this]"]
    if staging:
        lines.append("STAGING (act on these; NOTES to you, never words you write):")
        lines.extend(f"  - {s}" for s in staging)
    if content:
        lines.append("CONTENT (what actually goes into the piece):")
        lines.extend(f"  - {c}" for c in content)
    return "\n".join(lines)


def build_renderer_messages(
    brief: PieceBrief,
    user_message: str,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """
    The RENDERER prompt (thin): the voice instruction + delivery-format rules + the
    brief as a directive block. History gives prose continuity; the user's latest
    message is the turn being answered. No reasoning layers — the director already
    did that thinking, and keeping the renderer lean is what makes the prose
    model render cleanly without re-introducing unnecessary deliberation.
    """
    sections = [
        APP_CONFIG.renderer_system_text or None,
        format_rules.render(pref_nodes),  # B14 delivery-format continuum (the voice's job)
        _render_brief_block(brief),
    ]
    system_content = "\n\n".join(s for s in sections if s)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


def build_author_renderer_messages(
    brief: PieceBrief,
    user_message: str,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """AUTHOR-MODE renderer: write the COMPLETE piece from a single full-arc brief.
    Mirrors build_renderer_messages' assembly (system text + format rules + brief block
    + history); differs in (a) the author voice, (b) an explicit one-shot render-each-
    beat-in-full instruction, and (c) an enumerated beat skeleton from brief.piece_beats
    — what the renderer expands into full prose."""
    base_system = APP_CONFIG.author_renderer_system_text or APP_CONFIG.renderer_system_text
    one_shot = (
        "WRITE THE COMPLETE PIECE NOW, start to finish — a full arc (setup, "
        "development, complication, the claim, close) in ONE continuous run. This is a "
        "finished piece, NOT an opening beat: do not stop early, do not end on a "
        "question, do not write 'to be continued'.\n\n"
        "RENDER EACH BEAT BELOW IN FULL — write the moment, do NOT summarize it. Where "
        "a beat calls for it, use concrete detail, example, or dialogue; SHOW the "
        "reasoning as it happens rather than reporting that it happened. 'It leads to a "
        "surprising conclusion' is a FAILURE — write the conclusion and the step that "
        "reaches it. 'The two ideas connect' is a FAILURE — render the connection on "
        "the page. Interiority and argument are welcome; summary is not.\n\n"
        "Target the length of a full short essay (~1200–2000 words). N fully-rendered "
        "beats IS a full piece — that is how the length is earned, not by padding. Lean "
        "and concrete beats ornate — no purple, no throat-clearing, no essayistic "
        "hedging — and HOLD that voice across the whole length."
    )
    beats = [b.strip() for b in (brief.piece_beats or []) if b.strip()]
    beat_block = ""
    if beats:
        bullets = "\n".join(f"  - {b}" for b in beats)
        beat_block = (
            "[INTERNAL BEAT SKELETON — these are NOTES TO YOU, never printed. Expand each "
            "into a full rendered moment; write them in order as ONE continuous piece "
            "with NO numbers, NO headers, NO labels in your output.]\n"
            f"{bullets}\n"
            "Together they ARE the piece end-to-end."
        )
    sections = [
        base_system,
        one_shot,
        format_rules.render(pref_nodes),  # B14 delivery-format continuum (same as the turn path)
        _render_brief_block(brief),
        beat_block,
    ]
    system_content = "\n\n".join(s for s in sections if s)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


# --------------------------------------------------------------------------- #
# Dual-model render (Change 6)
# --------------------------------------------------------------------------- #

def build_dual_director_messages(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
    prev_brief: dict | None = None,
    locked_piece_frame: dict | None = None,
) -> list[dict[str, str]]:
    """The DUAL-MODEL director prompt: same understanding stack + dynamic state as the
    split director, but the dual envelope (emit a SegmentedPlan) appended last."""
    layers = _response_layers(context, pref_nodes, session_type)
    sections = [s for s in layers.values() if s]
    if APP_CONFIG.dual_director_envelope_text:
        sections.append(APP_CONFIG.dual_director_envelope_text)
    dyn = _director_dynamic_block(prev_brief, locked_piece_frame)
    if dyn:
        sections.append(dyn)
    system_content = "\n\n".join(sections)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


def _render_segment_block(segment: PlanSegment, plan: SegmentedPlan) -> str:
    """One segment's directive block for its renderer. Carries the shared smoothing
    (tone, locked piece_frame, global do_not_repeat, register) so independently-
    rendered segments cohere; the staging wall (Change 3) still applies."""
    lines: list[str] = [
        "[ONE SEGMENT of the reply — render ONLY this piece. Other writers render the "
        "other segments and your outputs are concatenated IN ORDER. Do NOT restate the "
        "setup, recap, or wrap up the whole beat — write only your segment so it joins "
        "seamlessly.]"
    ]
    if plan.tone.strip():
        lines.append(f"TONE (match exactly, for cohesion across segments): {plan.tone.strip()}")
    lines.append(
        f"THIS SEGMENT'S JOB [{segment.role}] — act on it, never quote it: "
        f"{segment.directive.strip()}"
    )

    ss = plan.piece_frame
    state_bits = [
        f"{label}: {val.strip()}"
        for label, val in (
            ("subject/POV", ss.subject_pov),
            ("other subjects", ss.subjects),
            ("setting", ss.context),
        )
        if val.strip()
    ]
    if state_bits:
        lines.append("PIECE FRAME — show as concrete detail, never recite: " + "; ".join(state_bits))

    reg = plan.delivery
    reg_bits = [
        f"{label}={val.strip()}"
        for label, val in (
            ("vividness", reg.vividness),
            ("density", reg.prose_density),
            ("voice", reg.person_tense),
            ("emphasis", reg.emphasis),
        )
        if val.strip()
    ]
    if reg_bits:
        lines.append("REGISTER: " + ", ".join(reg_bits))

    dnr = [x.strip() for x in plan.do_not_repeat if x.strip()]
    if dnr:
        lines.append("FORBIDDEN — do not repeat or rephrase: " + "; ".join(dnr))
    if plan.interest_anchor.strip():
        lines.append(f"KEEP CENTRAL (embody, don't say): {plan.interest_anchor.strip()}")
    avoid = [x.strip() for x in plan.hard_avoid if x.strip()]
    if avoid:
        lines.append("NEVER INCLUDE: " + "; ".join(avoid))
    return "\n".join(lines)


def build_segment_renderer_messages(
    segment: PlanSegment,
    plan: SegmentedPlan,
    user_message: str,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """Renderer prompt for ONE segment of a dual-model reply. Same voice + staging
    wall as the single renderer, scoped to this segment's directive + shared smoothing.
    History gives continuity; the segment does NOT see sibling segments' prose."""
    sections = [
        APP_CONFIG.renderer_system_text or None,
        format_rules.render(pref_nodes),
        _render_segment_block(segment, plan),
    ]
    system_content = "\n\n".join(s for s in sections if s)

    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


# --------------------------------------------------------------------------- #
# Conversational mode (master spec C3)
# --------------------------------------------------------------------------- #

def build_conversational_director_messages(
    user_message: str,
    context: GraphContext,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """The CONVERSATIONAL director prompt: the full understanding stack (so reads land
    grounded + in-voice) + the conversational envelope appended last — emit a tiny
    ResponseStance, not a PieceBrief. No piece-frame / arc apparatus."""
    layers = _response_layers(context, pref_nodes, session_type)
    sections = [s for s in layers.values() if s]
    if APP_CONFIG.conversational_director_envelope_text:
        sections.append(APP_CONFIG.conversational_director_envelope_text)
    system_content = "\n\n".join(sections)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages


def _render_stance_block(stance: ResponseStance) -> str:
    """A ResponseStance as a directive block for the conversational renderer. Staging
    wall applies: act on these notes, never quote them."""
    lines = ["[RESPONSE STANCE — write ONE in-voice reply from this; act on these "
             "notes, never quote them]"]
    if stance.engagement_target.strip():
        lines.append(f"REACT TO: {stance.engagement_target.strip()}")
    if stance.move == "land_read" and stance.read.strip():
        lines.append("LAND THIS READ — say what you're seeing, plainly and in voice, as "
                     "something that opens up the thinking. It's about the IDEA and "
                     "where it goes, never flattery of the user. Lead toward the live "
                     "thread; don't diagnose, don't lecture; do NOT end on a reflective "
                     f"note: {stance.read.strip()}")
    elif stance.move == "ask_targeted" and stance.question.strip():
        lines.append("ASK THIS, in voice (a genuine question, never a request for "
                     f"agreement): {stance.question.strip()}")
    else:
        lines.append("ENGAGE: respond in voice — react, push back, move the thread forward.")
    if stance.register_notes.strip():
        lines.append(f"REGISTER: {stance.register_notes.strip()}")
    avoid = [a.strip() for a in stance.avoid if a.strip()]
    if avoid:
        lines.append("AVOID: " + "; ".join(avoid))
    lines.append(
        "USER KNOWLEDGE: " + stance.user_knowledge_level
        + (" — assert lightly, earn depth" if stance.user_knowledge_level == "early"
           else " — lean on what you already know about them")
    )
    return "\n".join(lines)


def build_conversational_renderer_messages(
    stance: ResponseStance,
    user_message: str,
    history: list[ConversationTurn],
    pref_nodes: list[GraphNode],
    session_type: str = "primary",
) -> list[dict[str, str]]:
    """The CONVERSATIONAL renderer (the voice): the active persona's voice + staging
    wall, a note that this is a conversation (a natural chat-length reply, NOT a
    generated piece), and the stance. History gives continuity; the latest message is
    answered.

    The register is the ACTIVE PERSONA's (config/personas.py) when the identity layer is
    on; otherwise it falls back to a neutral short-reply note."""
    if APP_CONFIG.use_identity_layer:
        persona = get_active_persona()
        conv_note = (
            f"CONVERSATIONAL MODE: write a natural, in-voice reply as {persona.name} — "
            f"short (usually one or two sentences), NOT a generated piece, NOT narrated "
            f"action. One reply in your own voice.\n\n"
            f"{persona.conversational_register}\n\n"
            "Your voice sounds like this (match the cadence — short, pointed, never a "
            "paragraph):\n"
            + "\n".join(f'  "{t}"' for t in persona.example_turns)
        )
    else:
        conv_note = (
            "CONVERSATIONAL MODE: write a natural, in-voice reply — short (usually one "
            "or two sentences), NOT a generated piece and not narrated action. One reply."
        )
    sections = [
        APP_CONFIG.renderer_system_text or None,
        conv_note,
        format_rules.render(pref_nodes),
        _render_stance_block(stance),
    ]
    system_content = "\n\n".join(s for s in sections if s)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    messages.extend(recent_messages.render(history) or [])
    messages.append({"role": "user", "content": user_message})
    return messages
