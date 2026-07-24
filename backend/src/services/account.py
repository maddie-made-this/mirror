"""Account settings reads/writes (product reshape §10.3/§10.4 / P5.1).

The training-consent toggle (cross-user model training is opt-in; per-user graph learning
is always on — different layers) and the is_dev flag that gates the debug panel. Both are
columns on public.profiles (keyed by id).
"""
from uuid import UUID

from db.postgres import get_pool


async def get_account_flags(user_id: UUID) -> dict:
    """{is_dev, training_consent} for the current user (defaults if the row is absent)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT coalesce(is_dev, false) AS is_dev, "
            "coalesce(training_consent, false) AS training_consent "
            "FROM profiles WHERE id = $1",
            str(user_id),
        )
    if row is None:
        return {"is_dev": False, "training_consent": False}
    return {"is_dev": row["is_dev"], "training_consent": row["training_consent"]}


async def get_preferred_model(user_id: UUID) -> str | None:
    """The user's stored response-model choice, unvalidated. Callers must pass it
    through services.models.resolve() before use — the column is free text and may
    hold a retired or hand-edited value."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT preferred_model FROM profiles WHERE id = $1", str(user_id)
        )
    return row["preferred_model"] if row and row["preferred_model"] else None


async def set_training_consent(user_id: UUID, consent: bool) -> None:
    """Set the cross-user-training consent flag. Per-user personalization is unaffected —
    it is always on (the product), never gated by this."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE profiles SET training_consent = $2 WHERE id = $1",
            str(user_id), consent,
        )
