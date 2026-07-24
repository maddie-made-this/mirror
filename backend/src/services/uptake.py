"""
Per-element uptake (build_interest_model.md §3, §6) — the reaction loop's sensor.

Every element generation deliberately introduces (a function/similarity probe, an
elicitation target) gets an offer row when the AI turn goes out. The user's NEXT
message judges it: picked up / echoed / specifically engaged → 'taken'; ignored
while the conversation continued → 'passed'. Inferred, never asked — no UI exists
for this on purpose; it is what makes the experience attuned without interrogation.

Consequences close the loop:
- taken  → the source function reading's confidence rises (+); an active Sensitive
           on that node lifts (conditions changed — welcome, don't relitigate).
- passed → repeated flat landings push the function hypothesis DOWN (§5.1 error
           correction — a wrong function mispredicts its neighborhood), and ≥3
           passes on the same element while CLEARLY ENGAGED creates a Sensitive
           and the engine stops pushing that thread (§6). The asymmetry is
           deliberate: wrongly gating a neutral costs nothing; pushing a real
           gate costs trust. Never re-test a disengagement signal to confirm it.

Judging is heuristic and code-level (no LLM): node-overlap with what extraction
touched, then content-word overlap with the element phrase. Cheap, deterministic,
and biased toward 'passed' — which the asymmetry above makes the safe direction.
"""
import logging
import re
from uuid import UUID

from db.postgres import get_pool
from services import gates, interpretation

logger = logging.getLogger(__name__)

_PASSES_TO_GATE = 3
# Downward nudge per flat probe, applied from the second pass on (§5.1).
_ERROR_CORRECTION_DELTA = -0.12
_UPTAKE_REINFORCE_DELTA = 0.10

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "their",
    "them", "they", "her", "his", "she", "him", "you", "your", "being",
    "having", "about", "over", "under", "while", "what", "when", "where",
}


# --------------------------------------------------------------------------- #
# Pure cores
# --------------------------------------------------------------------------- #

def judge_uptake(
    element: str,
    node_id: str | None,
    message_text: str,
    touched_node_ids: set[str],
) -> str:
    """
    'taken' | 'passed'. Taken when the user's reply engaged the offered element:
    extraction touched its node, the element phrase appears, or at least half of
    the element's content words do. Anything else is passed — the safe verdict.
    """
    if node_id and node_id in touched_node_ids:
        return "taken"
    msg = (message_text or "").lower()
    el = (element or "").lower().strip()
    if not el or not msg:
        return "passed"
    if el in msg:
        return "taken"
    words = [w for w in re.findall(r"[a-z']{3,}", el) if w not in _STOPWORDS]
    if words:
        hits = sum(1 for w in words if w in msg)
        if hits / len(words) >= 0.5:
            return "taken"
    return "passed"


def should_gate(consecutive_passes: int, clearly_engaged: bool) -> bool:
    """
    §6 non-engagement signal: ≥3 offered opportunities, zero uptake, while clearly
    engaged with the surrounding material. Disengagement (a guarded session) is NOT
    evidence about the element — no gate forms from it.
    """
    return consecutive_passes >= _PASSES_TO_GATE and clearly_engaged


# --------------------------------------------------------------------------- #
# Offer recording + judging
# --------------------------------------------------------------------------- #

async def record_offer(
    user_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
    element: str,
    source_tag: str,
    node_id: str | None = None,
    interpretation_id: str | None = None,
) -> None:
    """One offer row per deliberately-introduced element (extends B2)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO element_offers
                (user_id, conversation_id, message_id, element, source_tag,
                 node_id, interpretation_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            str(user_id),
            str(conversation_id),
            str(message_id),
            element[:300],
            source_tag[:120],
            node_id,
            interpretation_id,
        )


async def get_offers_for_message(user_id: UUID, message_id: UUID) -> list[dict]:
    """The graph elements deliberately offered on this turn (P2.4 thinking view):
    {element, source_tag, uptake}. A real artifact the pipeline already recorded."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT element, source_tag, uptake FROM element_offers
            WHERE user_id = $1 AND message_id = $2
            ORDER BY created_at
            """,
            str(user_id),
            str(message_id),
        )
    return [dict(r) for r in rows]


async def get_offered_elements(user_id: UUID, candidates: list[str]) -> set[str]:
    """Which of these candidate elements have already been offered (any verdict)."""
    if not candidates:
        return set()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT element FROM element_offers
            WHERE user_id = $1 AND element = ANY($2::text[])
            """,
            str(user_id),
            [c[:300] for c in candidates],
        )
    return {r["element"] for r in rows}


async def _passes_since_last_taken(
    conn, user_id: UUID, node_id: str | None, element: str
) -> list[str]:
    """
    Offer ids judged 'passed' for this element/node since it was last taken.
    A taken resets the count — interest demonstrated later supersedes old passes.
    """
    rows = await conn.fetch(
        """
        WITH matching AS (
            SELECT id, uptake, judged_at FROM element_offers
            WHERE user_id = $1
              AND ((node_id IS NOT NULL AND node_id = $2) OR element = $3)
              AND uptake IS NOT NULL
        ),
        last_taken AS (
            SELECT max(judged_at) AS t FROM matching WHERE uptake = 'taken'
        )
        SELECT m.id FROM matching m, last_taken lt
        WHERE m.uptake = 'passed'
          AND (lt.t IS NULL OR m.judged_at > lt.t)
        """,
        str(user_id),
        node_id,
        element,
    )
    return [str(r["id"]) for r in rows]


async def judge_pending(
    user_id: UUID,
    conversation_id: UUID,
    message_text: str,
    touched_node_ids: set[str],
    clearly_engaged: bool,
) -> int:
    """
    Judge every pending offer in this conversation against the user's new
    message, then apply the loop consequences. Called from the message path
    after extraction (so touched_node_ids is known), BEFORE this turn's own
    offer is recorded. Returns how many offers were judged.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        pending = await conn.fetch(
            """
            SELECT id, element, node_id, interpretation_id FROM element_offers
            WHERE user_id = $1 AND conversation_id = $2 AND uptake IS NULL
            ORDER BY created_at
            """,
            str(user_id),
            str(conversation_id),
        )
        if not pending:
            return 0

        judged = 0
        for offer in pending:
            verdict = judge_uptake(
                offer["element"], offer["node_id"], message_text, touched_node_ids
            )
            await conn.execute(
                "UPDATE element_offers SET uptake = $1, judged_at = now() WHERE id = $2",
                verdict,
                offer["id"],
            )
            judged += 1

            try:
                if verdict == "taken":
                    if offer["interpretation_id"]:
                        await interpretation.reinforce(
                            user_id, [offer["interpretation_id"]],
                            delta=_UPTAKE_REINFORCE_DELTA,
                        )
                    if offer["node_id"]:
                        await gates.lift_soft_gate(user_id, offer["node_id"])
                    continue

                # passed —
                passes = await _passes_since_last_taken(
                    conn, user_id, offer["node_id"], offer["element"]
                )
                if offer["interpretation_id"] and len(passes) >= 2:
                    # The hypothesis mispredicted its neighborhood twice: move it.
                    await interpretation.reinforce(
                        user_id, [offer["interpretation_id"]],
                        delta=_ERROR_CORRECTION_DELTA,
                    )
                if offer["node_id"] and should_gate(len(passes), clearly_engaged):
                    await gates.create_soft_gate(
                        user_id, offer["node_id"], offer["element"], passes
                    )
            except Exception:
                # Verdict is recorded; consequences are best-effort.
                logger.exception(
                    "uptake consequence failed", extra={"offer_id": str(offer["id"])}
                )

    logger.info(
        "offers_judged",
        extra={"user_id": str(user_id), "count": judged},
    )
    return judged
