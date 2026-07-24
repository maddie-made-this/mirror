from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


class DeepHealthResponse(BaseModel):
    status: str
    neo4j: str
    qdrant: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/deep", response_model=DeepHealthResponse)
async def deep_health() -> DeepHealthResponse:
    """
    Checks connectivity to each downstream dependency (F4).
    Returns 'degraded' if any dependency is unreachable.
    """
    from db.neo4j import get_session
    from db.qdrant import get_client

    neo4j_status = "ok"
    qdrant_status = "ok"

    try:
        async with get_session() as session:
            await session.run("RETURN 1")
    except Exception:
        neo4j_status = "down"

    try:
        await get_client().get_collections()
    except Exception:
        qdrant_status = "down"

    overall = "ok" if neo4j_status == "ok" and qdrant_status == "ok" else "degraded"
    return DeepHealthResponse(status=overall, neo4j=neo4j_status, qdrant=qdrant_status)
