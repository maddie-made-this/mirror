import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession, AsyncTransaction

from core.settings import get_settings

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None

# Constraints and indexes applied on startup. All statements are idempotent
# (IF NOT EXISTS), so re-running them on every boot is safe and cheap.
_SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT node_unique IF NOT EXISTS "
    "FOR (n:Node) REQUIRE (n.id, n.user_id) IS UNIQUE",
    "CREATE CONSTRAINT mention_unique IF NOT EXISTS "
    "FOR (m:Mention) REQUIRE (m.id, m.user_id) IS UNIQUE",
    "CREATE INDEX node_user IF NOT EXISTS FOR (n:Node) ON (n.user_id)",
    "CREATE INDEX node_entity_type IF NOT EXISTS FOR (n:Node) ON (n.entity_type)",
    "CREATE INDEX node_last_session IF NOT EXISTS FOR (n:Node) ON (n.last_session)",
    "CREATE INDEX node_mention_count IF NOT EXISTS FOR (n:Node) ON (n.mention_count)",
    "CREATE INDEX mention_user IF NOT EXISTS FOR (m:Mention) ON (m.user_id)",
    "CREATE INDEX mention_created IF NOT EXISTS FOR (m:Mention) ON (m.created_at)",
    "CREATE INDEX mention_session IF NOT EXISTS FOR (m:Mention) ON (m.session_number)",
    # Cluster tier + interpretation layer.
    "CREATE CONSTRAINT cluster_unique IF NOT EXISTS "
    "FOR (c:Cluster) REQUIRE (c.id, c.user_id) IS UNIQUE",
    "CREATE CONSTRAINT interpretation_unique IF NOT EXISTS "
    "FOR (i:Interpretation) REQUIRE (i.id, i.user_id) IS UNIQUE",
    "CREATE INDEX node_cluster IF NOT EXISTS FOR (n:Node) ON (n.cluster_id)",
    "CREATE INDEX interpretation_status IF NOT EXISTS "
    "FOR (i:Interpretation) ON (i.status)",
]


async def init_driver() -> None:
    global _driver
    s = get_settings()
    _driver = AsyncGraphDatabase.driver(
        s.neo4j_uri,
        auth=(s.neo4j_user, s.neo4j_password),
    )
    await _driver.verify_connectivity()

    async with _driver.session() as session:
        for stmt in _SCHEMA_STATEMENTS:
            try:
                await session.run(stmt)
            except Exception:
                logger.warning("Schema statement failed", extra={"statement": stmt})


async def close_driver() -> None:
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if not _driver:
        raise RuntimeError("Neo4j driver not initialised — call init_driver() at startup")
    async with _driver.session() as session:
        yield session


@asynccontextmanager
async def get_tx() -> AsyncGenerator[AsyncTransaction, None]:
    """
    Yield an explicit transaction. Commits on clean exit, rolls back on any
    exception. Used to make a multi-write proposition ingest atomic.
    """
    if not _driver:
        raise RuntimeError("Neo4j driver not initialised — call init_driver() at startup")
    async with _driver.session() as session:
        tx = await session.begin_transaction()
        try:
            yield tx
            await tx.commit()
        except Exception:
            await tx.rollback()
            raise
