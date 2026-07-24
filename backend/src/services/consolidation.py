"""
The consolidation rule (build_interest_model.md §2.2) — the model's diachronic law:
repeated realized salience at a configuration, ESPECIALLY during deep-ramp moments,
grows (or creates) a motif there.

Runs in the background pipeline. Marks qualifying nodes `motif = true` with an
`motif_confidence` (the future learned-weight slot). Three guarantees:

- Reframing-born motifs KEEP their links: nothing here (or anywhere) deletes a
  kind=reframing reading. The explanation product references both the autonomous
  motif and the work it originally did (acceptance §9.3).
- Insight does not dissolve a motif: an affirmed origin/function reading has no
  effect on the motif flag — at best it widens the repertoire.
- Deep-ramp mentions weigh double: high-salience moments are motif-formation
  moments (Mention.depth_ramp, stamped at ingest).

The scoring core is a pure function for the acceptance tests.
"""
import logging
from uuid import UUID

from db.neo4j import get_session

logger = logging.getLogger(__name__)

# Below either threshold a configuration has not consolidated yet.
_MIN_MENTIONS = 4
_MIN_SALIENCE_MEAN = 0.45

# Node types that can anchor a motif. The rest are infrastructure (self,
# preferences/format rules) or non-content (boundary = gate territory).
_NON_MOTIFABLE = ["self", "boundary", "preference", "format_rule"]


def motif_score(
    mention_count: int,
    deep_mentions: int,
    session_span: int,
    salience_mean: float,
) -> float:
    """
    Pure scoring core. Repetition + deep-ramp formation moments + cross-session
    persistence, scaled by salience. Returns 0.0 below the consolidation floor,
    else a confidence in (0, 0.95] — capped below 1.0 because only live user
    confirmation may saturate anything in this system.
    """
    if mention_count < _MIN_MENTIONS or salience_mean < _MIN_SALIENCE_MEAN:
        return 0.0
    accumulation = (
        0.30
        + 0.07 * mention_count
        + 0.10 * deep_mentions          # deep-ramp repetitions stamp harder (§2.2)
        + 0.08 * max(session_span, 0)   # surviving across sessions = persistence
    )
    weight = 0.5 + salience_mean / 2     # salience_mean in [0.45, 1] → [0.725, 1]
    return round(min(accumulation * weight, 0.95), 3)


async def consolidate_user(user_id: UUID) -> int:
    """
    Score every candidate configuration and mark the qualifiers as motifs.
    Idempotent: re-running re-scores (confidence can rise with new mentions; the
    flag never silently unsets — de-consolidation is not a thing the model does).
    Returns how many nodes were marked/updated.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE NOT n.entity_type IN $skip
              AND n.mention_count >= $min_mentions
              AND coalesce(n.salience_score_mean, 0) >= $min_salience
            OPTIONAL MATCH (m:Mention {user_id: $uid, depth_ramp: 'deep'})-[:REFERENCES]->(n)
            WITH n, count(DISTINCT m) AS deep
            RETURN n.id AS id,
                   n.mention_count AS mentions,
                   deep,
                   coalesce(n.salience_score_mean, 0) AS salience_mean,
                   coalesce(n.last_session, 0) - coalesce(n.first_session, 0) AS span
            """,
            uid=str(user_id),
            skip=_NON_MOTIFABLE,
            min_mentions=_MIN_MENTIONS,
            min_salience=_MIN_SALIENCE_MEAN,
        )
        rows = [dict(r) async for r in result]

        updates = []
        for r in rows:
            score = motif_score(
                r["mentions"], r["deep"], r["span"], r["salience_mean"]
            )
            if score > 0:
                updates.append({"id": r["id"], "score": score})

        if updates:
            await session.run(
                """
                UNWIND $updates AS u
                MATCH (n:Node {id: u.id, user_id: $uid})
                SET n.motif = true,
                    n.motif_confidence = u.score
                """,
                uid=str(user_id),
                updates=updates,
            )

    if updates:
        logger.info(
            "motifs_consolidated",
            extra={"user_id": str(user_id), "count": len(updates)},
        )
    return len(updates)
