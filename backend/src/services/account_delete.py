"""Delete-my-account (product reshape §10.2 / P5.1).

One job that hard-deletes a user across EVERY store — Postgres, Neo4j, Qdrant — then the
Supabase auth identity. The Postgres table list is EXPLICIT (not schema-introspected) so a
new user-scoped table is a deliberate add here, never silently missed. Backups expire
≤30 days (documented, out of band).

Idempotent and best-effort per store: a failure in one store is logged and the rest still
run, so a partial delete can be re-run to completion rather than wedging.
"""
import logging
from uuid import UUID

import httpx

from core.settings import get_settings
from db.neo4j import get_session
from db.postgres import get_pool
from db.qdrant import get_client
from config.loader import APP_CONFIG

logger = logging.getLogger(__name__)

# Every Postgres table carrying this user's data. Tables keyed by user_id, plus `profiles`
# (keyed by id). EXPLICIT by design — extend this when a new user-scoped table lands
# (Phase 3 ingest_batches/ingest_items, Phase 6 timeline_entries are NOT created yet).
_USER_ID_TABLES = (
    "action_events",
    "supersede_pairs",
    "stories",
    "message_feedback",
    "element_offers",
    "user_dynamics",
    "conversation_turns",
    "conversations",
    "idempotency_keys",
)


async def _delete_postgres(user_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for table in _USER_ID_TABLES:
                await conn.execute(
                    f"DELETE FROM public.{table} WHERE user_id = $1", str(user_id)
                )
            await conn.execute(
                "DELETE FROM public.profiles WHERE id = $1", str(user_id)
            )


async def _delete_neo4j(user_id: UUID) -> None:
    # Nodes, Mentions, Interpretations — all carry user_id. DETACH DELETE drops their edges.
    async with get_session() as session:
        await session.run(
            "MATCH (n {user_id: $uid}) DETACH DELETE n", uid=str(user_id)
        )


async def _delete_qdrant(user_id: UUID) -> None:
    from qdrant_client.models import (
        FieldCondition, Filter, FilterSelector, MatchValue,
    )
    selector = FilterSelector(
        filter=Filter(must=[
            FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))
        ])
    )
    client = get_client()
    for collection in (APP_CONFIG.node_collection, APP_CONFIG.edge_label_collection):
        await client.delete(collection_name=collection, points_selector=selector)


async def _delete_supabase_auth(user_id: UUID) -> bool:
    """Delete the auth identity via the admin API. Returns False (with a warning) when no
    service-role key is configured — the data stores are already purged either way."""
    s = get_settings()
    if not s.supabase_service_role_key:
        logger.warning("account delete: no service-role key; skipping auth identity delete",
                       extra={"user_id": str(user_id)})
        return False
    url = f"{s.supabase_url}/auth/v1/admin/users/{user_id}"
    headers = {
        "apikey": s.supabase_service_role_key,
        "Authorization": f"Bearer {s.supabase_service_role_key}",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(url, headers=headers)
        resp.raise_for_status()
    return True


async def wipe_model(user_id: UUID) -> dict:
    """
    Reset the MODEL, keep the person: erase this user's graph (Neo4j — nodes,
    mentions, interpretations, clusters, and the last_clustered marker, which is a
    node property and dies with it) and their vectors (Qdrant), leaving Postgres
    (conversations, feedback, telemetry) and the auth identity untouched.

    Safe to run mid-life: the self-node is re-bootstrapped by ensure_self_node on
    the next message, and extraction rebuilds the graph from new conversation.
    Old turns' input_node_ids keep referencing deleted nodes — that's an audit
    trail of what fed past generations, not a live join, so dangling is correct.

    Same best-effort-per-store contract as delete_user: re-runnable to completion.
    """
    status: dict[str, str] = {}
    for name, fn in (("neo4j", _delete_neo4j), ("qdrant", _delete_qdrant)):
        try:
            await fn(user_id)
            status[name] = "ok"
        except Exception:
            logger.exception("model wipe: store failed", extra={"store": name})
            status[name] = "failed"
    logger.info("model wipe complete", extra={"user_id": str(user_id), "status": status})
    return status


async def delete_user(user_id: UUID) -> dict:
    """Hard-delete a user everywhere. Best-effort per store; returns a per-store status map
    so a partial failure is visible and the job can be safely re-run."""
    status: dict[str, str] = {}
    for name, fn in (
        ("postgres", _delete_postgres),
        ("neo4j", _delete_neo4j),
        ("qdrant", _delete_qdrant),
        ("supabase_auth", _delete_supabase_auth),
    ):
        try:
            result = await fn(user_id)
            status[name] = "skipped" if result is False else "ok"
        except Exception:
            logger.exception("account delete: store failed", extra={"store": name})
            status[name] = "failed"
    logger.info("account delete complete", extra={"user_id": str(user_id), "status": status})
    return status
