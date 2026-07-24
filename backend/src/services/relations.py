"""
relates_to similarity pass.

Two concepts can be embedding-near ("clay wobbling and collapsing" vs "throwing
pottery") yet land in different communities with no edge between them. This pass
adds a weak `relates_to` :EDGE between high-similarity, not-yet-connected pairs.
Grounded in embeddings (not interpretation), so it's defensible data — and it
both pulls the pair visually closer and gives bridge detection a cross-community
edge to find. Runs in the maintenance pipeline after clustering.
"""

import logging
from uuid import UUID, uuid5

from config.loader import APP_CONFIG
from db.neo4j import get_session

logger = logging.getLogger(__name__)

# Similarity band: above this is "kin". Pairs above the dedup/cluster threshold
# (0.62) would already have merged at ingest, so in practice hits sit just below.
_SIM_THRESHOLD = 0.5
_NEIGHBORS_PER_NODE = 3
_MAX_NEW_EDGES = 40


def _point_id(user_id: UUID, node_id: str) -> str:
    return str(uuid5(user_id, node_id))


async def relates_to_pass(user_id: UUID) -> int:
    """Create weak relates_to edges between embedding-near, unconnected nodes."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from db.qdrant import get_client

    client = get_client()
    collection = APP_CONFIG.node_collection

    async with get_session() as session:
        res = await session.run(
            "MATCH (n:Node {user_id: $uid}) RETURN n.id AS id", uid=str(user_id)
        )
        node_ids = [r["id"] async for r in res]
    if len(node_ids) < 3:
        return 0

    user_filter = Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
    )
    seen_pairs: set[frozenset[str]] = set()
    created = 0

    for nid in node_ids:
        if created >= _MAX_NEW_EDGES:
            break
        try:
            recs = await client.retrieve(
                collection_name=collection, ids=[_point_id(user_id, nid)], with_vectors=True
            )
        except Exception:
            continue
        if not recs or not getattr(recs[0], "vector", None):
            continue

        try:
            resp = await client.query_points(
                collection_name=collection,
                query=recs[0].vector,
                query_filter=user_filter,
                limit=_NEIGHBORS_PER_NODE + 1,  # +1: self is the top hit
                score_threshold=_SIM_THRESHOLD,
            )
        except Exception:
            continue

        for hit in resp.points:
            other = (hit.payload or {}).get("node_id")
            if not other or other == nid:
                continue
            pair = frozenset((nid, other))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            if await _edge_exists(nid, other, user_id):
                continue
            if await _create_relates_to(nid, other, user_id):
                created += 1
                if created >= _MAX_NEW_EDGES:
                    break

    if created:
        logger.info("relates_to_pass", extra={"user_id": str(user_id), "edges": created})
    return created


async def _edge_exists(a: str, b: str, user_id: UUID) -> bool:
    async with get_session() as session:
        res = await session.run(
            """
            MATCH (x:Node {user_id: $uid})-[e:EDGE]-(y:Node {user_id: $uid})
            WHERE x.id = $a AND y.id = $b
            RETURN count(e) AS c
            """,
            uid=str(user_id), a=a, b=b,
        )
        row = await res.single()
        return bool(row and row["c"] > 0)


async def _create_relates_to(a: str, b: str, user_id: UUID) -> bool:
    """
    MERGE a weak relates_to :EDGE (canonical order a<b) with the full set of
    GraphEdge properties (ISO timestamps, all required fields) so the read path
    deserializes it cleanly.
    """
    from datetime import datetime, timezone
    from uuid import uuid4

    src, tgt = sorted((a, b))
    now = datetime.now(timezone.utc).isoformat()
    props = {
        "id": str(uuid4()),
        "relation_type": "relates_to",
        "weight": 0.5,
        "causal_class": "associative",
        "is_directional": False,
        "is_negated": False,
        "proposition_id": str(uuid4()),
        "knowledge_source": "llm_inferred",
        "created_at": now,
        "last_seen_at": now,
        "first_session": 0,
        "last_session": 0,
        "inferred_similarity": True,
    }
    async with get_session() as session:
        res = await session.run(
            """
            MATCH (s:Node {id: $src, user_id: $uid})
            MATCH (t:Node {id: $tgt, user_id: $uid})
            MERGE (s)-[e:EDGE {relation_type: 'relates_to', user_id: $uid}]->(t)
            ON CREATE SET e += $props, e.user_id = $uid
            RETURN e.id AS id
            """,
            src=src, tgt=tgt, uid=str(user_id), props=props,
        )
        return (await res.single()) is not None
