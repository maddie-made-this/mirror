import logging
from uuid import UUID

from pydantic import BaseModel
from qdrant_client.models import FieldCondition, Filter, MatchValue

from config.loader import APP_CONFIG
from core.errors import DeduplicationError
from db.qdrant import get_client

logger = logging.getLogger(__name__)


# Typed result objects — callers should not reach into raw Qdrant structures (E5).

class NodeDedupHit(BaseModel):
    canonical_id: str
    score: float


class EdgeLabelDedupHit(BaseModel):
    canonical_label: str
    score: float


async def find_similar_node(
    embedding: list[float],
    user_id: UUID,
) -> NodeDedupHit | None:
    """
    Returns the nearest node for this user if similarity > node_dedup_threshold,
    otherwise None (meaning this is a new concept).
    """
    try:
        response = await get_client().query_points(
            collection_name=APP_CONFIG.node_collection,
            query=embedding,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
            ),
            limit=1,
            score_threshold=APP_CONFIG.node_dedup_threshold,
        )
        results = response.points
    except Exception as exc:
        raise DeduplicationError(f"Node similarity search failed: {exc}") from exc

    if not results:
        return None
    return NodeDedupHit(
        canonical_id=results[0].payload["node_id"],  # type: ignore[index]
        score=results[0].score,
    )


async def find_similar_nodes(
    embedding: list[float],
    user_id: UUID,
    *,
    threshold: float | None = None,
    limit: int = 3,
) -> list[NodeDedupHit]:
    """
    Return up to `limit` existing nodes whose embedding is within `threshold`
    of the given vector, sorted by similarity (highest first).
    Used by cluster-aware ingest to find merge candidates.
    Falls back to APP_CONFIG.cluster_threshold when threshold is None.
    """
    score_threshold = threshold if threshold is not None else APP_CONFIG.cluster_threshold
    try:
        response = await get_client().query_points(
            collection_name=APP_CONFIG.node_collection,
            query=embedding,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
            ),
            limit=limit,
            score_threshold=score_threshold,
        )
        results = response.points
    except Exception as exc:
        raise DeduplicationError(f"Node cluster search failed: {exc}") from exc

    return [
        NodeDedupHit(canonical_id=r.payload["node_id"], score=r.score)  # type: ignore[index]
        for r in results
        if r.payload
    ]


async def find_similar_edge_label(
    embedding: list[float],
    user_id: UUID,
) -> EdgeLabelDedupHit | None:
    """
    Returns the nearest edge label for this user if similarity > relationship_dedup_threshold,
    otherwise None (meaning this is a new relationship type).
    """
    try:
        response = await get_client().query_points(
            collection_name=APP_CONFIG.edge_label_collection,
            query=embedding,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
            ),
            limit=1,
            score_threshold=APP_CONFIG.relationship_dedup_threshold,
        )
        results = response.points
    except Exception as exc:
        raise DeduplicationError(f"Edge label similarity search failed: {exc}") from exc

    if not results:
        return None
    return EdgeLabelDedupHit(
        canonical_label=results[0].payload["label"],  # type: ignore[index]
        score=results[0].score,
    )
