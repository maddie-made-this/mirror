"""
Process-level background worker that takes extraction + the graph-mutation tail
OFF the response critical path (Architecture & Orchestration, Change 1).

Why this is safe: a turn's reply is generated from the graph as it stood BEFORE the
turn — a turn's own content can't inform its own reply — so extraction only ever
serves FUTURE turns. Running it after the reply costs the current turn nothing, and
because the worker drains continuously, new nodes land in the UI within seconds (the
"insights sooner" payoff), not next session. Steering on a slightly-stale graph
degrades gracefully.

Dev: an in-process asyncio.Queue drained by a single worker task started in the
FastAPI lifespan. Prod: swap enqueue()/the worker for a real task queue (ARQ/Celery)
— keep enqueue() identical so the swap is config, not a rewrite.

The unit of work is one user turn's post-reply pipeline, in order:
    extract_propositions → ingest_propositions → uptake.judge_pending
    → recluster → uptake.record_offer
A single FIFO consumer is load-bearing: it preserves the cross-turn invariant that a
turn records its OWN offer only AFTER it has judged the PRIOR turns' offers (turn N's
record_offer completes before turn N+1's judge_pending runs).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from uuid import UUID

logger = logging.getLogger(__name__)

# How many freshly-touched node ids to remember per user for the UI indicator.
_RECENT_CAP = 50


@dataclass
class ExtractionJob:
    """One turn's worth of off-path work. Carries the graph context as it stood
    BEFORE the turn (relevant_nodes) plus everything ingest/uptake need."""

    user_id: UUID
    conversation_id: UUID
    message_id: UUID
    session_number: int
    message: str
    relevant_nodes: list = field(default_factory=list)   # list[GraphNode]
    active_predicates: list = field(default_factory=list)
    active_node_ids: list = field(default_factory=list)
    display_name: str = "Me"
    self_node_id: str | None = None
    depth_ramp: str = ""
    clearly_engaged: bool = True
    # This turn's steering probe (recorded as an offer for the NEXT turn to judge).
    steer: dict | None = None


# Module-level singleton state (one worker per process).
_queue: "asyncio.Queue[ExtractionJob] | None" = None
_worker: "asyncio.Task | None" = None
_pending: dict[str, int] = {}            # user_id -> queued + in-flight job count
_recent: dict[str, deque] = {}           # user_id -> recently-touched node ids


def _ensure_queue() -> "asyncio.Queue[ExtractionJob]":
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


async def enqueue(job: ExtractionJob) -> None:
    """Add one turn's post-reply pipeline to the background queue. Returns at once —
    the response path never waits on extraction."""
    uid = str(job.user_id)
    _pending[uid] = _pending.get(uid, 0) + 1
    _ensure_queue().put_nowait(job)


def processing_status(user_id: UUID) -> dict:
    """The visible-queue payload for GET /{user_id}/processing: how many turns are
    still being processed for this user, and the nodes that recently landed."""
    uid = str(user_id)
    return {
        "pending": _pending.get(uid, 0),
        "recently_added_node_ids": list(_recent.get(uid, ())),
    }


def _note_touched(user_id: str, node_ids) -> None:
    if not node_ids:
        return
    dq = _recent.setdefault(user_id, deque(maxlen=_RECENT_CAP))
    for nid in node_ids:
        dq.appendleft(nid)


async def _process(job: ExtractionJob) -> None:
    # Deferred imports: keep the module import-light and dodge any service cycles.
    from services import recluster, uptake
    from services.extraction import extract_propositions, ingest_propositions

    props = await extract_propositions(
        job.message,
        job.relevant_nodes,
        job.active_predicates,
        conversation_id=job.conversation_id,
        message_id=job.message_id,
    )
    ingest = await ingest_propositions(
        props,
        job.user_id,
        job.session_number,
        job.active_node_ids,
        user_display_name=job.display_name,
        self_node_id=job.self_node_id,
        depth_ramp=job.depth_ramp,
    )
    touched_node_ids = ingest[5]  # (created, updated, e_created, e_updated, skipped, touched)

    # Uptake: judge PRIOR turns' offers against this message (needs touched_node_ids),
    # BEFORE recording this turn's own offer below.
    try:
        await uptake.judge_pending(
            job.user_id, job.conversation_id, job.message,
            set(touched_node_ids), job.clearly_engaged,
        )
    except Exception:
        logger.exception("uptake judging failed (worker)")

    # Periodic recluster check — log-only for now; identifies split candidates.
    for nid in touched_node_ids:
        try:
            await recluster.maybe_recluster_node(nid, job.user_id)
        except Exception:
            logger.exception("recluster check failed (worker)", extra={"node_id": nid})

    # Record this turn's probe as an offer — the user's NEXT message judges it.
    if job.steer and job.steer.get("element"):
        try:
            await uptake.record_offer(
                job.user_id, job.conversation_id, job.message_id,
                job.steer["element"], job.steer["tag"],
                node_id=job.steer.get("node_id"),
                interpretation_id=job.steer.get("interpretation_id"),
            )
        except Exception:
            logger.exception("offer recording failed (worker)")

    _note_touched(str(job.user_id), touched_node_ids)


async def _run_worker() -> None:
    q = _ensure_queue()
    logger.info("extraction worker started")
    while True:
        job = await q.get()
        try:
            await _process(job)
        except Exception:
            logger.exception(
                "extraction job failed", extra={"message_id": str(job.message_id)}
            )
        finally:
            uid = str(job.user_id)
            _pending[uid] = max(0, _pending.get(uid, 1) - 1)
            if _pending[uid] == 0:
                _pending.pop(uid, None)
            q.task_done()


def start_worker() -> "asyncio.Task":
    """Idempotently start the single drain worker (called from the FastAPI lifespan)."""
    global _worker
    if _worker is None or _worker.done():
        _ensure_queue()
        _worker = asyncio.create_task(_run_worker())
    return _worker


async def stop_worker() -> None:
    """Cancel the worker on shutdown. Jobs still queued are dropped — idempotent
    extraction means a re-run on next startup is harmless, but dev shutdowns are
    rare enough that this is fine."""
    global _worker
    if _worker is not None:
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("extraction worker shutdown error")
        _worker = None
