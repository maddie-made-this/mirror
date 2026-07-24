from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from api.deps import CurrentUserID
from schemas.graph import ClusterInfo, GraphEdge, GraphNode, Mention
from schemas.panels import AngleSummary, ConceptSummary, GraphSummary
from services import extraction_queue, graph_service

router = APIRouter(prefix="/graph", tags=["graph"])


# Registered BEFORE the "/{user_id}" route below: a literal path must be declared first,
# or FastAPI tries to parse "summary" as the UUID user_id and 422s.
@router.get("/summary", response_model=GraphSummary)
async def graph_summary(current_user_id: CurrentUserID) -> GraphSummary:
    """The 'You' panel (P2.1): top tier-2 angle readings + most-active concepts for the
    authenticated user. Read-only; links out to the full map + the coverage meter (P3.6)."""
    angles = await graph_service.get_top_angles(current_user_id, limit=5)
    concepts = await graph_service.get_active_concepts(current_user_id, limit=12)
    return GraphSummary(
        top_angles=[AngleSummary(**a) for a in angles],
        active_concepts=[ConceptSummary(**c) for c in concepts],
    )


class OverlayInterpretation(BaseModel):
    id: str
    statement: str
    kind: str
    confidence: float
    cluster_ids: list[str]


class ClusterSimilarity(BaseModel):
    a: str
    b: str
    score: float


class CooccurrenceEdge(BaseModel):
    source_id: str
    target_id: str
    weight: float


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    clusters: list[ClusterInfo] = []
    interpretations: list[OverlayInterpretation] = []
    cluster_similarity: list[ClusterSimilarity] = []
    cooccurrence: list[CooccurrenceEdge] = []


class ProcessingStatus(BaseModel):
    """Visible-queue status for the background extraction worker (Change 1):
    how many of this user's turns are still being processed, and the ids of nodes
    that recently landed — so the UI can show a quiet "N processing" indicator and
    pop new nodes onto the map as they arrive (within seconds, not next session)."""
    pending: int = 0
    recently_added_node_ids: list[str] = []


def _require_owner(user_id: UUID, current_user_id: UUID) -> None:
    if user_id != current_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@router.get("/{user_id}", response_model=GraphResponse)
async def get_graph(
    user_id: UUID,
    current_user_id: CurrentUserID,
    limit: int = 500,
    min_mentions: int = 1,
    entity_types: list[str] | None = Query(default=None),
    include_negated: bool = False,
    include_cooccurrence: bool = False,
) -> GraphResponse:
    """Paginated, filterable graph for the visualization endpoint."""
    _require_owner(user_id, current_user_id)
    nodes, edges = await graph_service.get_user_graph(
        user_id,
        limit=limit,
        min_mentions=min_mentions,
        entity_types=entity_types,
        include_negated=include_negated,
    )
    clusters = await graph_service.get_user_clusters(user_id)
    overlays = await graph_service.get_overlay_interpretations(user_id)
    similarity = await graph_service.get_cluster_similarity(user_id)
    cooccurrence: list[dict] = []
    if include_cooccurrence:
        cooccurrence = await graph_service.get_cooccurrence_edges(
            user_id, [n.id for n in nodes]
        )
    return GraphResponse(
        nodes=nodes,
        edges=edges,
        clusters=[ClusterInfo(**c) for c in clusters],
        interpretations=[OverlayInterpretation(**o) for o in overlays],
        cluster_similarity=[ClusterSimilarity(**s) for s in similarity],
        cooccurrence=[CooccurrenceEdge(**c) for c in cooccurrence],
    )


@router.get("/{user_id}/processing", response_model=ProcessingStatus)
async def get_processing_status(
    user_id: UUID,
    current_user_id: CurrentUserID,
) -> ProcessingStatus:
    """Poll the background extraction worker for this user (Change 1). Process-local
    and in-memory: cheap to hit on a short interval from the chat/map UI."""
    _require_owner(user_id, current_user_id)
    return ProcessingStatus(**extraction_queue.processing_status(user_id))


@router.get("/{user_id}/nodes/{node_id}/mentions", response_model=list[Mention])
async def list_mentions(
    user_id: UUID,
    node_id: str,
    current_user_id: CurrentUserID,
    limit: int = 20,
) -> list[Mention]:
    """Recent mentions that reference this node, newest first."""
    _require_owner(user_id, current_user_id)
    return await graph_service.get_node_mentions(user_id, node_id, limit)


class NodeInterpretation(BaseModel):
    id: str
    statement: str
    kind: str
    confidence: float
    inferential_step: str


@router.get("/{user_id}/nodes/{node_id}/interpretations", response_model=list[NodeInterpretation])
async def list_node_interpretations(
    user_id: UUID,
    node_id: str,
    current_user_id: CurrentUserID,
) -> list[NodeInterpretation]:
    """The reasoning behind this node — interpretations that explain or cite it."""
    _require_owner(user_id, current_user_id)
    rows = await graph_service.get_node_interpretations(user_id, node_id)
    return [NodeInterpretation(**r) for r in rows]


@router.get("/{user_id}/nodes/{node_id}/cooccurring")
async def list_cooccurring(
    user_id: UUID,
    node_id: str,
    current_user_id: CurrentUserID,
    limit: int = 10,
) -> list[dict]:
    """Nodes most often co-mentioned with this node."""
    _require_owner(user_id, current_user_id)
    pairs = await graph_service.get_cooccurring_nodes(user_id, node_id, limit)
    return [{"node": n.model_dump(mode="json"), "count": c} for n, c in pairs]


@router.get("/{user_id}/nodes/{node_id}/readings")
async def node_readings(
    user_id: UUID,
    node_id: str,
    current_user_id: CurrentUserID,
) -> dict:
    """
    The explanation product (interest-model §8): this motif's coexisting
    readings — headline + origin / function / dynamics / reframing / beliefs —
    each with confidence, status, what-would-change-this, and the user's own
    words as evidence. Never collapsed into a verdict.
    """
    _require_owner(user_id, current_user_id)
    return await graph_service.get_node_readings(user_id, node_id)


@router.get("/{user_id}/mentions/entity-types")
async def list_user_mention_entity_types(
    user_id: UUID,
    current_user_id: CurrentUserID,
) -> list[str]:
    """Every entity type present across this user's mentions, unfiltered — the
    stable source for the episodic page's filter chips. Derived from the visible
    (filtered) rows instead, the chip list collapsed as soon as a filter was
    applied, hiding the other choices."""
    _require_owner(user_id, current_user_id)
    return await graph_service.get_user_mention_entity_types(user_id)


@router.get("/{user_id}/mentions")
async def list_user_mentions(
    user_id: UUID,
    current_user_id: CurrentUserID,
    limit: int = 50,
    offset: int = 0,
    entity_type: list[str] | None = Query(default=None),
    q: str = "",
) -> list[dict]:
    """
    The EPISODIC memory page: the user-wide verbatim record (what they actually
    said), newest first, searchable/filterable, each row linked to the node(s)
    it fed. The receipts layer beneath both the map and the understanding list.

    `entity_type` may repeat; multiple types INTERSECT (a row must touch all of
    them), so stacking filters narrows the record rather than widening it.
    """
    _require_owner(user_id, current_user_id)
    return await graph_service.get_user_mentions(
        user_id,
        limit=min(limit, 200),
        offset=max(offset, 0),
        entity_types=entity_type,
        q=q[:120],
    )


@router.get("/{user_id}/understanding")
async def understanding(
    user_id: UUID,
    current_user_id: CurrentUserID,
    limit: int = 100,
) -> list[dict]:
    """
    The SEMANTIC memory page: the list twin of the map — every concept/motif
    with its readings summary, high-salience and consolidated first. Same model, second
    representation (the mobile-friendly one).
    """
    _require_owner(user_id, current_user_id)
    return await graph_service.get_understanding(user_id, limit=min(limit, 300))
