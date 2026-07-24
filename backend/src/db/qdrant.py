from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from config.loader import APP_CONFIG
from core.settings import get_settings

_client: AsyncQdrantClient | None = None


async def init_client() -> None:
    global _client
    s = get_settings()
    _client = AsyncQdrantClient(
        url=s.qdrant_url,
        api_key=s.qdrant_api_key or None,
        timeout=10,  # seconds — prevents hung requests blocking the pipeline (F3)
    )
    await _ensure_collections()


async def close_client() -> None:
    global _client
    if _client:
        await _client.close()
        _client = None


def get_client() -> AsyncQdrantClient:
    if not _client:
        raise RuntimeError("Qdrant client not initialised — call init_client() at startup")
    return _client


async def _ensure_collections() -> None:
    client = get_client()
    existing = {c.name for c in (await client.get_collections()).collections}

    for collection in (APP_CONFIG.node_collection, APP_CONFIG.edge_label_collection):
        if collection not in existing:
            await client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=APP_CONFIG.embedding_dim,  # driven by config, not hardcoded (E10)
                    distance=Distance.COSINE,
                ),
            )
