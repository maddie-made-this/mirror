"""
Story documents (product reshape §2.2 / P1.1).

A story is a DERIVED view over a conversation's canon turns — content is NEVER copied
into the stories row. "Save as story" inserts the metadata row; the document renders by
reading conversation_turns WHERE is_canon, so canonize / edit / variant-pick automatically
reflow into the document. Load-bearing: derive-don't-copy = zero sync logic, one source
of truth.
"""
import json
import logging
from uuid import UUID

from db.postgres import get_pool
from schemas.story import StoryBeat, StorySummary

logger = logging.getLogger(__name__)


def _jsonb(v) -> dict:
    """asyncpg may hand back jsonb as a str (no codec) or a dict — normalise to dict."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {}
    return v or {}


def _to_summary(row) -> StorySummary:
    return StorySummary(
        id=row["id"],
        source_conversation_id=row["source_conversation_id"],
        title=row["title"],
        pinned=row["pinned"],
        cover_state=_jsonb(row["cover_state"]),
        color_map=_jsonb(row["color_map"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create_story(
    user_id: UUID, source_conversation_id: UUID, title: str | None = None
) -> StorySummary:
    """'Save as story': upsert the metadata row. Content stays derived from canon turns.

    Idempotent per conversation — a story is just a pointer to a conversation's
    canon, so two stories over the same conversation would render identically.
    Re-saving refreshes the existing row (title + updated_at) rather than making a
    duplicate.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM stories WHERE user_id = $1 AND source_conversation_id = $2",
            str(user_id), str(source_conversation_id),
        )
        if existing:
            row = await conn.fetchrow(
                """
                UPDATE stories
                SET title = coalesce($3, title), updated_at = now()
                WHERE id = $1 AND user_id = $2
                RETURNING *
                """,
                existing["id"], str(user_id), title,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO stories (user_id, source_conversation_id, title)
                VALUES ($1, $2, $3)
                RETURNING *
                """,
                str(user_id), str(source_conversation_id), title,
            )
    return _to_summary(row)


async def get_story(story_id: UUID, user_id: UUID) -> StorySummary | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM stories WHERE id = $1 AND user_id = $2",
            str(story_id), str(user_id),
        )
    return _to_summary(row) if row else None


async def list_stories(user_id: UUID) -> list[StorySummary]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM stories WHERE user_id = $1 ORDER BY updated_at DESC",
            str(user_id),
        )
    return [_to_summary(r) for r in rows]


async def render_story(story_id: UUID, user_id: UUID) -> list[StoryBeat]:
    """DERIVE the document: the source conversation's canon beats in order. Never copies —
    a canonize/edit/variant-pick is reflected on the next read for free."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        story = await conn.fetchrow(
            "SELECT source_conversation_id FROM stories WHERE id = $1 AND user_id = $2",
            str(story_id), str(user_id),
        )
        if not story:
            return []
        rows = await conn.fetch(
            """
            SELECT message_id, response_text
            FROM conversation_turns
            WHERE conversation_id = $1 AND user_id = $2 AND is_canon
            ORDER BY created_at
            """,
            str(story["source_conversation_id"]), str(user_id),
        )
    # turn_id is the message_id (the app-facing serverId) so the document editor and the
    # chat editor address the same beat via the one PATCH /turns/{turn_id}/text endpoint
    # (P1.5) — not the internal `id` surrogate the chat client never sees.
    return [StoryBeat(turn_id=r["message_id"], text=r["response_text"] or "") for r in rows]


async def update_story_meta(
    story_id: UUID,
    user_id: UUID,
    *,
    title: str | None = None,
    pinned: bool | None = None,
    cover_state: dict | None = None,
) -> StorySummary | None:
    """Patch metadata (COALESCE keeps unspecified fields). Content is never stored here."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE stories
            SET title = COALESCE($3, title),
                pinned = COALESCE($4, pinned),
                cover_state = COALESCE($5::jsonb, cover_state),
                updated_at = now()
            WHERE id = $1 AND user_id = $2
            RETURNING *
            """,
            str(story_id), str(user_id), title, pinned,
            json.dumps(cover_state) if cover_state is not None else None,
        )
    return _to_summary(row) if row else None
