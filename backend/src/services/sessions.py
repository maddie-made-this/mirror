import logging
from datetime import datetime, timezone
from uuid import UUID

from db.neo4j import get_session

logger = logging.getLogger(__name__)

# A new session begins after this many hours of inactivity.
_SESSION_TIMEOUT_HOURS = 4


async def get_or_create_current_session(user_id: UUID) -> int:
    """
    Return the current session number for this user.
    Creates session 1 on first call. Increments automatically after
    SESSION_TIMEOUT_HOURS of inactivity (B5).
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    async with get_session() as session:
        # MERGE ensures one UserSession node per user.
        result = await session.run(
            """
            MERGE (s:UserSession {user_id: $uid})
            ON CREATE SET s.session_number = 1, s.last_activity = $now
            RETURN s.session_number AS number, s.last_activity AS last_activity
            """,
            uid=str(user_id),
            now=now_iso,
        )
        record = await result.single()
        session_number: int = record["number"]
        last_activity_raw: str = record["last_activity"]

    last_activity = datetime.fromisoformat(last_activity_raw)
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    hours_since = (now - last_activity).total_seconds() / 3600

    if hours_since >= _SESSION_TIMEOUT_HOURS:
        session_number += 1
        async with get_session() as session:
            await session.run(
                """
                MATCH (s:UserSession {user_id: $uid})
                SET s.session_number = $new_number, s.last_activity = $now
                """,
                uid=str(user_id),
                new_number=session_number,
                now=now_iso,
            )
        logger.info(
            "New session started due to inactivity",
            extra={"user_id": str(user_id), "session_number": session_number},
        )
    else:
        async with get_session() as session:
            await session.run(
                "MATCH (s:UserSession {user_id: $uid}) SET s.last_activity = $now",
                uid=str(user_id),
                now=now_iso,
            )

    return session_number
