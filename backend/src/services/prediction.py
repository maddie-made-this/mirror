"""
The prediction engines (build_interest_model.md §5) — candidate GENERATION.

Both engines run here, in the background pipeline, on the cheap utility model;
steering (services/steering.py) consumes the stored candidates per turn so the
hot path never waits on an LLM. Routing is per-motif by best-current evidence:

5.1 Function-generalization (PRIMARY — motifs with a credible function reading):
    from the idiographic function statement, generate configurations that satisfy
    the SAME NEED through different surface content. Stored on the function
    reading itself (`candidates`). The reaction loop then error-corrects: probes
    that land raise the reading's confidence; repeated flat landings lower it
    (services/uptake.py) — function-prediction without that loop is forbidden.

5.2 Similarity-generalization (SECONDARY — high-salience motifs with NO credible
    function): the LLM's population prior only RANKS; the user's own
    co-occurrence neighbors are injected so THEIR graph dominates wherever it
    exists; reactions decide. Stored on the node (`adjacent_candidates`).

`origin_episode` never feeds either engine (it doesn't generalize — §5.1).
"""
import json
import logging
from uuid import UUID

from config.loader import APP_CONFIG
from db.neo4j import get_session
from llm.client import chat
from services import graph_service

logger = logging.getLogger(__name__)

_MAX_FUNCTION_READINGS_PER_RUN = 4
_MAX_SIMILARITY_NODES_PER_RUN = 3
_CREDIBLE_FUNCTION_CONFIDENCE = 0.6
_SALIENCE_THRESHOLD = 0.5

_FUNCTION_CANDIDATE_SYSTEM = """
You generate candidate directions for a personalization engine, from a FUNCTION
hypothesis — a description of the underlying pull a person's interest satisfies.

Given the idiographic function statement and the surface content it currently
lives in, propose 3-5 DIFFERENT surface directions that satisfy the SAME
underlying pull. The pull is the invariant; the surface must change. (Example:
"tracing a system to its foundations relieves them of ambiguity" → a first-
principles derivation; a reverse-engineering teardown; a formal proof that
closes every gap. NOT more variants of the same topic.)

Rules:
- Each candidate is a short, concrete angle or framing (4-12 words), weavable
  into an ongoing exploration as a gentle probe — not a full treatment.
- Stay faithful to the stated pull; do not drift to a generic interest.
- PRESERVE THE DIRECTION. Read whether the pull is toward resolving or toward
  dwelling, toward building or toward taking apart, and keep it. If the pull is
  toward the unresolved snag, EVERY candidate keeps that open-endedness; never
  flip it into tidy closure. If the pull is toward completeness, keep it there.
  Getting the direction backwards offers the opposite of what they want.
- PRESERVE THE REGISTER. Match the tone their own material establishes. If their
  material is rigorous, skeptical, unsentimental, the candidates must be too —
  never soften into breezy, inspirational, or crowd-pleasing framing unless
  THEIR words ask for it. A candidate in the wrong register serves a different
  person's interest.
- HONOR what's established about this person (given below): never propose
  anything that contradicts a belief or preference they have confirmed.
- Avoid the current surface content and trivial synonyms of it.
Return JSON only: {"candidates": ["...", "..."]}
""".strip()

_SIMILARITY_CANDIDATE_SYSTEM = """
You generate adjacent directions for a personalization engine, for an interest
with NO known underlying function — a taste that simply is what it is.
Prediction here is neighborhood, not meaning.

You are given the interest and the concepts that co-occur with it in THIS user's
own words. Your own broad associations may only RANK ideas; the user's
co-occurrence list carries more weight than anything you'd assume from the
population — wherever their graph suggests a direction, prefer it.

Rules:
- Propose exactly 3 adjacent directions, each a short concrete angle or framing
  (4-12 words), ordered most→least promising for THIS user.
- Adjacent means near the interest in feel/texture/shape — a small step out,
  not a leap to a different territory.
- PRESERVE DIRECTION and REGISTER: keep the same resolving-vs-dwelling,
  building-vs-dismantling orientation the interest shows, and match their tone
  (rigorous/skeptical stays rigorous/skeptical; do not soften into breezy or
  inspirational unless their own words ask for it).
- HONOR what's established about this person (given below): never contradict a
  confirmed belief or preference.
Return JSON only: {"candidates": ["...", "...", "..."]}
""".strip()


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_candidates(raw: str, cap: int = 5) -> list[str]:
    data = json.loads(_strip_fence(raw))
    items = data.get("candidates", []) if isinstance(data, dict) else []
    out = []
    for c in items:
        c = str(c).strip()
        if 3 <= len(c) <= 120:
            out.append(c)
    return out[:cap]


async def _established_facts(user_id: UUID, limit: int = 6) -> str:
    """
    The register/role anchors the candidate generators need: the user's CONFIRMED
    (affirmed, conf 1.0 via the efficacy loop) and otherwise high-confidence
    belief + function readings. This is the signal that tells the generator their
    register (rigorous/plain vs warm) and their stance (skeptical vs receptive),
    and what never to contradict — the absence of it is why probes came back
    generic and off-register. Returns a prompt block, or "" when nothing is
    established.
    """
    async with get_session() as session:
        res = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind IN ['belief', 'function']
              AND i.status <> 'rejected'
              AND coalesce(i.confidence, 0) >= 0.6
            RETURN i.statement AS s, coalesce(i.confidence, 0) AS c
            ORDER BY c DESC LIMIT $lim
            """,
            uid=str(user_id),
            lim=limit,
        )
        facts = [r["s"] async for r in res if r["s"]]
    if not facts:
        return ""
    return (
        "\n\nEstablished about this person (honor these — their register and role; "
        "never contradict, never soften):\n" + "\n".join(f"- {f}" for f in facts)
    )


async def generate_function_candidates(user_id: UUID) -> int:
    """
    Fill `candidates` on credible function readings that don't have them yet.
    Returns how many readings were populated.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'function'
              AND i.status <> 'rejected'
              AND coalesce(i.confidence, 0) >= $minc
              AND coalesce(i.candidates, []) = []
            RETURN i.id AS id, i.statement AS statement,
                   coalesce(i.attached_node_ids, []) AS node_ids
            ORDER BY i.confidence DESC
            LIMIT $lim
            """,
            uid=str(user_id),
            minc=_CREDIBLE_FUNCTION_CONFIDENCE,
            lim=_MAX_FUNCTION_READINGS_PER_RUN,
        )
        readings = [dict(r) async for r in result]

        if not readings:
            return 0

        # Resolve current surface content (the attached node names) so the
        # generator can avoid proposing the same surface back.
        node_ids = sorted({nid for r in readings for nid in r["node_ids"]})
        names: dict[str, str] = {}
        if node_ids:
            nres = await session.run(
                "MATCH (n:Node {user_id: $uid}) WHERE n.id IN $ids "
                "RETURN n.id AS id, n.name AS name",
                uid=str(user_id),
                ids=node_ids,
            )
            names = {r["id"]: r["name"] async for r in nres}

    anchors = await _established_facts(user_id)

    populated = 0
    for r in readings:
        surface = ", ".join(names.get(nid, "") for nid in r["node_ids"] if names.get(nid))
        user_content = (
            f"Function statement: {r['statement']}\n"
            f"Current surface content: {surface or 'unknown'}"
            f"{anchors}"
        )
        try:
            raw = await chat(
                [
                    {"role": "system", "content": _FUNCTION_CANDIDATE_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                model=APP_CONFIG.utility_model_resolved,
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=APP_CONFIG.utility_max_tokens,
            )
            candidates = _parse_candidates(raw, cap=5)
        except Exception:
            logger.warning("function candidate generation failed", extra={"id": r["id"]})
            continue
        if not candidates:
            continue
        async with get_session() as session:
            await session.run(
                "MATCH (i:Interpretation {id: $id, user_id: $uid}) "
                "SET i.candidates = $cands",
                id=r["id"],
                uid=str(user_id),
                cands=candidates,
            )
        populated += 1

    if populated:
        logger.info(
            "function_candidates_generated",
            extra={"user_id": str(user_id), "readings": populated},
        )
    return populated


async def generate_similarity_candidates(user_id: UUID) -> int:
    """
    Fill `adjacent_candidates` on high-salience nodes that have NO credible function
    reading (the conditioned accidents). Returns how many nodes were populated.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE NOT n.entity_type IN ['self', 'boundary', 'preference', 'format_rule']
              AND coalesce(n.salience_score_mean, n.salience_score, 0) >= $thr
              AND n.mention_count >= 3
              AND coalesce(n.adjacent_candidates, []) = []
              AND NOT EXISTS {
                MATCH (i:Interpretation {user_id: $uid})
                WHERE i.kind = 'function'
                  AND i.status <> 'rejected'
                  AND coalesce(i.confidence, 0) >= $minc
                  AND (n.id IN coalesce(i.attached_node_ids, [])
                       OR n.id IN coalesce(i.evidence, []))
              }
            RETURN n.id AS id, n.name AS name
            ORDER BY coalesce(n.salience_score_mean, n.salience_score, 0) DESC
            LIMIT $lim
            """,
            uid=str(user_id),
            thr=_SALIENCE_THRESHOLD,
            minc=_CREDIBLE_FUNCTION_CONFIDENCE,
            lim=_MAX_SIMILARITY_NODES_PER_RUN,
        )
        nodes = [dict(r) async for r in result]

    anchors = await _established_facts(user_id)

    populated = 0
    for n in nodes:
        # The user's own co-occurrence neighborhood — their graph dominates (§5.2).
        try:
            neighbors = await graph_service.get_cooccurring_nodes(user_id, n["id"], limit=8)
            neighbor_names = [g.name for g, _count in neighbors]
        except Exception:
            neighbor_names = []
        user_content = (
            f"Motif: {n['name']}\n"
            f"Co-occurs in this user's own words with: "
            f"{', '.join(neighbor_names) if neighbor_names else '(nothing yet)'}"
            f"{anchors}"
        )
        try:
            raw = await chat(
                [
                    {"role": "system", "content": _SIMILARITY_CANDIDATE_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                model=APP_CONFIG.utility_model_resolved,
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=APP_CONFIG.utility_max_tokens,
            )
            candidates = _parse_candidates(raw, cap=3)
        except Exception:
            logger.warning("similarity candidate generation failed", extra={"id": n["id"]})
            continue
        if not candidates:
            continue
        async with get_session() as session:
            await session.run(
                "MATCH (n:Node {id: $id, user_id: $uid}) "
                "SET n.adjacent_candidates = $cands",
                id=n["id"],
                uid=str(user_id),
                cands=candidates,
            )
        populated += 1

    if populated:
        logger.info(
            "similarity_candidates_generated",
            extra={"user_id": str(user_id), "nodes": populated},
        )
    return populated
