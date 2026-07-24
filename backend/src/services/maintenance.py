"""
Background maintenance pipeline.

Clustering, interpretation reflection, and bridge detection must run OFF the
request path, periodically — they are too slow to run inline and benefit from
seeing a batch of new nodes at once. This module owns:

  * a lightweight per-user "dirty" marker (set when a user accrues new graph
    writes), so the periodic job skips idle users, and
  * the per-user pipeline: cluster -> interpret -> detect_bridges.

The marker is in-process (a set). That is correct for the current single-
instance backend; a multi-instance deploy would promote it to a Postgres column
or a Neo4j property (`last_clustered_session`). The scheduler that drives this
is started in the FastAPI lifespan (see main.py).
"""

import logging
from uuid import UUID

logger = logging.getLogger(__name__)

# user_id (str) -> dirty. A set is enough; we only need membership.
_dirty_users: set[str] = set()


def mark_user_dirty(user_id: UUID | str) -> None:
    """Flag a user for reprocessing on the next pipeline tick."""
    _dirty_users.add(str(user_id))


def dirty_count() -> int:
    return len(_dirty_users)


async def run_pipeline_once() -> None:
    """
    Drain the dirty set and run the per-user pipeline for each. Called by the
    scheduler on an interval. A user whose pipeline raises is re-queued so a
    transient failure doesn't silently drop their reprocessing.
    """
    if not _dirty_users:
        return

    batch = list(_dirty_users)
    _dirty_users.clear()
    logger.info("maintenance_pipeline_tick", extra={"users": len(batch)})

    for uid_str in batch:
        try:
            await _run_user_pipeline(UUID(uid_str))
        except Exception:
            logger.exception(
                "maintenance pipeline failed for user; re-queued",
                extra={"user_id": uid_str},
            )
            _dirty_users.add(uid_str)


async def _run_user_pipeline(user_id: UUID) -> None:
    """
    cluster -> interpret -> detect_bridges. Each stage is optional and guarded so
    the pipeline degrades gracefully while the workstreams are built out
    incrementally — a stage that isn't implemented yet is simply skipped.
    """
    # --- Clustering (Workstream 2C) ---
    try:
        from services import clustering
    except ImportError:
        clustering = None
    if clustering is not None:
        await clustering.cluster_user(user_id)

    # --- relates_to similarity pass (cross-community embedding kin) ---
    try:
        from services import relations
    except ImportError:
        relations = None
    if relations is not None:
        await relations.relates_to_pass(user_id)

    # --- Inter-community semantic attraction (§3A): centroid cosine adjacency ---
    try:
        from services import cluster_similarity
    except ImportError:
        cluster_similarity = None
    if cluster_similarity is not None:
        await cluster_similarity.compute_cluster_similarity(user_id)

    # --- Tier-2 angle matching (three-tier engine model §2) ---
    # After clustering (clusters are the matcher's input); before bridges (independent
    # but reading the same graph state). Classifies each cluster into a curated angle.
    try:
        from services import tier_2_matcher
    except ImportError:
        tier_2_matcher = None
    if tier_2_matcher is not None and hasattr(tier_2_matcher, "match_clusters"):
        await tier_2_matcher.match_clusters(user_id)

    # --- Interpretation reflection (Workstream 3) ---
    try:
        from services import interpretation
    except ImportError:
        interpretation = None
    if interpretation is not None and hasattr(interpretation, "reflect_user"):
        await interpretation.reflect_user(user_id)

    # --- Motif readings (interest-model §3): per-motif function/origin/belief ---
    if interpretation is not None and hasattr(interpretation, "reflect_motifs"):
        await interpretation.reflect_motifs(user_id)

    # --- Synthesized node headlines (producer C3b): a SHORT summary of each node's
    # readings, stored on the node, so get_node_readings serves a synthesis not a copy.
    if interpretation is not None and hasattr(interpretation, "synthesize_node_headlines"):
        await interpretation.synthesize_node_headlines(user_id)

    # --- Bridge detection (Workstream 4) ---
    try:
        from services import bridges
    except ImportError:
        bridges = None
    if bridges is not None and hasattr(bridges, "detect_user_bridges"):
        await bridges.detect_user_bridges(user_id)

    # --- Interest-model background passes (§2.2, §3, §4, §5) ---
    # Each independent and guarded: aversions from hard boundaries, the
    # consolidation rule, prediction-engine candidates, slow trait accumulation.
    try:
        from services import gates
        await gates.derive_aversions_from_boundaries(user_id)
        # The one path that moves an excluded_topic: the user's own explicit reversal.
        await gates.revoke_aversions_on_explicit_reversal(user_id)
    except Exception:
        logger.exception("excluded_topic maintenance failed", extra={"user_id": str(user_id)})

    try:
        from services import consolidation
        await consolidation.consolidate_user(user_id)
    except Exception:
        logger.exception("consolidation failed", extra={"user_id": str(user_id)})

    try:
        from services import prediction
        await prediction.generate_function_candidates(user_id)
        await prediction.generate_similarity_candidates(user_id)
    except Exception:
        logger.exception("candidate generation failed", extra={"user_id": str(user_id)})

    try:
        from services import dynamics
        await dynamics.update_traits(user_id)
    except Exception:
        logger.exception("trait update failed", extra={"user_id": str(user_id)})


async def enqueue_all_users() -> int:
    """
    Mark every user that has graph data as dirty. Used on startup so a restart
    recomputes clusters/interpretations/bridges (picking up code/prompt changes)
    rather than serving stale stored results.
    """
    from db.neo4j import get_session

    async with get_session() as session:
        result = await session.run(
            "MATCH (n:Node) WHERE n.user_id IS NOT NULL RETURN DISTINCT n.user_id AS uid"
        )
        uids = [r["uid"] async for r in result if r["uid"]]
    for uid in uids:
        _dirty_users.add(str(uid))
    logger.info("enqueued_all_users_for_maintenance", extra={"users": len(uids)})
    return len(uids)


async def recompute_all_users() -> None:
    """
    Startup recompute: enqueue every user and run the pipeline once now. Runs as a
    background task off the lifespan so it never blocks startup; failures are logged,
    not fatal. The periodic scheduler then keeps things fresh as users chat.
    """
    try:
        if await enqueue_all_users():
            await run_pipeline_once()
    except Exception:
        logger.exception("startup recompute failed")
