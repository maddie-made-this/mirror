"""'Mirror's thinking' click-through (product reshape §3.6 / P2.4).

Assembles the REAL artifacts that produced a turn — the graph nodes + interpretations that
fed it, the steering objective, a curated slice of the director's piece brief, and the
elements it deliberately offered. These already exist on the turn (+ element_offers), so
the view costs nothing and can never be theater: what the user reads IS what the system
used. An OPTIONAL narrativized 'the system's read' summary sits on top — one cheap-model call,
generated lazily on first open and cached in conversation_turns.thinking_summary, gated by
APP_CONFIG.enable_thinking_summary (off until the per-message CoT cost is measured).
"""
import json
import logging
from uuid import UUID

from config.loader import APP_CONFIG
from db.postgres import get_pool
from services import graph_service, uptake

logger = logging.getLogger(__name__)

# The director-brief fields worth surfacing as "its thinking" — the actual reasoning, not
# the internal scaffolding (beat_history/piece_beats logs) or raw prose.
_BRIEF_FIELDS = (
    "function_to_serve", "next_beat", "advance_directive",
    "arc_position", "arc_synopsis", "interest_anchor", "delivery", "piece_frame",
)


def _jsonb(v) -> dict:
    """asyncpg may hand back jsonb as a str or a dict — normalise to dict."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


def _brief_slice(piece_brief: dict) -> dict | None:
    if not piece_brief:
        return None
    slice_ = {k: piece_brief[k] for k in _BRIEF_FIELDS if piece_brief.get(k)}
    return slice_ or None


async def get_thinking(user_id: UUID, turn_id: UUID) -> dict | None:
    """Assemble the thinking view for a turn, or None if the turn isn't owned by the user.
    Generates + caches the narrativized summary only when the flag is on and none exists."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        turn = await conn.fetchrow(
            """
            SELECT input_node_ids, input_interpretation_ids, steering_objective,
                   piece_brief, thinking_summary
            FROM conversation_turns
            WHERE user_id = $1 AND message_id = $2
            """,
            str(user_id),
            str(turn_id),
        )
    if turn is None:
        return None

    node_ids = list(turn["input_node_ids"] or [])
    interp_ids = list(turn["input_interpretation_ids"] or [])
    names = await graph_service.get_node_names(user_id, node_ids)
    interpretations = await graph_service.get_interpretation_statements(user_id, interp_ids)
    offers = await uptake.get_offers_for_message(user_id, turn_id)
    brief = _brief_slice(_jsonb(turn["piece_brief"]))

    view = {
        # preserve the pipeline's node order; fall back to the slug if a node was pruned
        "input_nodes": [{"id": nid, "name": names.get(nid, nid)} for nid in node_ids],
        "interpretations": interpretations,
        "steering_objective": turn["steering_objective"],
        "piece_brief": brief,
        "element_offers": offers,
        "summary": turn["thinking_summary"],
    }

    # Lazy, cached, cost-gated narrativized read. Best-effort — the artifacts stand alone.
    if view["summary"] is None and APP_CONFIG.enable_thinking_summary:
        try:
            view["summary"] = await _generate_summary(user_id, turn_id, view)
        except Exception:
            logger.warning("thinking summary generation failed", extra={"turn_id": str(turn_id)})

    return view


async def _generate_summary(user_id: UUID, turn_id: UUID, view: dict) -> str | None:
    """One cheap-model call turning the real artifacts into a short 'the system's read' — then cache
    it on the turn so it's generated at most once. Grounded strictly in the artifacts."""
    from llm.client import chat

    facts = {
        "concepts": [n["name"] for n in view["input_nodes"]],
        "readings": [i["statement"] for i in view["interpretations"]],
        "steering_objective": view["steering_objective"],
        "brief": view["piece_brief"],
    }
    raw = await chat(
        messages=[
            {"role": "system", "content": (
                "You write a short, warm second-person note (2-3 sentences) explaining what "
                "the author was paying attention to when it wrote a beat, grounded ONLY in "
                "the given facts. No analysis-to-the-user's-face, no clinical language, no "
                "invented details. If the facts are thin, keep it brief and honest."
            )},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        model=APP_CONFIG.utility_model_resolved,
        temperature=0.5,
    )
    summary = (raw or "").strip()
    if not summary:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversation_turns SET thinking_summary = $3 "
            "WHERE user_id = $1 AND message_id = $2",
            str(user_id), str(turn_id), summary,
        )
    return summary
