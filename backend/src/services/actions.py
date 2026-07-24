"""
Action-events log (product reshape §6.1 / P0.2).

A typed, queryable stream of the user's per-beat actions
(longer/shorter/retry/edit/accept_chip/canonize/decanonize). The single write point;
callers are the reaction-chip handlers, the edit endpoint, and the canonize/decanonize
(variant-pick) path. Feeds #10a length adaptation, retry diagnostics, chip weighting,
and clean supersede-pair labels.
"""
import json
import logging
from uuid import UUID

from db.postgres import get_pool

logger = logging.getLogger(__name__)

# Mirrors the CHECK constraint in 20260705120000_action_events.sql.
ACTION_KINDS = frozenset(
    {"longer", "shorter", "retry", "edit", "accept_chip", "canonize", "decanonize"}
)


async def record_action(
    user_id: UUID,
    conversation_id: UUID,
    action: str,
    *,
    target_turn_id: UUID | None = None,
    render_mode: str | None = None,
    payload: dict | None = None,
) -> None:
    """One insert into action_events. Telemetry is best-effort — it must never break a
    turn — so an unknown action is dropped with a warning rather than raised."""
    if action not in ACTION_KINDS:
        logger.warning("record_action: unknown action, dropping", extra={"action": action})
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO action_events
                (user_id, conversation_id, target_turn_id, action, render_mode, payload)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            user_id,
            conversation_id,
            target_turn_id,
            action,
            render_mode,
            json.dumps(payload or {}),
        )


async def retry_rate_7d(user_id: UUID) -> dict:
    """
    Retry diagnostics (product reshape §6.5 / P4.2): retry-rate over the last 7 days,
    derived purely from action_events. Retry is a DIAGNOSTIC (wrong model / wrong read /
    prose below bar / gacha-rolling), NEVER a preference — this only surfaces the rate for
    investigation; nothing adapts on it. Returns {retries, beat_actions, rate}.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              count(*) FILTER (WHERE action = 'retry')                         AS retries,
              count(*) FILTER (WHERE action IN ('retry','longer','shorter'))   AS beat_actions
            FROM action_events
            WHERE user_id = $1 AND created_at >= now() - interval '7 days'
            """,
            user_id,
        )
    retries = int(row["retries"] or 0)
    beat_actions = int(row["beat_actions"] or 0)
    rate = (retries / beat_actions) if beat_actions else 0.0
    return {"retries": retries, "beat_actions": beat_actions, "rate": rate}


async def record_supersede_pair(
    user_id: UUID,
    conversation_id: UUID,
    kept_turn_id: UUID,
    rejected_turn_id: UUID,
    *,
    render_mode: str | None = None,
    retry_note: str | None = None,
) -> None:
    """
    Log a kept-vs-rejected generation pair on pick-after-regenerate (the P1.4 variant-pick
    path) — the uptake signal + the DPO-style fine-tune dataset (§6.3 / P0.4). Snapshots
    training_consent from the user's CURRENT profiles setting at write time so a later
    consent change can't retroactively license this pair (L6.3). Null/missing → False.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        consent = await conn.fetchval(
            "SELECT training_consent FROM profiles WHERE id = $1", user_id
        )
        await conn.execute(
            """
            INSERT INTO supersede_pairs
                (user_id, conversation_id, kept_turn_id, rejected_turn_id,
                 render_mode, retry_note, training_consent)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            user_id,
            conversation_id,
            kept_turn_id,
            rejected_turn_id,
            render_mode,
            retry_note,
            bool(consent),
        )
