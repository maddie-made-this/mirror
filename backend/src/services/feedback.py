"""
Per-message feedback (B3 / handoff §A1) — the dominant direct-signal channel.

A 'check' / 'x' on an AI message is read as "this is right / not right *for me*"
(fit, not quality). It is linked to the turn's GENERATION INPUTS (B2:
input_node_ids / input_interpretation_ids) so the signal credits/discredits the
RIGHT graph elements, not just the message.

HARD BOUNDARY (A1.5): an 'x' note is delivery-tuning context only. It is stored on
the feedback row and never extracted, never becomes graph content, and never routes
to the interpretation layer. Keeping corrections out of the emic/function layer is
what prevents meta-noise from repolluting the graph.
"""
import asyncio
import logging
from uuid import UUID

from db.postgres import get_pool
from services import graph_service, interpretation

logger = logging.getLogger(__name__)


async def _promote_affirmation(user_id: UUID, message_id: UUID) -> None:
    """Endorsement gate: promote an affirmed turn's piece elements to USER_ACCEPTED
    user-facts. Best-effort; lazy import avoids an import cycle with extraction."""
    try:
        from services.extraction import extract_from_affirmation
        await extract_from_affirmation(user_id, message_id)
    except Exception:
        logger.exception(
            "affirmation promotion failed", extra={"message_id": str(message_id)}
        )


async def record_feedback(
    user_id: UUID,
    message_id: UUID,
    reaction: str,
    note: str | None = None,
) -> dict:
    """
    Persist the feedback and apply the dominant confidence signal.

    'check' → reinforce the nodes + interpretations that fed this generation, and
              report that the analytic-branch ("help me understand this") affordance
              is available.
    'x'     → store the note as a weighting signal on the generation only. No
              reinforcement, no extraction, no interpretation routing (A1.5).
    'note'  → the voteless third option (P2.3): a comment with no up/down judgment.
              Stored like an 'x' note — delivery-tuning only, never graph content.

    A note may accompany ANY reaction (P2.3) — it is delivery-tuning signal on the
    generation and never crosses into the graph, whatever the reaction.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        turn = await conn.fetchrow(
            """
            SELECT conversation_id, input_node_ids, input_interpretation_ids
            FROM conversation_turns
            WHERE user_id = $1 AND message_id = $2
            """,
            str(user_id),
            str(message_id),
        )
        if turn is None:
            return {"ok": False, "reason": "unknown_message"}

        await conn.execute(
            """
            INSERT INTO message_feedback
                (user_id, conversation_id, message_id, reaction, note)
            VALUES ($1, $2, $3, $4, $5)
            """,
            str(user_id),
            str(turn["conversation_id"]),
            str(message_id),
            reaction,
            note,  # P2.3: a note may ride any reaction (delivery-tuning only, never graph)
        )

    if reaction != "check":
        # 'x' / 'note': the row IS the signal. No reinforcement, no extraction, no
        # interpretation routing — boundary A1.5.
        return {"ok": True, "analytic_available": False}

    # 'check': reinforce what the graph contributed to this generation.
    node_ids = list(turn["input_node_ids"] or [])
    interp_ids = list(turn["input_interpretation_ids"] or [])
    try:
        if node_ids:
            await graph_service.reinforce_nodes(user_id, node_ids)
        if interp_ids:
            await interpretation.reinforce(user_id, interp_ids)
    except Exception:
        # Reinforcement is best-effort; the feedback row is already recorded.
        logger.exception(
            "feedback reinforcement failed", extra={"message_id": str(message_id)}
        )

    # Endorsement gate (extraction redesign §6): a 'check' is the ONLY path by which
    # a generated piece's content becomes a durable user fact. Promote the affirmed
    # turn's elements to USER_ACCEPTED — async, off the response path.
    asyncio.create_task(_promote_affirmation(user_id, message_id))

    return {"ok": True, "analytic_available": True}
