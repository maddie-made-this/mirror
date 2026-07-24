#!/usr/bin/env python3
"""
Wipe ONE test user's conversation + graph state for a clean test run
(next_test_tech_spec C5a). Clears the Neo4j graph, the Qdrant node-embedding points,
and the Supabase conversation/derived tables for that user. Does NOT touch
auth / account / profile rows.

Run from backend/:
    PYTHONPATH=src python scripts/wipe_test_state.py --yes              # default SIM_TEST_EMAIL
    PYTHONPATH=src python scripts/wipe_test_state.py --account2 --yes
    PYTHONPATH=src python scripts/wipe_test_state.py --user-id <uuid> --yes
Without --yes it only prints the resolved target (dry run).
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND / "src"))


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_dotenv(_BACKEND / ".env")

# Public tables keyed by user_id that hold conversation / derived state.
# Ordered children -> parents so a missing ON DELETE CASCADE can't block a parent delete.
#
# PRESERVED ON WIPE (never listed here): public.profiles — holds username, avatar_url,
# theme, and settings (enter_to_send, memory_paused, preferred_language, preferred_model).
# auth.users is also never touched. A persona wipe keeps identity + settings; it clears
# only conversation + graph state.
#
# NOTE: per-turn / per-conversation derived state (piece_brief, stage_timings, piece_frame,
# is_canon, generation_inputs) are COLUMNS on conversation_turns / conversations, so they
# are cleared automatically with their parent rows — they are NOT separate tables.
#
# >>> If you add a new user_id-keyed table, add it here (children before parents). <<<
_USER_TABLES = [
    "message_feedback", "element_offers", "user_dynamics", "idempotency_keys",
    "conversation_turns", "conversations",
]


async def _resolve_uid(conn, args) -> tuple[str, str]:
    if args.user_id:
        return args.user_id, "(by --user-id)"
    suffix = "3" if args.account3 else "2" if args.account2 else ""
    email = args.email or os.environ.get(f"SIM_TEST_EMAIL{suffix}", "")
    if not email:
        raise SystemExit("No email/user-id. Set SIM_TEST_EMAIL or pass --email/--user-id.")
    row = await conn.fetchrow("SELECT id FROM auth.users WHERE email = $1", email)
    if not row:
        raise SystemExit(f"No auth user for {email}.")
    return str(row["id"]), email


async def main(args) -> None:
    from config.loader import APP_CONFIG
    from db.neo4j import get_session, init_driver
    from db.postgres import get_pool
    from db.qdrant import get_client, init_client
    from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

    pool = await get_pool()
    async with pool.acquire() as conn:
        uid, email = await _resolve_uid(conn, args)
    print(f"Target user: {uid}  ({email})")
    if not args.yes:
        print("DRY RUN — re-run with --yes to wipe Neo4j graph + Qdrant node vectors + "
              "conversation tables. Auth/account/profile are never touched.")
        return

    # Neo4j — all graph nodes/rels for the user (Node, Mention, Cluster, Interpretation).
    await init_driver()
    async with get_session() as s:
        res = await s.run(
            "MATCH (n {user_id: $uid}) DETACH DELETE n RETURN count(n) AS c", uid=uid
        )
        rec = await res.single()
        print(f"Neo4j: detached+deleted {rec['c']} nodes for user")

    # Qdrant — node-embedding points for the user (edge-label collection is shared/global).
    await init_client()
    sel = FilterSelector(filter=Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=uid))]
    ))
    await get_client().delete(collection_name=APP_CONFIG.node_collection, points_selector=sel)
    print(f"Qdrant: deleted points in {APP_CONFIG.node_collection} for user")

    # Supabase — conversation + derived tables (children first).
    async with pool.acquire() as conn:
        for t in _USER_TABLES:
            try:
                status = await conn.execute(f"DELETE FROM {t} WHERE user_id = $1", uid)
                print(f"  {t}: {status}")
            except Exception as e:  # missing table / FK — report, keep going
                print(f"  {t}: SKIP ({type(e).__name__}: {e})")

    # Drift guard: flag any user_id-keyed public table NOT in the wipe list (except profiles).
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name = 'user_id'
            """
        )
        known = set(_USER_TABLES) | {"profiles"}
        unlisted = sorted({r["table_name"] for r in rows} - known)
        if unlisted:
            print(f"  WARNING: user_id tables NOT wiped (add to _USER_TABLES?): {unlisted}")
    print("Done. Auth/account/profile rows untouched.")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Wipe a test user's conversation+graph state.")
    p.add_argument("--user-id", default="")
    p.add_argument("--email", default="")
    p.add_argument("--account2", action="store_true")
    p.add_argument("--account3", action="store_true")
    p.add_argument("--yes", action="store_true", help="actually perform the wipe")
    asyncio.run(main(p.parse_args()))
