"""
Reaction-chip generation for the single-stream cowriter.

The product is reaction-over-composition: the engine authors, the user mostly
reacts via three chips (advance / regenerate / wildcard). The chips' quality
carries the whole "guided" feel, so this is first-class engine, not garnish —
generic chips ("continue the piece") are worse than none.

The wildcard is where the graph flexes (design §4.4): it is PREDICTION-ENGINE-
DRIVEN — built around a stored candidate from the function-generalization engine
(same need, different surface) or, failing that, the similarity engine — which is
what makes it land uncannily rather than randomly. The offered element is
recorded as an element_offer, so the user's next move (tapping the chip, typing
past it) judges it through the same uptake loop as steering probes: the chip IS
a probe, just a visible one. Gated nodes are never offered. Falls back to the
concept-flavored LLM wildcard when no candidate is waiting.
"""

import json
import logging
from uuid import UUID, uuid4

from config.loader import APP_CONFIG
from llm.client import chat
from schemas.message import Chip

logger = logging.getLogger(__name__)

_CHIP_SYSTEM = (
    "You generate exactly three reaction chips for a collaborative writing app "
    "where the engine writes and the user mostly reacts. Given the current beat "
    "and what is known about this specific user (their recurring concepts), "
    "produce three chips:\n"
    "1. kind 'advance' — accept and move to the next phase.\n"
    "2. kind 'regenerate' — redo THIS beat differently (do not advance); e.g. "
    "expand the argument, shift to a concrete example, change pacing.\n"
    "3. kind 'wildcard' — a less-obvious tonal/focus shift the user might not "
    "think of, informed by their specific concepts. This is the interesting one.\n"
    "Each chip: a short user-facing `label` (2-6 words) and a longer hidden "
    "`instruction` (the steering text sent when tapped). Be specific to the beat "
    "and the user — never generic. Return JSON only: "
    '{"chips": [{"kind": str, "label": str, "instruction": str}, ...]}.'
)

_FALLBACK_CHIPS = [
    Chip(kind="advance", label="Keep going", instruction="Continue to the next beat."),
    Chip(kind="regenerate", label="Try that again", instruction="Rewrite the last beat differently."),
    Chip(kind="wildcard", label="Shift the focus", instruction="Take the piece somewhere unexpected."),
]

# Composer chips (product reshape §3.4 / P2.5): the blank/new-piece state only — the
# blank-page fix. Static (no graph call): openers, not reactions to a beat.
_COMPOSER_CHIPS = [
    Chip(kind="composer", label="Start a piece",
         instruction="Start a new piece for me."),
    Chip(kind="composer", label="Pick up where we left off",
         instruction="Continue from where we last left off."),
    Chip(kind="composer", label="Surprise me",
         instruction="Surprise me — start something you think I'll like."),
]


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


async def _wildcard_probe(user_id: UUID) -> dict | None:
    """
    The prediction engines' pick for this user's wildcard: the first unoffered,
    ungated candidate — function-generalization first (§5.1 primary), then
    similarity (§5.2). Returns {element, tag, node_id, interpretation_id} or
    None when nothing is waiting (fresh graph, all candidates spent).
    """
    from services import gates, graph_service, uptake

    try:
        gated = await gates.get_active_gate_node_ids(user_id)
    except Exception:
        gated = set()
    try:
        for p in await graph_service.get_function_probe_candidates(user_id):
            node_ids = list(p.get("node_ids") or [])
            if any(n in gated for n in node_ids):
                continue
            cands = list(p.get("candidates") or [])
            offered = await uptake.get_offered_elements(user_id, cands)
            for c in cands:
                if c not in offered:
                    return {
                        "element": c,
                        "tag": f"wildcard:function:{p['id']}",
                        "node_id": node_ids[0] if node_ids else None,
                        "interpretation_id": p["id"],
                    }
        for s in await graph_service.get_similarity_probe_nodes(user_id):
            if s["id"] in gated:
                continue
            cands = list(s.get("candidates") or [])
            offered = await uptake.get_offered_elements(user_id, cands)
            for c in cands:
                if c not in offered:
                    return {
                        "element": c,
                        "tag": f"wildcard:similar:{s['id']}",
                        "node_id": s["id"],
                        "interpretation_id": None,
                    }
    except Exception:
        logger.warning("wildcard probe selection failed; falling back to concepts")
    return None


async def generate_chips(
    beat: str,
    user_id: UUID,
    session_number: int,
    conversation_id: UUID | None = None,
) -> list[Chip]:
    """
    Produce three graph-informed reaction chips for the current beat. The
    wildcard builds around a prediction-engine candidate when one is waiting
    (recorded as an offer so the uptake loop judges it); otherwise it falls back
    to concept flavoring. Degrades to sensible generic chips on any failure so
    the UI always has something to render.

    Blank/new-story state (empty beat, P2.5): serve the static composer chips —
    the blank-page fix — instead of reaction chips (there is nothing to react to).
    """
    if not beat or not beat.strip():
        return list(_COMPOSER_CHIPS)

    probe = await _wildcard_probe(user_id)

    # Personalize from the user's graph — relevant concepts flavor every chip.
    concept_hint = ""
    try:
        from services import graph_service

        ctx = await graph_service.build_graph_context(beat, user_id, session_number)
        names = [n.name for n in ctx.relevant_nodes[:8]]
        if names:
            concept_hint = "\n\nConcepts this user keeps returning to: " + ", ".join(names)
    except Exception:
        logger.warning("chip graph context unavailable; proceeding without")

    probe_hint = ""
    if probe:
        probe_hint = (
            f"\n\nFor the WILDCARD chip specifically: build it around weaving "
            f"\"{probe['element']}\" into the piece — the engine predicts this "
            f"adjacent element will land for this user. Keep the label inviting "
            f"and concrete; the instruction steers the next beat to incorporate "
            f"it naturally, never as an announcement."
        )

    chips: list[Chip] | None = None
    try:
        raw = await chat(
            messages=[
                {"role": "system", "content": _CHIP_SYSTEM},
                {"role": "user", "content": f"Current beat:\n{beat}{concept_hint}{probe_hint}"},
            ],
            model=APP_CONFIG.utility_model_resolved,
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        data = json.loads(_strip_fence(raw))
        items = data.get("chips", []) if isinstance(data, dict) else []
        parsed = [
            Chip(
                kind=str(i.get("kind", "wildcard")),
                label=str(i.get("label", "")).strip(),
                instruction=str(i.get("instruction", "")).strip(),
            )
            for i in items
            if i.get("label") and i.get("instruction")
        ]
        if len(parsed) >= 3:
            chips = parsed[:3]
    except Exception:
        logger.warning("chip generation failed; using fallback chips")

    if chips is None:
        chips = list(_FALLBACK_CHIPS)
        if probe:
            # Even without the LLM, the engine's pick is a better wildcard than
            # a generic shift — the candidate is the value, the prose is garnish.
            chips[2] = Chip(
                kind="wildcard",
                label="Try something adjacent",
                instruction=(
                    f"Weave \"{probe['element']}\" into the next beat, naturally "
                    f"and without announcing it."
                ),
            )

    # The wildcard IS a probe — record the offer so the user's next move
    # (tapping it, or typing past it) closes the §5.1 reaction loop.
    if probe and conversation_id is not None:
        try:
            from services import uptake

            await uptake.record_offer(
                user_id, conversation_id, uuid4(),
                probe["element"], probe["tag"],
                node_id=probe.get("node_id"),
                interpretation_id=probe.get("interpretation_id"),
            )
        except Exception:
            logger.warning("wildcard offer recording failed", extra={"tag": probe["tag"]})

    return chips
