"""
The dials (build_interest_model.md §4) — trait layer + session layer.

Trait layer (SalienceDynamics, Postgres user_dynamics): engagement/reticence gains, pacing,
engagement baseline. Slow-moving by construction: update_traits runs in the
background pipeline, uses EMAs, and refuses to move anything until enough
cross-session data exists. (A) infers coarsely; every value carries `confidence`
— the slot a learned weight will occupy in (B).

Session layer (SessionState): coarse, per-conversation, computed fresh each turn
from cheap queries and NEVER persisted — the hard rule "session readings modulate
behavior NOW; only slow cross-session accumulation moves traits" is enforced by
there being no write path at all.

The heuristic cores (ramp_from / gate_from / ema) are pure functions so the
acceptance tests (§9.4) can exercise them without infrastructure.
"""
import logging
from uuid import UUID

from db.neo4j import get_session
from db.postgres import get_pool
from schemas.interest import SalienceDynamics, Frame, GatePosition, DepthRamp, SessionState

logger = logging.getLogger(__name__)

# How many recent turns/mentions the session readings look at.
_RECENT_TURNS = 4
_RECENT_MENTIONS = 12

# Traits refuse to move off their priors until this much data exists.
_MIN_SESSIONS_FOR_ENGAGEMENT = 2
_MIN_OFFERS_FOR_RETICENCE = 6


# --------------------------------------------------------------------------- #
# Pure heuristic cores
# --------------------------------------------------------------------------- #

def ramp_from(turn_count: int, recent_salience_mean: float) -> DepthRamp:
    """
    Depth ramp position (§4): sustained salience deep into a conversation raises
    the effective depth of the exchange. Coarse three-step read:
    DEEP requires both length and sustained engagement — it is the motif-formation
    zone; MID is building; EARLY is settling in.
    """
    if turn_count >= 8 and recent_salience_mean >= 0.45:
        return DepthRamp.DEEP
    if turn_count >= 3 and recent_salience_mean >= 0.2:
        return DepthRamp.MID
    if turn_count >= 6:
        return DepthRamp.MID  # long but low-salience — engaged, not deep
    return DepthRamp.EARLY


def gate_from(recent_mean_chars: float, baseline_chars: float) -> GatePosition:
    """
    Gate position (§4): read as DEVIATION of current engagement from the user's
    OWN baseline — never an absolute. Above their norm → open (steering
    opportunity); well below → guarded (follow and soothe). Unknown baseline
    (new user) → neutral, because there is nothing to deviate from.
    """
    if baseline_chars <= 0 or recent_mean_chars <= 0:
        return GatePosition.NEUTRAL
    ratio = recent_mean_chars / baseline_chars
    if ratio >= 1.3:
        return GatePosition.OPEN
    if ratio <= 0.55:
        return GatePosition.GUARDED
    return GatePosition.NEUTRAL


def ema(previous: float, observed: float, alpha: float = 0.2) -> float:
    """One EMA step — the only way traits move."""
    return previous + alpha * (observed - previous)


# --------------------------------------------------------------------------- #
# Session layer — computed per turn, never stored
# --------------------------------------------------------------------------- #

async def get_session_state(
    user_id: UUID, conversation_id: UUID, session_type: str = "primary"
) -> SessionState:
    """
    Compute this conversation's coarse session state right now. Cheap: one
    Postgres read (turn counts + recent lengths + baseline) and one Neo4j read
    (recent mention salience). active_region is filled by the caller from the
    turn's graph context (it already has the relevant nodes in hand).
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*) AS turns
            FROM conversation_turns
            WHERE user_id = $1 AND conversation_id = $2
            """,
            str(user_id),
            str(conversation_id),
        )
        turn_count = int(row["turns"]) if row else 0

        recent = await conn.fetch(
            """
            SELECT coalesce(msg_char_len, length(user_message)) AS chars
            FROM conversation_turns
            WHERE user_id = $1 AND conversation_id = $2 AND user_message <> ''
            ORDER BY created_at DESC
            LIMIT $3
            """,
            str(user_id),
            str(conversation_id),
            _RECENT_TURNS,
        )
        recent_chars = (
            sum(r["chars"] for r in recent) / len(recent) if recent else 0.0
        )

        dyn = await conn.fetchrow(
            "SELECT baseline_msg_chars FROM user_dynamics WHERE user_id = $1",
            str(user_id),
        )
        baseline = float(dyn["baseline_msg_chars"]) if dyn else 0.0

    recent_salience = 0.0
    try:
        async with get_session() as neo:
            result = await neo.run(
                """
                MATCH (m:Mention {user_id: $uid, conversation_id: $cid})
                WITH m ORDER BY m.created_at DESC LIMIT $lim
                RETURN avg(coalesce(m.salience_score, 0)) AS a
                """,
                uid=str(user_id),
                cid=str(conversation_id),
                lim=_RECENT_MENTIONS,
            )
            row = await result.single()
            recent_salience = float(row["a"]) if row and row["a"] is not None else 0.0
    except Exception:
        logger.warning("session-state salience read failed; assuming low engagement")

    return SessionState(
        depth_ramp=ramp_from(turn_count, recent_salience),
        gate_position=gate_from(recent_chars, baseline),
        frame=Frame.REAL if session_type == "analytic" else Frame.FICTION,
        turn_count=turn_count,
    )


# --------------------------------------------------------------------------- #
# Trait layer — background only (maintenance pipeline)
# --------------------------------------------------------------------------- #

async def update_traits(user_id: UUID) -> SalienceDynamics | None:
    """
    Slow cross-session accumulation onto user_dynamics. Each tick: EMA the
    engagement baseline; move the engagement gain toward the user's long-run
    salience mean once enough sessions exist; move the reticence gain toward the
    offer pass-rate once enough offers have been judged. Session-layer readings
    are never inputs here in raw form — only whole-history aggregates, which is
    what makes a single guarded session unable to tighten the disposition.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        agg = await conn.fetchrow(
            """
            SELECT count(DISTINCT conversation_id) AS convos,
                   avg(coalesce(msg_char_len, length(user_message))) AS mean_chars
            FROM conversation_turns
            WHERE user_id = $1 AND user_message <> ''
            """,
            str(user_id),
        )
        if not agg or not agg["convos"]:
            return None

        offers = await conn.fetchrow(
            """
            SELECT count(*) FILTER (WHERE uptake = 'passed') AS passed,
                   count(*) FILTER (WHERE uptake IS NOT NULL) AS judged
            FROM element_offers
            WHERE user_id = $1
            """,
            str(user_id),
        )
        judged = int(offers["judged"] or 0)
        passed = int(offers["passed"] or 0)

    # Long-run salience mean across the whole graph (mention-weighted).
    salience_mean = 0.0
    sessions_observed = 0
    try:
        async with get_session() as neo:
            result = await neo.run(
                """
                MATCH (m:Mention {user_id: $uid})
                RETURN avg(coalesce(m.salience_score, 0)) AS a,
                       count(DISTINCT m.session_number) AS sessions
                """,
                uid=str(user_id),
            )
            row = await result.single()
            if row:
                salience_mean = float(row["a"]) if row["a"] is not None else 0.0
                sessions_observed = int(row["sessions"] or 0)
    except Exception:
        logger.warning("trait salience read failed; engagement_gain holds")

    pool = await get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT * FROM user_dynamics WHERE user_id = $1", str(user_id)
        )
        engagement = float(current["engagement_gain"]) if current else 0.5
        reticence = float(current["reticence_gain"]) if current else 0.5
        baseline = float(current["baseline_msg_chars"]) if current else 0.0

        baseline = ema(baseline, float(agg["mean_chars"] or 0.0), alpha=0.3) \
            if baseline > 0 else float(agg["mean_chars"] or 0.0)

        if sessions_observed >= _MIN_SESSIONS_FOR_ENGAGEMENT:
            # Map salience mean [-1, 1] → gain [0, 1]; nudge, never jump.
            engagement = ema(engagement, (salience_mean + 1) / 2, alpha=0.2)
        if judged >= _MIN_OFFERS_FOR_RETICENCE:
            # A high pass-rate = reticence engages easily → higher reticence gain.
            reticence = ema(reticence, passed / judged, alpha=0.2)

        confidence = min(0.3 + 0.05 * sessions_observed + 0.02 * judged, 0.8)

        await conn.execute(
            """
            INSERT INTO user_dynamics
                (user_id, engagement_gain, reticence_gain, baseline_msg_chars,
                 sessions_observed, confidence, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (user_id) DO UPDATE SET
                engagement_gain = $2, reticence_gain = $3, baseline_msg_chars = $4,
                sessions_observed = $5, confidence = $6, updated_at = now()
            """,
            str(user_id),
            round(engagement, 4),
            round(reticence, 4),
            round(baseline, 1),
            sessions_observed,
            round(confidence, 3),
        )

    return SalienceDynamics(
        user_id=user_id,
        engagement_gain=engagement,
        reticence_gain=reticence,
        baseline_msg_chars=baseline,
        sessions_observed=sessions_observed,
        confidence=confidence,
    )
