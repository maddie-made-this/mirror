"""
Gates (build_interest_model.md §3, §6) — Excluded and Sensitive, with their distinct
lifecycles enforced HERE, in code, not by the caller's discipline:

- Aversions are created from explicit hard boundaries. The ENGINE has no path to
  move one — no probe, no test, no decay, and no uptake-lift (nothing is ever
  offered against an excluded_topic to be taken up). The single edge that can move one
  is the USER's own explicit reversal: a later, user-stated, strongly positive
  statement about the region revokes it (history kept, never re-derived). The
  engine never solicits that statement — §7's user-dominance rule cuts both
  ways: only their own words can set or clear one, or the engine ends up contradicting the user with their own past
  words (the §9.2 failure).
- SoftGates are created from selective non-engagement (services/uptake decides
  WHEN; this module just persists), are lifted on positive uptake, and a lifted
  gate leaves history behind (a new one can form later — conditions change).

The asymmetry is deliberate (§6): wrongly gating a neutral element costs nothing;
pushing a real gate costs trust. Err toward gating, never re-test a disengagement
signal to confirm it, and never let a soft gate silently harden into an excluded_topic.
"""
import logging
from datetime import datetime, timezone
from uuid import UUID

from db.neo4j import get_session

logger = logging.getLogger(__name__)

# A boundary node whose valence floor ever reached this is a true negative.
_AVERSION_VALENCE_FLOOR = -0.8

# A reversal must be this positive — mild warmth toward an averted region is
# not a revocation; the asymmetry says err toward keeping the gate.
_REVERSAL_VALENCE = 0.5


def is_explicit_reversal(knowledge_source: str, valence_score: float) -> bool:
    """
    The single edge that can move an excluded_topic: the user's OWN, explicitly stated,
    strongly positive re-approach to the region. LLM-inferred positivity never
    qualifies — only their words, in their voice, can lift it.
    """
    return knowledge_source == "user_stated" and valence_score >= _REVERSAL_VALENCE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def derive_aversions_from_boundaries(user_id: UUID) -> int:
    """
    Maintenance pass: every strongly-negative boundary node gets an :Excluded
    (once). Evidence = its most recent mentions. Returns how many were created.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid, entity_type: 'boundary'})
            WHERE coalesce(n.valence_score_min, 0) <= $floor
              AND NOT EXISTS { MATCH (:Excluded {user_id: $uid, node_id: n.id}) }
            OPTIONAL MATCH (m:Mention {user_id: $uid})-[:REFERENCES]->(n)
            WITH n, collect(m.id)[..5] AS ev
            CREATE (a:Excluded {
                id: randomUUID(), user_id: $uid, node_id: n.id,
                region: n.name, evidence: ev, status: 'active', created_at: $now
            })
            RETURN count(a) AS c
            """,
            uid=str(user_id),
            floor=_AVERSION_VALENCE_FLOOR,
            now=_now(),
        )
        row = await result.single()
        created = int(row["c"]) if row else 0
    if created:
        logger.info("aversions_created", extra={"user_id": str(user_id), "count": created})
    return created


async def revoke_aversions_on_explicit_reversal(user_id: UUID) -> int:
    """
    Maintenance pass: revoke any active excluded_topic whose region the user has
    EXPLICITLY re-approached since the excluded_topic formed — a user-stated mention,
    strongly positive (see is_explicit_reversal), dated after the excluded_topic's
    creation. The row stays (revoked, with the reversal mentions as evidence)
    and is never re-derived: the NOT EXISTS guard in derivation matches revoked
    rows too, so the wall doesn't silently rebuild from the old boundary node.
    Welcome warmly; never relitigate their past statement (§9.2).
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (a:Excluded {user_id: $uid})
            WHERE coalesce(a.status, 'active') = 'active'
              AND a.node_id IS NOT NULL AND a.node_id <> ''
            MATCH (m:Mention {user_id: $uid})-[:REFERENCES]->(n:Node {user_id: $uid})
            WHERE n.id = a.node_id
              AND m.knowledge_source = 'user_stated'
              AND coalesce(m.valence_score, 0) >= $thr
              AND m.created_at > a.created_at
            WITH a, collect(DISTINCT m.id)[..3] AS reversal
            SET a.status = 'revoked', a.revoked_at = $now, a.revoked_by = reversal
            RETURN count(a) AS c
            """,
            uid=str(user_id),
            thr=_REVERSAL_VALENCE,
            now=_now(),
        )
        row = await result.single()
        revoked = int(row["c"]) if row else 0
    if revoked:
        logger.info(
            "aversions_revoked_by_user_reversal",
            extra={"user_id": str(user_id), "count": revoked},
        )
    return revoked


async def create_soft_gate(
    user_id: UUID, node_id: str, element: str, offer_ids: list[str]
) -> None:
    """
    Persist a soft gate for (user, node). Idempotent: an existing ACTIVE gate just
    accumulates evidence; a lifted gate stays lifted and a fresh one is created —
    conditions may have changed since, and the history matters.
    """
    async with get_session() as session:
        await session.run(
            """
            MERGE (g:Sensitive {user_id: $uid, node_id: $nid, status: 'active'})
            ON CREATE SET g.id = randomUUID(), g.element = $el,
                          g.evidence_offer_ids = $ev, g.created_at = $now
            ON MATCH SET g.evidence_offer_ids =
                g.evidence_offer_ids + [x IN $ev WHERE NOT x IN g.evidence_offer_ids]
            """,
            uid=str(user_id),
            nid=node_id,
            el=element,
            ev=[str(i) for i in offer_ids],
            now=_now(),
        )
    logger.info(
        "soft_gate_set",
        extra={"user_id": str(user_id), "node_id": node_id, "element": element[:80]},
    )


async def lift_soft_gate(user_id: UUID, node_id: str) -> int:
    """
    Positive uptake on a gated element: the gate was a CONDITION reading and the
    condition changed. Lift it (keep the row — it documents the journey). The
    caller's response posture: welcome warmly, never contradict the user with
    their past statement (acceptance test §9.2). Aversions have no lift path.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (g:Sensitive {user_id: $uid, node_id: $nid, status: 'active'})
            SET g.status = 'lifted', g.lifted_at = $now
            RETURN count(g) AS c
            """,
            uid=str(user_id),
            nid=node_id,
            now=_now(),
        )
        row = await result.single()
        lifted = int(row["c"]) if row else 0
    if lifted:
        logger.info("soft_gate_lifted", extra={"user_id": str(user_id), "node_id": node_id})
    return lifted


async def get_active_gate_node_ids(user_id: UUID) -> set[str]:
    """
    Node ids steering/prediction must not target: every excluded_topic region and every
    ACTIVE soft gate. One set — the caller doesn't need to know which is which
    (the difference is lifecycle, not filtering).
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (a:Excluded {user_id: $uid})
            WHERE coalesce(a.status, 'active') = 'active'
              AND a.node_id IS NOT NULL AND a.node_id <> ''
            RETURN a.node_id AS nid
            UNION
            MATCH (g:Sensitive {user_id: $uid, status: 'active'})
            WHERE g.node_id IS NOT NULL AND g.node_id <> ''
            RETURN g.node_id AS nid
            """,
            uid=str(user_id),
        )
        return {r["nid"] async for r in result}


async def get_user_gates(user_id: UUID) -> dict:
    """Both gate sets, for the explanation surfaces (panel / understanding page)."""
    async with get_session() as session:
        av = await session.run(
            """
            MATCH (a:Excluded {user_id: $uid})
            RETURN a.id AS id, a.node_id AS node_id, a.region AS region,
                   coalesce(a.evidence, []) AS evidence,
                   coalesce(a.status, 'active') AS status
            """,
            uid=str(user_id),
        )
        aversions = [dict(r) async for r in av]
        sg = await session.run(
            """
            MATCH (g:Sensitive {user_id: $uid})
            RETURN g.id AS id, g.node_id AS node_id, g.element AS element,
                   g.status AS status
            ORDER BY g.status
            """,
            uid=str(user_id),
        )
        soft_gates = [dict(r) async for r in sg]
    return {"aversions": aversions, "soft_gates": soft_gates}
