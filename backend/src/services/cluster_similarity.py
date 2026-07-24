"""
Inter-community semantic attraction (the cluster-similarity tier).

Two communities can be thematically adjacent ("creative identity" vs. "work and
worth") without sharing any edge. This pass computes each community's centroid in
embedding space — the mean of its member node vectors, fetched from Qdrant — and
the pairwise cosine between centroids, then persists the top similar pairs as
scalar-weighted (c1)-[:CLUSTER_SIMILAR {score}]->(c2) relationships.

Only the scalar similarity is persisted and ever leaves the backend. Centroids
(vectors) are computed transiently and never stored or serialized to the client,
per the architecture rule. The frontend reads the adjacency to pull semantically
near communities spatially closer, so the map's geography carries meaning.

Runs in the maintenance pipeline, right after clustering.
"""

import logging
import math
from uuid import UUID, uuid5

from config.loader import APP_CONFIG
from db.neo4j import get_session

logger = logging.getLogger(__name__)

# Below this cosine, "similarity" is mostly noise — not worth pulling together.
_MIN_SCORE = 0.15
# Each community is drawn toward only its few nearest kin (keeps the field sparse).
_TOP_K_PER_CLUSTER = 3
# Cap vector fetches per community (centroid of a sample is a fine approximation).
_MAX_MEMBERS_FOR_CENTROID = 60


def _point_id(user_id: UUID, node_id: str) -> str:
    return str(uuid5(user_id, node_id))


def _centroid(vectors: list[list[float]]) -> list[float] | None:
    """Mean vector. Skips ragged vectors defensively; returns None if empty."""
    if not vectors:
        return None
    dim = len(vectors[0])
    acc = [0.0] * dim
    used = 0
    for v in vectors:
        if len(v) != dim:
            continue
        for i, x in enumerate(v):
            acc[i] += x
        used += 1
    if used == 0:
        return None
    return [a / used for a in acc]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


async def _cluster_members(user_id: UUID) -> dict[str, list[str]]:
    """{cluster_id: [node_id, ...]} for every clustered node."""
    async with get_session() as session:
        res = await session.run(
            """
            MATCH (n:Node {user_id: $uid}) WHERE n.cluster_id IS NOT NULL
            RETURN n.cluster_id AS cid, collect(n.id) AS ids
            """,
            uid=str(user_id),
        )
        return {r["cid"]: r["ids"] async for r in res}


async def compute_cluster_similarity(user_id: UUID) -> int:
    """Centroid cosine between communities; persist top similar pairs. Returns count."""
    from db.qdrant import get_client

    members = await _cluster_members(user_id)
    if len(members) < 2:
        await _write_similarity(user_id, [])  # clear any stale edges
        return 0

    client = get_client()
    collection = APP_CONFIG.node_collection

    centroids: dict[str, list[float]] = {}
    for cid, ids in members.items():
        sample = ids[:_MAX_MEMBERS_FOR_CENTROID]
        try:
            recs = await client.retrieve(
                collection_name=collection,
                ids=[_point_id(user_id, nid) for nid in sample],
                with_vectors=True,
            )
        except Exception:
            logger.warning("centroid fetch failed", extra={"cluster_id": cid})
            continue
        vecs = [r.vector for r in recs if getattr(r, "vector", None)]
        c = _centroid(vecs)
        if c is not None:
            centroids[cid] = c

    cids = list(centroids.keys())
    if len(cids) < 2:
        await _write_similarity(user_id, [])
        return 0

    # Pairwise cosine, then keep each cluster's top-K above threshold.
    by_cluster: dict[str, list[tuple[float, str]]] = {c: [] for c in cids}
    for i in range(len(cids)):
        for j in range(i + 1, len(cids)):
            s = _cosine(centroids[cids[i]], centroids[cids[j]])
            if s >= _MIN_SCORE:
                by_cluster[cids[i]].append((s, cids[j]))
                by_cluster[cids[j]].append((s, cids[i]))

    pairs: dict[frozenset[str], float] = {}
    for cid, lst in by_cluster.items():
        lst.sort(reverse=True)
        for s, other in lst[:_TOP_K_PER_CLUSTER]:
            key = frozenset((cid, other))
            pairs[key] = max(pairs.get(key, 0.0), s)

    edges = [(*sorted(k), round(v, 4)) for k, v in pairs.items()]
    await _write_similarity(user_id, edges)
    if edges:
        logger.info(
            "cluster_similarity", extra={"user_id": str(user_id), "pairs": len(edges)}
        )
    return len(edges)


async def _write_similarity(
    user_id: UUID, edges: list[tuple[str, str, float]]
) -> None:
    """Replace this user's CLUSTER_SIMILAR edges with the freshly computed set."""
    async with get_session() as session:
        await session.run(
            "MATCH (:Cluster {user_id: $uid})-[r:CLUSTER_SIMILAR]->() DELETE r",
            uid=str(user_id),
        )
        for a, b, score in edges:
            await session.run(
                """
                MATCH (x:Cluster {id: $a, user_id: $uid})
                MATCH (y:Cluster {id: $b, user_id: $uid})
                MERGE (x)-[r:CLUSTER_SIMILAR]->(y)
                SET r.score = $score
                """,
                a=a, b=b, uid=str(user_id), score=score,
            )
