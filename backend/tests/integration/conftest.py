"""
Integration-test harness for the tier-2 pipeline (SPEC_tier_2_integration_test.md).

These tests hit the LIVE dev Neo4j (real writes via save_interpretation, the real
persist→query round-trip the API depends on); only the LLM is mocked. Run them on
their own so the real creds below take effect before config is cached:

    python -m pytest backend/tests/integration/ -q

The root conftest (backend/tests/conftest.py) forces *dummy* Neo4j creds for the
mocked unit suite. Integration needs the real ones, so we override here at module
import — which runs before test collection imports config.loader / db.neo4j (and thus
before core.settings.get_settings() caches the creds). If Neo4j is unreachable the
fixtures skip rather than fail.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

# --- Force the REAL Neo4j (+ Qdrant) creds from backend/.env, overriding the root
# conftest's dummies. Must happen before get_settings() is first called. ---
_ENV = Path(__file__).resolve().parents[2] / ".env"   # backend/.env
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k = _k.strip()
            if _k.startswith("NEO4J") or _k.startswith("QDRANT"):
                os.environ[_k] = _v.strip()   # FORCE (override, not setdefault)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def test_user_id():
    """A throwaway user_id per test — keeps the live graph isolated + wipeable."""
    return uuid4()


@pytest_asyncio.fixture
async def graph(test_user_id):
    """
    Bring up a Neo4j driver bound to this test's event loop (skip the test if the dev
    Neo4j isn't reachable), and DETACH DELETE the test user's graph + close the driver
    on teardown. A fresh driver per test is required because pytest-asyncio uses a new
    loop per test and the async driver is loop-bound.
    """
    from db.neo4j import close_driver, get_session, init_driver
    try:
        await init_driver()
        async with get_session() as s:
            await (await s.run("RETURN 1 AS ok")).single()
    except Exception as e:   # noqa: BLE001 — any connect/auth error => skip, not fail
        pytest.skip(f"Neo4j not reachable for integration tests: {e!r}")
    try:
        yield
    finally:
        try:
            async with get_session() as s:
                await s.run("MATCH (n {user_id: $uid}) DETACH DELETE n", uid=str(test_user_id))
        finally:
            await close_driver()


@pytest_asyncio.fixture
async def seeded_cluster(graph, test_user_id):
    """
    A 4-node :Cluster with the exact relationships the matcher's _candidate_clusters
    query reads — (n:Node)-[:IN_CLUSTER]->(c:Cluster) and (m:Mention)-[:REFERENCES]->(n)
    — plus Node.cluster_id (read by get_node_readings + the orphan-prune). Returns
    (cluster_id, node_ids).
    """
    from db.neo4j import get_session
    cid = f"{test_user_id}:c:test_cluster"
    names = ["recursion", "entropy", "isomorphism", "provenance"]
    node_ids = [f"concept:{n}" for n in names]
    async with get_session() as s:
        await s.run(
            "CREATE (c:Cluster {user_id:$uid, id:$cid, label:'structural patterns'})",
            uid=str(test_user_id), cid=cid,
        )
        for name, nid in zip(names, node_ids):
            await s.run(
                """
                CREATE (n:Node {user_id:$uid, id:$nid, name:$name, entity_type:'concept',
                                cluster_id:$cid, mention_count:3, created_at:$now,
                                valence_score:0.7, salience_score:0.7})
                """,
                uid=str(test_user_id), nid=nid, name=name, cid=cid, now=now_iso(),
            )
            await s.run(
                """
                MATCH (n:Node {id:$nid, user_id:$uid}), (c:Cluster {id:$cid, user_id:$uid})
                MERGE (n)-[:IN_CLUSTER]->(c)
                """,
                nid=nid, uid=str(test_user_id), cid=cid,
            )
            await s.run(
                """
                MATCH (n:Node {id:$nid, user_id:$uid})
                CREATE (:Mention {user_id:$uid, text:$text, created_at:$now})-[:REFERENCES]->(n)
                """,
                nid=nid, uid=str(test_user_id),
                text=f"I keep coming back to {name} when I'm trying to explain something", now=now_iso(),
            )
    return cid, node_ids
