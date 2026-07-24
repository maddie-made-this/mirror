"""
Periodic recluster check.

After a node accumulates enough mentions, embed each mention's source span
and run k-means with k=2 to see whether the concept has drifted into two
distinct sub-clusters. For now this is *log-only* — a high silhouette score
is flagged for human review, but no structural changes are made to the graph.

Once the signal looks trustworthy in production data, implement the actual
split: rename node A, create node B, reassign mentions by cluster label,
and redistribute edges.
"""

import logging
from uuid import UUID

from config.loader import APP_CONFIG
from db.neo4j import get_session

logger = logging.getLogger(__name__)


async def maybe_recluster_node(node_id: str, user_id: UUID) -> bool:
    """
    Check whether a node's mentions warrant a k=2 split.
    Returns True if a split happened (currently always False — log-only).

    Trigger condition: mention_count is a positive multiple of
    APP_CONFIG.recluster_check_every.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {id: $nid, user_id: $uid})
            WHERE n.mention_count > 0 AND n.mention_count % $every = 0
            OPTIONAL MATCH (m:Mention)-[:REFERENCES]->(n)
            RETURN n.mention_count AS count, collect(m.text) AS texts
            """,
            nid=node_id,
            uid=str(user_id),
            every=APP_CONFIG.recluster_check_every,
        )
        row = await result.single()

    if row is None or row["count"] < APP_CONFIG.recluster_check_every:
        return False

    texts = [t for t in row["texts"] if t]
    if len(texts) < 6:
        return False  # too few mentions to cluster meaningfully

    try:
        import numpy as np
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
    except ImportError:
        logger.warning(
            "scikit-learn / numpy not installed; recluster check skipped",
            extra={"node_id": node_id},
        )
        return False

    from services.embedding import embed_batch

    embeddings = np.array(await embed_batch(texts))

    km = KMeans(n_clusters=2, n_init=4, random_state=42).fit(embeddings)
    score = float(silhouette_score(embeddings, km.labels_))

    if score < APP_CONFIG.recluster_min_silhouette:
        return False  # not a clean two-way split

    # Signal found — log for now. The split mechanics (rename, reassign
    # mentions/edges) will be implemented once this signal proves reliable.
    logger.info(
        "node_split_candidate",
        extra={
            "node_id": node_id,
            "user_id": str(user_id),
            "mention_count": int(row["count"]),
            "silhouette": score,
            "cluster_sizes": [int((km.labels_ == i).sum()) for i in range(2)],
        },
    )
    # TODO: implement actual node split once signal is validated.
    return False
