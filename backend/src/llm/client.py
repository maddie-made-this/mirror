import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx

from core.settings import get_settings

logger = logging.getLogger(__name__)

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _backend(role: str = "default") -> tuple[str, str]:
    """Resolve (url, api_key) for the active backend. The renderer is the token-heavy
    tier and can be pinned to its own provider while the director stays on OpenRouter —
    the architecture is split (the reasoner directs, the stylist renders).
    role='renderer' honors renderer_base_url / renderer_backend when set; everything
    else uses llm_backend."""
    s = get_settings()
    # Generic renderer provider (any OpenAI-compatible endpoint) takes precedence —
    # model + host are swappable config, no code change to move providers.
    if role == "renderer" and s.renderer_base_url:
        return s.renderer_base_url, s.renderer_api_key
    return _OPENROUTER_URL, s.openrouter_api_key

# Module-level pooled client — reused across all requests to avoid per-call
# TCP handshake and TLS negotiation overhead (E8).
_client: httpx.AsyncClient | None = None


async def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=60.0)
    return _client


async def close_http_client() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.3,
    sampling: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    max_retries: int = 2,
    role: str = "default",
) -> str:
    """
    Send a chat completion request via OpenRouter.
    Returns the raw content string from the first choice.
    Retries on transient 429/502/503/504 with exponential backoff (F2).

    max_tokens caps the completion length when set (and > 0) — used to bound
    cost per tier. None/0 leaves it uncapped (provider default).
    """
    s = get_settings()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if sampling:
        payload.update(sampling)  # top_p / repetition_penalty / frequency_penalty / presence_penalty
    if response_format:
        payload["response_format"] = response_format
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = max_tokens

    client = await get_http_client()
    url, api_key = _backend(role)
    # A renderer provider answers to its OWN model id, not the OpenRouter renderer_model the
    # caller passed — send the configured provider/pod model (keeps routing + loadout honest).
    if s.renderer_base_url and url == s.renderer_base_url and s.renderer_model:
        model = payload["model"] = s.renderer_model
    headers = {"Authorization": f"Bearer {api_key}"}
    # OpenRouter courtesy/attribution headers ONLY when actually hitting OpenRouter; a
    # third-party endpoint should receive a clean Authorization-only header set.
    if url == _OPENROUTER_URL:
        headers["HTTP-Referer"] = s.http_referer   # from settings, not hardcoded (E9)
        headers["X-Title"] = s.app_title

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        t0 = time.perf_counter()
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            usage = data.get("usage", {})
            logger.info(
                "llm_call",
                extra={
                    "model": model,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                },
            )
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in (429, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** attempt
                logger.warning(
                    "LLM call transient error, retrying",
                    extra={"status": exc.response.status_code, "attempt": attempt, "wait_s": wait},
                )
                await asyncio.sleep(wait)
                continue
            raise
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < max_retries:
                wait = 2 ** attempt
                logger.warning("LLM call network error, retrying", extra={"error": str(exc), "attempt": attempt})
                await asyncio.sleep(wait)
                continue
            raise

    raise last_exc  # type: ignore[misc]  # unreachable but satisfies type checker


async def chat_stream(
    messages: list[dict[str, str]],
    *,
    model: str,
    temperature: float = 0.7,
    sampling: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    role: str = "default",
    on_first_token: Callable[[float], None] | None = None,
) -> AsyncIterator[str]:
    """
    Stream a chat completion via OpenRouter as Server-Sent Events.
    Yields content deltas (token chunks) as they arrive.

    No retry here — streaming retries are complex (partial output already
    sent). A transient pre-stream failure raises on the first chunk attempt;
    a mid-stream drop surfaces as an error to the caller.

    max_tokens caps the completion length when set (and > 0); None/0 = uncapped.
    """
    s = get_settings()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if sampling:
        payload.update(sampling)
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = max_tokens
    client = await get_http_client()
    url, api_key = _backend(role)
    if s.renderer_base_url and url == s.renderer_base_url and s.renderer_model:
        payload["model"] = s.renderer_model       # provider's model id (see chat())
    headers = {"Authorization": f"Bearer {api_key}"}
    if url == _OPENROUTER_URL:
        headers["HTTP-Referer"] = s.http_referer
        headers["X-Title"] = s.app_title

    t0 = time.perf_counter()
    first_ts: float | None = None
    completion_chars = 0
    async with client.stream(
        "POST", url, headers=headers, json=payload
    ) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line or not line.startswith("data: "):
                continue
            data_str = line[len("data: "):].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            delta = (
                chunk.get("choices", [{}])[0]
                .get("delta", {})
                .get("content")
            )
            if delta:
                if first_ts is None:  # time-to-first-token (TTFT) — the latency gate
                    first_ts = time.perf_counter()
                    if on_first_token is not None:
                        on_first_token(first_ts)
                completion_chars += len(delta)
                yield delta

    logger.info(
        "llm_stream_call",
        extra={
            "model": model,
            "completion_chars": completion_chars,
            "ttft_ms": int((first_ts - t0) * 1000) if first_ts else None,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        },
    )
