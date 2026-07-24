"""
Tier-2 pipeline integration tests (SPEC_tier_2_integration_test.md §9.2).

Real Neo4j round-trip (save_interpretation -> Cypher -> get_node_readings); the LLM is
the only mock. Covers the happy path, the size floor, NO_MATCH + invalid-key audit
logging, the API-facing readings bucket, and the churn-fix behaviours (stable-identity
refresh + orphan prune). Run on its own so the real creds from conftest take effect:

    python -m pytest backend/tests/integration/ -q
"""
import json
import logging

import pytest

from schemas.interpretation import Interpretation, InterpretationKind
from services import graph_service
from services import tier_2_matcher as m


def _chat_returning(payload: dict):
    async def _fake(messages, **kw):
        return json.dumps(payload)
    return _fake


async def _angles(user_id, *, include_rejected=False):
    from db.neo4j import get_session
    clause = "" if include_rejected else "WHERE coalesce(i.status,'candidate') <> 'rejected'"
    async with get_session() as s:
        res = await s.run(
            f"MATCH (i:Interpretation {{user_id:$uid, kind:'angle'}}) {clause} "
            f"RETURN properties(i) AS p",
            uid=str(user_id),
        )
        return [r["p"] async for r in res]


# 1.1 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_matcher_creates_angle_for_qualifying_cluster(
    monkeypatch, seeded_cluster, test_user_id
):
    cid, node_ids = seeded_cluster
    monkeypatch.setattr("services.tier_2_matcher.chat", _chat_returning({
        "angle_key": "grasping_a_whole_system",
        "matched_evidence": "recursion, entropy, isomorphism — the same structure across fields",
        "confidence": 0.85,
    }), raising=False)

    n = await m.match_clusters(test_user_id)
    assert n == 1
    rows = await _angles(test_user_id)
    assert len(rows) == 1
    a = rows[0]
    assert a["angle_key"] == "grasping_a_whole_system"
    assert a["statement"] == "grasping a whole system"
    assert a["confidence"] == pytest.approx(0.85)
    assert a["attached_cluster_ids"] == [cid]
    assert set(node_ids) <= set(a["attached_node_ids"])
    assert a["what_would_change_this"]      # populated from felt_distinction_from_neighbors


# 1.2 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_matcher_skips_undersized_clusters(monkeypatch, graph, test_user_id):
    from db.neo4j import get_session
    cid = f"{test_user_id}:c:small"
    async with get_session() as s:
        await s.run("CREATE (c:Cluster {user_id:$uid, id:$cid, label:'tiny'})",
                    uid=str(test_user_id), cid=cid)
        for nid in ["concept:a", "concept:b"]:
            await s.run(
                "CREATE (n:Node {user_id:$uid, id:$nid, name:$nid, entity_type:'concept', cluster_id:$cid})",
                uid=str(test_user_id), nid=nid, cid=cid,
            )
            await s.run(
                "MATCH (n:Node {id:$nid,user_id:$uid}),(c:Cluster {id:$cid,user_id:$uid}) "
                "MERGE (n)-[:IN_CLUSTER]->(c)",
                nid=nid, uid=str(test_user_id), cid=cid,
            )

    called = []

    async def spy_chat(messages, **kw):
        called.append(1)
        return json.dumps({"angle_key": "NO_MATCH", "confidence": 0.0})
    monkeypatch.setattr("services.tier_2_matcher.chat", spy_chat, raising=False)

    await m.match_clusters(test_user_id)
    assert called == []                                  # LLM never invoked below the size floor
    assert await _angles(test_user_id) == []


# 1.3 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_matcher_logs_no_match_correctly(
    monkeypatch, seeded_cluster, test_user_id, caplog
):
    cid, _ = seeded_cluster
    monkeypatch.setattr("services.tier_2_matcher.chat", _chat_returning({
        "angle_key": "NO_MATCH", "matched_evidence": "no clear felt-fit", "confidence": 0.0,
    }), raising=False)

    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        await m.match_clusters(test_user_id)

    assert await _angles(test_user_id) == []
    miss = [r for r in caplog.records if r.getMessage() == "angle_match_misses"]
    assert miss, "expected an angle_match_misses log line"
    rec = miss[0]
    assert rec.user_id == str(test_user_id)
    assert rec.cluster_id == cid
    assert rec.member_names                              # cluster member names present
    assert hasattr(rec, "mention_sample")


# 1.4 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_matcher_treats_invalid_vocabulary_key_as_no_match(
    monkeypatch, seeded_cluster, test_user_id, caplog
):
    monkeypatch.setattr("services.tier_2_matcher.chat", _chat_returning({
        "angle_key": "totally_made_up_angle", "matched_evidence": "x", "confidence": 0.8,
    }), raising=False)

    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        await m.match_clusters(test_user_id)

    assert await _angles(test_user_id) == []             # invalid key cannot persist
    assert any(r.getMessage() == "angle_match_misses" and getattr(r, "reason", "") == "invalid_key"
               for r in caplog.records)
    assert any(r.getMessage() == "angle_matcher_invalid_key" and r.levelno == logging.WARNING
               for r in caplog.records), "expected a WARNING audit line for the hallucinated key"


# 1.5 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_node_readings_returns_angle_bucket(
    monkeypatch, seeded_cluster, test_user_id
):
    _, node_ids = seeded_cluster
    monkeypatch.setattr("services.tier_2_matcher.chat", _chat_returning({
        "angle_key": "grasping_a_whole_system", "matched_evidence": "x", "confidence": 0.85,
    }), raising=False)
    await m.match_clusters(test_user_id)

    readings = await graph_service.get_node_readings(test_user_id, node_ids[0])
    assert "angle" in readings
    assert readings["angle"], "angle bucket should be populated for an angled cluster member"
    assert readings["angle"][0]["statement"] == "grasping a whole system"


# 1.6 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_churn_resistance_across_repeated_runs(
    monkeypatch, seeded_cluster, test_user_id, caplog
):
    from db.neo4j import get_session
    cid, node_ids = seeded_cluster
    monkeypatch.setattr("services.tier_2_matcher.chat", _chat_returning({
        "angle_key": "grasping_a_whole_system", "matched_evidence": "x", "confidence": 0.8,
    }), raising=False)

    await m.match_clusters(test_user_id)                 # run 1 — creates the angle
    assert len(await _angles(test_user_id)) == 1

    # Regenerate the cluster_id — what clustering does on every tick (DETACH DELETE the
    # :Cluster, re-cluster the same nodes under a fresh membership-hash id).
    new_cid = f"{test_user_id}:c:test_cluster_REGEN"
    async with get_session() as s:
        await s.run("MATCH (c:Cluster {user_id:$uid, id:$old}) DETACH DELETE c",
                    uid=str(test_user_id), old=cid)
        await s.run("CREATE (c:Cluster {user_id:$uid, id:$cid, label:'structural patterns'})",
                    uid=str(test_user_id), cid=new_cid)
        for nid in node_ids:
            await s.run("MATCH (n:Node {id:$nid, user_id:$uid}) SET n.cluster_id=$cid",
                        nid=nid, uid=str(test_user_id), cid=new_cid)
            await s.run(
                "MATCH (n:Node {id:$nid,user_id:$uid}),(c:Cluster {id:$cid,user_id:$uid}) "
                "MERGE (n)-[:IN_CLUSTER]->(c)",
                nid=nid, uid=str(test_user_id), cid=new_cid,
            )

    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        await m.match_clusters(test_user_id)             # run 2 — must refresh, not duplicate

    rows = await _angles(test_user_id)
    assert len(rows) == 1, "stable-identity dedup must not mint a duplicate"
    assert rows[0]["attached_cluster_ids"] == [new_cid]  # re-pointed at the regenerated id
    assert any(r.getMessage() == "tier_2_angle_refreshed" for r in caplog.records)


# 1.7 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_orphan_prune_rejects_dead_angles(graph, test_user_id, caplog):
    from services.interpretation import save_interpretation

    # An angle pinned to a cluster + nodes that don't exist — i.e. a churn artifact.
    await save_interpretation(Interpretation(
        user_id=test_user_id, statement="grasping a whole system",
        kind=InterpretationKind.ANGLE, angle_key="grasping_a_whole_system", confidence=0.8,
        attached_cluster_ids=["nonexistent-cluster"],
        attached_node_ids=["nonexistent-node-1", "nonexistent-node-2"],
    ))

    # No live clusters exist, so match_clusters only runs the orphan-prune pass.
    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        await m.match_clusters(test_user_id)

    rows = await _angles(test_user_id, include_rejected=True)
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"
    assert "orphaned" in (rows[0].get("rejected_reason") or "")
    assert any(r.getMessage() == "tier_2_angles_pruned" for r in caplog.records)


# 1.8 ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_supersession_rejects_dangling_duplicate(
    monkeypatch, seeded_cluster, test_user_id, caplog
):
    """Legacy-dedup follow-up: a dangling angle whose members are subsumed by a LIVE
    same-key angle is rejected (the live one survives). This is the pre-fix churn the
    orphan-prune deliberately keeps (members still cluster)."""
    from services.interpretation import save_interpretation

    cid, node_ids = seeded_cluster
    monkeypatch.setattr("services.tier_2_matcher.chat", _chat_returning({
        "angle_key": "grasping_a_whole_system", "matched_evidence": "x", "confidence": 0.85,
    }), raising=False)
    await m.match_clusters(test_user_id)                  # the LIVE angle (attached to cid)
    assert len(await _angles(test_user_id)) == 1

    # Inject a dangling duplicate: same key + same members, but a dead cluster id.
    await save_interpretation(Interpretation(
        user_id=test_user_id, statement="grasping a whole system",
        kind=InterpretationKind.ANGLE, angle_key="grasping_a_whole_system", confidence=0.8,
        attached_cluster_ids=["dead-cluster"], attached_node_ids=node_ids,
    ))
    assert len(await _angles(test_user_id)) == 2          # live + dangling duplicate

    with caplog.at_level(logging.INFO, logger="services.tier_2_matcher"):
        await m.match_clusters(test_user_id)              # supersession rejects the duplicate

    live = await _angles(test_user_id)
    assert len(live) == 1                                 # back to one
    assert live[0]["attached_cluster_ids"] == [cid]       # the LIVE angle survived
    allrows = await _angles(test_user_id, include_rejected=True)
    rejected = [r for r in allrows if r["status"] == "rejected"]
    assert rejected and "superseded" in (rejected[0].get("rejected_reason") or "")
    assert any(r.getMessage() == "tier_2_angles_superseded" for r in caplog.records)
