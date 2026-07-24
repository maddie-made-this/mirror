import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.v1.router import router
from core.errors import register_exception_handlers
from core.logging import configure_logging, request_id_var
from core.rate_limit import limiter
from core.settings import get_settings
from db.neo4j import close_driver, init_driver
from db.postgres import close_pool, init_pool
from db.qdrant import close_client, init_client
from llm.client import close_http_client
from services import extraction_queue
from services.maintenance import recompute_all_users, run_pipeline_once

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    await init_driver()
    await init_client()
    await init_pool()

    # Extraction worker (Change 1): a continuous background consumer that drains the
    # extract → ingest → uptake → recluster pipeline OFF the response critical path,
    # so reply latency no longer varies with extraction and new nodes land in seconds.
    extraction_queue.start_worker()

    # Background maintenance pipeline (clustering/interpretation/bridges). In
    # process via APScheduler — simplest for a single-instance backend; ARQ/Celery
    # are the scale-up path. Skips idle users via the dirty marker.
    s = get_settings()
    scheduler = None
    if s.enable_scheduler:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            run_pipeline_once,
            "interval",
            seconds=s.maintenance_interval_seconds,
            id="user_maintenance_pipeline",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info(
            "maintenance scheduler started",
            extra={"interval_s": s.maintenance_interval_seconds},
        )
    app.state.scheduler = scheduler

    # Recompute clusters/interpretations/bridges for every user once on startup so a
    # restart applies code/prompt changes. Background task — never blocks startup.
    app.state.recompute_task = None
    if s.recompute_on_start:
        app.state.recompute_task = asyncio.create_task(recompute_all_users())
        logger.info("startup recompute scheduled")

    yield

    if app.state.recompute_task is not None:
        app.state.recompute_task.cancel()
    if scheduler is not None:
        scheduler.shutdown(wait=False)
    await extraction_queue.stop_worker()
    await close_driver()
    await close_client()
    await close_pool()
    await close_http_client()  # E8: close pooled httpx client on shutdown


def create_app() -> FastAPI:
    app = FastAPI(title="Mirror API", version="0.1.0", lifespan=lifespan)

    s = get_settings()

    # A3: CORS origins driven by environment variable, never hardcoded.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in s.allowed_origins.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # F1: rate limiting.
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # G2: attach a correlation ID to every request and echo it in the response.
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[return]
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    register_exception_handlers(app)
    app.include_router(router)

    return app


app = create_app()
