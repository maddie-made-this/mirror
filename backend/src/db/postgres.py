import json

import asyncpg

from core.settings import get_settings

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Encode/decode json + jsonb columns transparently as Python objects."""
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def init_pool() -> None:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=s.supabase_db_url,
            min_size=1,
            max_size=10,
            init=_init_connection,
        )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_pool() -> asyncpg.Pool:
    if _pool is None:
        await init_pool()
    assert _pool is not None  # init_pool always assigns it
    return _pool
