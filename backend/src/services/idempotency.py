import logging
from uuid import UUID

from db.postgres import get_pool

logger = logging.getLogger(__name__)


async def claim_or_get_cached_response(
    user_id: UUID,
    conversation_id: UUID,
    client_message_id: UUID,
) -> dict | None:
    """
    Claim a (user, client_message_id) slot.

    Returns None for a fresh request (or a retry whose original is still
    in flight) — the caller should proceed with processing. Returns the cached
    response dict if this client_message_id was already processed to completion.

    The ON CONFLICT DO UPDATE is a no-op write whose only purpose is to make
    RETURNING surface the existing row when the key already exists.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO idempotency_keys
                (user_id, conversation_id, client_message_id, status)
            VALUES ($1, $2, $3, 'in_flight')
            ON CONFLICT (user_id, client_message_id) DO UPDATE
                SET client_message_id = EXCLUDED.client_message_id
            RETURNING status, response_json
            """,
            str(user_id),
            str(conversation_id),
            str(client_message_id),
        )
    if row is not None and row["status"] == "complete":
        return row["response_json"]
    return None


async def store_response(
    user_id: UUID,
    client_message_id: UUID,
    response_json: dict,
) -> None:
    """Mark a claimed slot complete and cache the response for future retries."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE idempotency_keys
            SET status = 'complete',
                response_json = $3,
                completed_at = now()
            WHERE user_id = $1 AND client_message_id = $2
            """,
            str(user_id),
            str(client_message_id),
            response_json,
        )
