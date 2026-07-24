from openai import AsyncOpenAI

from config.loader import APP_CONFIG
from core.settings import get_settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if not _client:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _client


async def embed(text: str) -> list[float]:
    response = await _get_client().embeddings.create(
        input=text,
        model=APP_CONFIG.embedding_model,
    )
    return response.data[0].embedding


async def embed_batch(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    response = await _get_client().embeddings.create(
        input=texts,
        model=APP_CONFIG.embedding_model,
    )
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two embedding vectors (0.0 if either is empty/degenerate).
    Used for semantic dedup of bridges + readings (producer spec C2)."""
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0
