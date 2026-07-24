"""
Tier-2 angle matcher (three-tier engine model §3).

Classifies each of a user's clusters into ONE entry of the curated angle
vocabulary (services/angle_vocabulary.py) — the felt character the cluster takes
for THIS user ("what kind of pull this is") — and persists it as an
:Interpretation {kind:'angle'}.

The honesty property: the LLM makes a CLASSIFICATION CHOICE from a finite list.
It never generates psychology and never produces free text. Every persisted angle
carries an `angle_key` that is validated to exist in the vocabulary file; an LLM
key that isn't in the vocabulary is treated as NO_MATCH and logged as a
vocabulary-expansion candidate. The failure mode is "wrong choice from N angles"
— auditable, testable, recoverable — never fluent confabulation.

Wired into the maintenance pipeline AFTER clustering, BEFORE bridge detection.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from config.loader import APP_CONFIG
from db.neo4j import get_session
from llm.client import chat
from schemas.interpretation import Interpretation, InterpretationKind
from services import angle_vocabulary
from services.interpretation import _strip_fence, save_interpretation

logger = logging.getLogger(__name__)

# Sub-thresholds and constants — all module-level, easy to tune.
_MIN_CLUSTER_SIZE = 3          # firing threshold; below this tier-2 doesn't fire
_MENTIONS_PER_NODE = 12        # spec constant; applied as a cluster-total bound below
_MENTIONS_CAP_PER_CLUSTER = _MENTIONS_PER_NODE * 2   # bounds the matcher prompt size
_ANGLE_STALENESS_DAYS = 14
_MAX_CLUSTERS_PER_RUN = 8      # mirrors interpretation._MAX_CLUSTERS_PER_RUN
_CONFIDENCE_FLOOR = 0.4        # mirrors APP_CONFIG.reading_confidence_floor
_CONFIDENCE_CEIL = 0.9
_FETCH_CLUSTER_LIMIT = 50      # cap the candidate scan; filtered + capped to _MAX in Python
_ANGLE_MEMBER_OVERLAP_THRESHOLD = 0.6   # churn fix: "same angle" when member-overlap >= this


_MATCHER_SYSTEM = (
    "You are matching a user's cluster of related interests to a psychological angle "
    "from a curated vocabulary. The vocabulary is fixed; your job is to pick the "
    "single best match.\n\n"
    "Do NOT invent angles. Do NOT psychologize the user. Do NOT propose new "
    "categories. If no vocabulary entry fits well, return \"NO_MATCH\" — that is a "
    "normal result, not a failure.\n\n"
    "You are choosing the angle that names WHY these interests are compelling for THIS "
    "user, based on which trigger phrasings appear in their actual words and which "
    "related concepts appear in their cluster. The angle is the felt character of their "
    "cluster, not a psychological function (do not produce function-level claims — "
    "that's a different layer).\n\n"
    "Return JSON only: {\"angle_key\": \"<key from vocabulary>\" | \"NO_MATCH\", "
    "\"matched_evidence\": \"<one sentence citing the user's words and which trigger "
    "phrasings or related concepts supported the match>\", "
    "\"confidence\": <float 0.4-0.9>}."
)


def _vocabulary_block() -> str:
    """Serialize the full vocabulary for the matcher prompt (the LLM picks from this)."""
    lines: list[str] = []
    for e in angle_vocabulary.all_angles():
        lines.append(
            f"- key: {e.key}\n"
            f"  name: {e.name}\n"
            f"  definition: {e.definition}\n"
            f"  distinct from neighbors: {e.felt_distinction_from_neighbors}\n"
            f"  trigger phrasings: {'; '.join(e.trigger_phrasings)}\n"
            f"  related concepts: {', '.join(e.related_concepts)}"
        )
    return "\n".join(lines)


def _is_stale(updated_at_iso: str | None, now: datetime) -> bool:
    """True if the angle is older than the staleness window (or its timestamp is
    unparseable, in which case we conservatively re-match)."""
    if not updated_at_iso:
        return True
    try:
        ts = datetime.fromisoformat(str(updated_at_iso))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return True
    return (now - ts) > timedelta(days=_ANGLE_STALENESS_DAYS)


async def _candidate_clusters(user_id: UUID) -> list[dict]:
    """
    Clusters with >= _MIN_CLUSTER_SIZE members, each with its member ids/names, a
    bounded recent-mention sample, and its existing (non-rejected) angle interp if
    any (id / key / updated_at) — so the caller can filter to clusters that lack an
    angle or whose angle has gone stale.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (c:Cluster {user_id: $uid})<-[:IN_CLUSTER]-(n:Node)
            OPTIONAL MATCH (m:Mention {user_id: $uid})-[:REFERENCES]->(n)
            WITH c, n, m ORDER BY m.created_at DESC
            WITH c,
                 collect(DISTINCT n.id)   AS node_ids,
                 collect(DISTINCT n.name) AS names,
                 collect(DISTINCT m.text)[..$mlimit] AS mentions
            WHERE size(node_ids) >= $min_size
            OPTIONAL MATCH (ai:Interpretation {user_id: $uid})
              WHERE ai.kind = 'angle' AND ai.status <> 'rejected'
                AND c.id IN coalesce(ai.attached_cluster_ids, [])
            WITH c, node_ids, names, mentions, ai ORDER BY ai.updated_at DESC
            WITH c, node_ids, names, mentions, head(collect(ai)) AS angle
            RETURN c.id AS cid, c.label AS label, node_ids, names, mentions,
                   angle.id AS angle_id, angle.angle_key AS angle_key,
                   angle.updated_at AS angle_updated_at
            ORDER BY size(node_ids) DESC
            LIMIT $fetch_limit
            """,
            uid=str(user_id),
            mlimit=_MENTIONS_CAP_PER_CLUSTER,
            min_size=_MIN_CLUSTER_SIZE,
            fetch_limit=_FETCH_CLUSTER_LIMIT,
        )
        rows = [dict(r) async for r in result]
        for row in rows:
            row["user_id"] = str(user_id)   # carried for the miss-log curation context
        return rows


def _log_miss(c: dict, reason: str, **extra) -> None:
    """The curation queue: a structured miss line driving vocabulary growth."""
    logger.info(
        "angle_match_misses",
        extra={
            "reason": reason,
            "user_id": c.get("user_id"),
            "cluster_id": c.get("cid"),
            "member_names": [n for n in (c.get("names") or []) if n][:12],
            "mention_sample": [m for m in (c.get("mentions") or []) if m][:5],
            **extra,
        },
    )


async def _classify_cluster(c: dict) -> tuple[str, str, float] | None:
    """
    LLM-classify a cluster into a vocabulary key. Returns (angle_key, evidence,
    confidence) on a VALID in-vocabulary match, or None on NO_MATCH / invalid key
    / parse failure (each logged appropriately).
    """
    names = [n for n in (c.get("names") or []) if n]
    mentions = [m for m in (c.get("mentions") or []) if m]
    user_content = (
        f"Cluster theme: {c.get('label') or 'unlabeled'}\n"
        f"Concepts in this cluster: {', '.join(names[:30])}\n"
        f"Verbatim things the user said:\n"
        + "\n".join(f"- {m}" for m in mentions[:_MENTIONS_CAP_PER_CLUSTER])
        + "\n\nThe curated angle vocabulary (pick exactly one key, or NO_MATCH):\n"
        + _vocabulary_block()
    )
    try:
        raw = await chat(
            [
                {"role": "system", "content": _MATCHER_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            model=APP_CONFIG.matcher_model_resolved,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(_strip_fence(raw))
    except Exception:
        logger.warning("angle matcher parse failure", extra={"cluster_id": c.get("cid")})
        return None
    if not isinstance(data, dict):
        return None

    key = (data.get("angle_key") or "").strip()
    evidence = (data.get("matched_evidence") or "").strip()
    try:
        conf = float(data.get("confidence", 0.6))
    except (TypeError, ValueError):
        conf = 0.6
    conf = min(max(conf, _CONFIDENCE_FLOOR), _CONFIDENCE_CEIL)

    if key == "NO_MATCH" or not key:
        _log_miss(c, "no_match")
        return None
    # Audit-trail enforcement: an LLM key not in the vocabulary cannot persist. Warn
    # loudly (separate from the INFO miss line) so a model hallucinating vocabulary is
    # easy to spot in monitoring.
    if angle_vocabulary.get_angle(key) is None:
        logger.warning(
            "angle_matcher_invalid_key",
            extra={"cluster_id": c.get("cid"), "invalid_key": key},
        )
        _log_miss(c, "invalid_key", invalid_key=key)
        return None
    return key, evidence, conf


def _select_best_overlap(
    member_node_ids: list[str],
    candidates: list[Interpretation],
    threshold: float,
) -> Interpretation | None:
    """
    Pure: of `candidates`, return the one whose attached_node_ids overlap
    `member_node_ids` by >= threshold, highest-overlap wins; None if none clear it.
    overlap = |new ∩ existing| / max(|new|, |existing|). Extracted from
    _find_existing_angle so the overlap rule is unit-testable without a Neo4j round-trip.
    """
    new_set = {n for n in member_node_ids if n}
    if not new_set:
        return None
    best: tuple[float, Interpretation] | None = None
    for c in candidates:
        existing_set = {n for n in (c.attached_node_ids or []) if n}
        if not existing_set:
            continue
        overlap = len(new_set & existing_set) / max(len(new_set), len(existing_set))
        if overlap >= threshold and (best is None or overlap > best[0]):
            best = (overlap, c)
    return best[1] if best else None


async def _find_existing_angle(
    user_id: UUID,
    angle_key: str,
    member_node_ids: list[str],
    overlap_threshold: float = _ANGLE_MEMBER_OVERLAP_THRESHOLD,
) -> Interpretation | None:
    """
    A non-rejected :Interpretation{kind:'angle'} for this user with the SAME angle_key
    whose attached_node_ids overlap the candidate member set by >= overlap_threshold
    (best match wins), or None.

    Stable-identity dedup: this replaces the cluster-id-keyed lookup that churned each
    run when clustering re-IDed clusters — node ids are canonical slugs and survive,
    cluster ids are a per-run membership hash and don't. Same root cause + fix shape as
    the bridge-churn dedup in services/bridges.py.
    """
    if not member_node_ids:
        return None
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid, kind: 'angle', angle_key: $key})
            WHERE coalesce(i.status, 'candidate') <> 'rejected'
            RETURN i
            """,
            uid=str(user_id),
            key=angle_key,
        )
        candidates: list[Interpretation] = []
        async for r in result:
            try:
                candidates.append(Interpretation(**dict(r["i"])))
            except Exception:
                continue   # a row that won't reconstruct must never block the match
    return _select_best_overlap(member_node_ids, candidates, overlap_threshold)


async def _update_angle_attachments(
    interp_id: str,
    new_cluster_ids: list[str],
    new_node_ids: list[str],
    new_confidence: float,
) -> None:
    """
    Re-point an existing angle at the current cluster id + member set and refresh
    confidence/updated_at. Used when stable-identity dedup matches a freshly-classified
    cluster to an angle whose cluster_id was regenerated. Status is deliberately left
    untouched — the matched angle is already non-rejected, and re-pointing must not
    clobber a user affirm/qualify. (The spec sketched status='active'; that isn't a
    valid InterpretationStatus and would downgrade interacted readings, so we omit it.)
    """
    async with get_session() as session:
        await session.run(
            """
            MATCH (i:Interpretation {id: $id})
            SET i.attached_cluster_ids = $cluster_ids,
                i.attached_node_ids = $node_ids,
                i.confidence = $conf,
                i.updated_at = $now
            """,
            id=interp_id,
            cluster_ids=new_cluster_ids,
            node_ids=new_node_ids,
            conf=new_confidence,
            now=datetime.now(timezone.utc).isoformat(),
        )


async def _prune_orphan_angles(user_id: UUID) -> int:
    """
    Mark as 'rejected' any non-rejected angle whose attached_cluster_ids no longer
    resolve to a live :Cluster AND fewer than 3 of its attached_node_ids are still
    clustered. Reject (not delete) to keep the audit trail; runs once per match pass.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid, kind: 'angle'})
            WHERE coalesce(i.status, 'candidate') <> 'rejected'
            OPTIONAL MATCH (c:Cluster {user_id: $uid})
              WHERE c.id IN coalesce(i.attached_cluster_ids, [])
            WITH i, count(c) AS live_clusters
            OPTIONAL MATCH (n:Node {user_id: $uid})
              WHERE n.id IN coalesce(i.attached_node_ids, [])
                AND n.cluster_id IS NOT NULL
            WITH i, live_clusters, count(n) AS live_clustered_nodes
            WHERE live_clusters = 0 AND live_clustered_nodes < 3
            SET i.status = 'rejected',
                i.rejected_reason = 'orphaned: cluster regenerated, members no longer co-clustered',
                i.updated_at = $now
            RETURN count(i) AS pruned
            """,
            uid=str(user_id),
            now=datetime.now(timezone.utc).isoformat(),
        )
        row = await result.single()
        return int(row["pruned"]) if row else 0


async def _reject_superseded_angles(
    user_id: UUID,
    overlap_threshold: float = _ANGLE_MEMBER_OVERLAP_THRESHOLD,
) -> int:
    """
    Reject a DANGLING angle (none of its attached_cluster_ids resolves to a live
    :Cluster) when a LIVE same-key angle already subsumes its members (overlap >=
    threshold). This clears the duplicate the orphan-prune deliberately keeps: pre-fix
    churn left re-IDed-cluster angles whose members later migrated into a cluster that
    now holds its own current-id angle — so the old one is dead, but its members still
    cluster, so _prune_orphan_angles won't touch it. Reject (keep the audit trail).
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid, kind: 'angle'})
            WHERE coalesce(i.status, 'candidate') <> 'rejected'
            OPTIONAL MATCH (c:Cluster {user_id: $uid})
              WHERE c.id IN coalesce(i.attached_cluster_ids, [])
            WITH i, count(c) AS live_clusters
            RETURN i.id AS id, i.angle_key AS key,
                   coalesce(i.attached_node_ids, []) AS members, live_clusters
            """,
            uid=str(user_id),
        )
        rows = [dict(r) async for r in result]

    live_by_key: dict[str, list[set]] = {}
    dangling: list[dict] = []
    for r in rows:
        members = {n for n in (r.get("members") or []) if n}
        if r["live_clusters"] > 0:
            live_by_key.setdefault(r["key"], []).append(members)
        else:
            dangling.append({"id": r["id"], "key": r["key"], "members": members})

    to_reject: list[str] = []
    for d in dangling:
        if not d["members"]:
            continue
        for live_members in live_by_key.get(d["key"], []):
            if not live_members:
                continue
            overlap = len(d["members"] & live_members) / max(len(d["members"]), len(live_members))
            if overlap >= overlap_threshold:
                to_reject.append(d["id"])
                break

    if to_reject:
        async with get_session() as session:
            await session.run(
                """
                MATCH (i:Interpretation {user_id: $uid})
                WHERE i.id IN $ids
                SET i.status = 'rejected',
                    i.rejected_reason = 'superseded: a live same-key angle subsumes these members',
                    i.updated_at = $now
                """,
                uid=str(user_id), ids=to_reject,
                now=datetime.now(timezone.utc).isoformat(),
            )
    return len(to_reject)


async def _reject_interp(user_id: UUID, interp_id: str) -> None:
    """Retire a superseded angle (the new match's key differs from the old)."""
    async with get_session() as session:
        await session.run(
            """
            MATCH (i:Interpretation {id: $iid, user_id: $uid})
            SET i.status = 'rejected', i.updated_at = $now
            """,
            iid=interp_id, uid=str(user_id),
            now=datetime.now(timezone.utc).isoformat(),
        )


async def match_clusters(user_id: UUID) -> int:
    """
    For each of the user's clusters that doesn't yet have an angle interpretation
    (or whose angle has aged past staleness), classify it against the curated angle
    vocabulary and persist the resulting :Interpretation of kind='angle'.

    Returns the count of angle interpretations created or refreshed. Runs after
    clustering, before bridge detection (see maintenance.py wiring).
    """
    candidates = await _candidate_clusters(user_id)
    now = datetime.now(timezone.utc)

    todo: list[dict] = []
    for c in candidates:
        if not c.get("angle_key"):
            todo.append(c)                          # never matched
        elif _is_stale(c.get("angle_updated_at"), now):
            todo.append(c)                          # stale → re-match
    todo = todo[:_MAX_CLUSTERS_PER_RUN]
    # NB: no early return on empty `todo` — the orphan-prune below must run every pass
    # (a cluster can dissolve, orphaning its angle, even when nothing new matches).

    created = 0
    refreshed = 0
    for c in todo:
        match = await _classify_cluster(c)
        if match is None:
            continue
        key, evidence, conf = match
        entry = angle_vocabulary.get_angle(key)
        if entry is None:                           # defensive; validated above
            continue

        member_ids = [n for n in (c.get("node_ids") or []) if n]
        old_id = c.get("angle_id")
        old_key = c.get("angle_key")

        # Stable-identity dedup (churn fix): an existing same-key angle whose member
        # set still overlaps survives cluster-id regeneration — re-point it in place
        # instead of minting a duplicate.
        existing = await _find_existing_angle(user_id, key, member_ids)
        if existing is not None:
            await _update_angle_attachments(str(existing.id), [c["cid"]], member_ids, conf)
            # A *different-key* angle still pinned to this cluster's current id is
            # superseded — retire it (unless it's the very one we just refreshed).
            if old_id and old_key and old_key != key and str(existing.id) != old_id:
                await _reject_interp(user_id, old_id)
            logger.info(
                "tier_2_angle_refreshed",
                extra={
                    "user_id": str(user_id),
                    "interp_id": str(existing.id),
                    "angle_key": key,
                    "old_cluster_ids": existing.attached_cluster_ids,
                    "new_cluster_id": c["cid"],
                },
            )
            refreshed += 1
            continue

        # Genuinely new angle (no same-key overlapping match). Retire any different-key
        # angle still pinned to this cluster's current id.
        if old_id and old_key and old_key != key:
            await _reject_interp(user_id, old_id)
        interp = Interpretation(
            user_id=user_id,
            statement=entry.name,                   # readable label, no separate fetch
            kind=InterpretationKind.ANGLE,
            angle_key=entry.key,                    # the audit trail
            inferential_step=evidence,              # why this angle was chosen
            what_would_change_this=entry.felt_distinction_from_neighbors,  # falsifier = neighbor
            attached_cluster_ids=[c["cid"]],
            attached_node_ids=member_ids,
            confidence=conf,
        )
        await save_interpretation(interp)
        created += 1

    if created:
        logger.info(
            "angle_interpretations_matched",
            extra={"user_id": str(user_id), "count": created},
        )

    pruned = await _prune_orphan_angles(user_id)
    if pruned:
        logger.info(
            "tier_2_angles_pruned",
            extra={"user_id": str(user_id), "count": pruned},
        )

    superseded = await _reject_superseded_angles(user_id)
    if superseded:
        logger.info(
            "tier_2_angles_superseded",
            extra={"user_id": str(user_id), "count": superseded},
        )

    return created + refreshed
