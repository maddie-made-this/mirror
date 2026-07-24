"""
Interpretation layer.

The system's hypotheses about the user, attached to the graph as :Interpretation
nodes ([:EXPLAINS]->(:Node|:Cluster)). A periodic reflection pass (run from the
scheduler) reads a cluster's members + recent mentions and asks the LLM for a
few sourced, rejectable interpretations at low confidence. Confidence then moves
with accumulation and — dominantly — the user's affirm/reject/qualify response.

That response loop (api/v1/interpretations.py POST /respond) IS the efficacy
test: offline validation is contaminated (training + context-window), so the
only valid score is live user confirmation. Ship the loop.
"""

import json
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from config.loader import APP_CONFIG
from db.neo4j import get_session
from llm.client import chat
from services import embedding
from schemas.interpretation import (
    Interpretation,
    InterpretationKind,
    InterpretationStatus,
    UserResponse,
)

logger = logging.getLogger(__name__)

# Confidence at/above which a candidate is eligible to be surfaced to the user.
_SURFACE_THRESHOLD = 0.6
# Max clusters to reflect over per run (bounds LLM cost per tick).
_MAX_CLUSTERS_PER_RUN = 8
# Mentions sampled per cluster for the reflection prompt.
_MENTIONS_PER_CLUSTER = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    lines = s.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #

async def save_interpretation(interp: Interpretation) -> None:
    """Persist a :Interpretation node + [:EXPLAINS] edges to its nodes/clusters."""
    # C3a confidence floor: never store/surface a sub-floor reading.
    if interp.confidence < APP_CONFIG.reading_confidence_floor:
        logger.debug("dropping sub-floor reading",
                     extra={"confidence": interp.confidence, "kind": str(interp.kind)})
        return
    props = interp.model_dump(mode="json", exclude={"id", "user_id"})
    async with get_session() as session:
        await session.run(
            """
            MERGE (i:Interpretation {id: $id, user_id: $uid})
            SET i += $props
            WITH i
            UNWIND ($node_ids + $cluster_ids) AS target_id
            MATCH (t {id: target_id, user_id: $uid})
            MERGE (i)-[:EXPLAINS]->(t)
            """,
            id=str(interp.id),
            uid=str(interp.user_id),
            props=props,
            node_ids=interp.attached_node_ids,
            cluster_ids=interp.attached_cluster_ids,
        )


async def _existing_cluster_interps(user_id: UUID) -> set[str]:
    """
    Cluster ids that already have a non-rejected interpretation. Read from the
    interpretation's stored attached_cluster_ids (a property), NOT the live
    [:EXPLAINS] edge — clustering DETACH DELETEs :Cluster nodes each run, which
    would drop those edges and cause endless re-generation. With stable cluster
    ids (membership hash), a still-present cluster stays covered across runs.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.status <> 'rejected' AND i.attached_cluster_ids IS NOT NULL
            UNWIND i.attached_cluster_ids AS cid
            RETURN DISTINCT cid
            """,
            uid=str(user_id),
        )
        return {r["cid"] async for r in result}


async def _clusters_with_members(user_id: UUID) -> list[dict]:
    """Clusters + their member node names + a sample of recent mention texts."""
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
            RETURN c.id AS cid, c.label AS label, node_ids, names, mentions
            ORDER BY size(node_ids) DESC
            """,
            uid=str(user_id),
            mlimit=_MENTIONS_PER_CLUSTER,
        )
        return [dict(r) async for r in result]


# --------------------------------------------------------------------------- #
# Reflection pass
# --------------------------------------------------------------------------- #

def _norm_statement(s: str) -> str:
    """Normalize a statement/category for duplicate detection: lowercase, drop
    punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def _canonical_category(cat: str, categories: list[str]) -> str:
    """Map a model-returned category onto a canonical list entry (exact or head match),
    or "" if it matches none — the backstop (insight-synthesis spec C3) that drops a
    hallucinated category and lets a positive/neutral reading stay uncategorized rather
    than be shoehorned into a category it doesn't fit. Empty list → always ""."""
    c = _norm_statement(cat)
    if not c:
        return ""
    for entry in categories:
        if c == _norm_statement(entry) or c == _norm_statement(entry.split("(")[0]):
            return entry
    return ""


async def _existing_function_statements(user_id: UUID) -> set[str]:
    """Normalized 'function' statements the user already has (non-rejected), for
    cross-node dedup (insight-synthesis spec C1) — the dumps surfaced one generic
    function copied onto many nodes."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'function' AND i.status <> 'rejected'
            RETURN i.statement AS statement
            """,
            uid=str(user_id),
        )
        return {
            _norm_statement(r["statement"]) async for r in result if r["statement"]
        }


async def _existing_function_embeddings(user_id: UUID) -> list[list[float]]:
    """Embeddings of the user's existing (non-rejected) 'function' statements, for the
    C2 COSINE dedup — catches reworded paraphrases the lexical check (above) misses."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'function' AND i.status <> 'rejected'
            RETURN i.statement AS statement
            """,
            uid=str(user_id),
        )
        stmts = [r["statement"] async for r in result if r["statement"]]
    return await embedding.embed_batch(stmts) if stmts else []


async def _synth_one_headline(name: str, statements: list[str]) -> str:
    """LLM-synthesize ONE short headline (utility tier) from a node's readings — a
    summary, never a copy of a single reading (producer C3b)."""
    system = (
        "You write ONE short headline (max ~12 words) that SYNTHESIZES what these "
        "readings about a person's interest add up to. It is a synthesis, NOT a "
        "copy of any single line and NOT a quote. Plain, third person, no preamble, no "
        "quotation marks. Return only the headline."
    )
    user = f"Concept: {name}\nReadings:\n" + "\n".join(f"- {s}" for s in statements)
    try:
        raw = await chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=APP_CONFIG.headline_model_resolved,  # P5.3 headline-synthesis tier
            temperature=0.3,
        )
        return _strip_fence(raw).strip().strip('"').strip()[:160]
    except Exception:
        logger.warning("headline synthesis failed", extra={"node": name})
        return ""


async def synthesize_node_headlines(user_id: UUID) -> int:
    """Producer C3b: for every developed node, synthesize a SHORT headline from its
    readings and store it on the node, so get_node_readings serves a synthesis rather
    than a verbatim copy of the first function reading. Returns the count updated."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})<-[:EXPLAINS]-(i:Interpretation {user_id: $uid})
            WHERE i.status <> 'rejected' AND coalesce(i.statement, '') <> ''
            RETURN n.id AS nid, n.name AS name, collect(i.statement)[..6] AS statements
            """,
            uid=str(user_id),
        )
        nodes = [(r["nid"], r["name"], list(r["statements"])) async for r in result]

    updated = 0
    for nid, name, statements in nodes:
        stmts = [s for s in statements if s]
        if not stmts:
            continue
        headline = await _synth_one_headline(name or "", stmts)
        if not headline:
            continue
        async with get_session() as session:
            await session.run(
                "MATCH (n:Node {id: $nid, user_id: $uid}) SET n.headline = $h",
                nid=nid, uid=str(user_id), h=headline,
            )
        updated += 1
    if updated:
        logger.info("node_headlines_synthesized",
                    extra={"user_id": str(user_id), "count": updated})
    return updated


def _build_reflection_system(categories: list[str]) -> str:
    """
    The reflection prompt. Statements MUST be IDIOGRAPHIC (A3) — the user's own
    specifics, never a bare category — because the idiographic belief is what feeds
    generation; a category-level statement is hollow. When `categories` is non-empty
    (when a taxonomy is configured), each interpretation is also tagged with the
    nomothetic category
    family it fits (a metadata index, not the payload).
    """
    base = (
        "You are forming sourced, rejectable, IDIOGRAPHIC hypotheses about a person "
        "from a themed cluster of their concepts and the verbatim things they said.\n\n"
        "For the cluster, propose 0-2 interpretations. Each MUST be:\n"
        "- IDIOGRAPHIC: phrased in THIS person's own specifics — their relationships, "
        "their history, their verbatim details from the quotes. A statement that "
        "could apply to many people is too coarse; do not produce it. NEVER state a "
        "bare category ('is curious', 'likes structure') — name the SPECIFIC "
        "belief in their own material. Aim for the FORM "
        "'<their specific interest> seems to connect to <a specific commitment or "
        "memory from THEIR OWN quotes>' — but the angle "
        "brackets are blanks you fill ONLY from what this person actually said.\n"
        "- BUILT ONLY FROM THEIR WORDS: do not import any person, relationship, "
        "scenario, or detail from these instructions or from anyone else. If a "
        "detail (a job, a city, an illness, a gender) is not in their quotes, "
        "it must not appear in your statement. Use the person's own pronouns and "
        "self-description as shown in their words — never assume their gender.\n"
        "- SUBJECT FIREWALL (producer C4e — write ABOUT the user, never AS them): refer "
        "to the user in a STABLE third person. NEVER attribute a piece character's "
        "pronoun, viewpoint, or attribute to the user — a character in a piece is not "
        "the author, so a reading must never use that character's 'he/him' for the user. "
        "NEVER write in the first person AS the user (no ventriloquism). If the user's "
        "own identity isn't established from their OUT-OF-PIECE self-description, "
        "use neutral reference ('the user', 'they') — not a guessed gendered pronoun "
        "and not the piece's pronoun.\n"
        "- tentative and rejectable (a hypothesis, never a verdict),\n"
        "- explicit about its inferential leap: separately state the raw detail you "
        "observed and the functional claim you draw, so it never looks more certain "
        "than the evidence.\n"
    )
    cat = ""
    if categories:
        cat = (
            "\nAlso tag each interpretation with a `category` — the underlying "
            "family it fits, copied from this fixed list (the category "
            "is a metadata index, NOT the statement):\n"
            + "\n".join(f"  - {c}" for c in categories)
            + "\nPick the one whose load-bearing specific detail selects it. The list is "
            "the deployment's configured families and nothing else; a reading that fits "
            "none of them belongs in the uncategorized entry or \"\" — NEVER stretch a "
            "family to cover a reading it does not actually describe. If "
            'two stay plausible or none clearly fits, use "" — do not guess; a later '
            "question disambiguates.\n"
        )
    schema = (
        "\nReturn JSON only: {\"interpretations\": [{\"statement\": str, \"kind\": "
        '"pattern"|"tension"|"function", '
        + ('"category": str, ' if categories else "")
        + '"inferential_step": str, "evidence": [concept names], '
        '"confidence": 0.5-0.7, '
        '"what_would_change_this": str (the concrete evidence that would revise '
        "this reading — required)}]}. "
        "If nothing specific and meaningful stands out, return an empty array."
    )
    return base + cat + schema


async def reflect_user(user_id: UUID) -> int:
    """
    Generate candidate interpretations for this user's clusters that don't yet
    have one. Returns the count created. Called by the scheduler pipeline.
    """
    skip = await _existing_cluster_interps(user_id)
    clusters = await _clusters_with_members(user_id)
    created = 0
    reflection_system = _build_reflection_system(APP_CONFIG.nomothetic_categories)

    for c in clusters[:_MAX_CLUSTERS_PER_RUN]:
        if c["cid"] in skip:
            continue
        names = [n for n in c.get("names", []) if n]
        if len(names) < 3:
            continue
        mentions = [m for m in c.get("mentions", []) if m]
        name_to_id = dict(zip(c.get("names", []), c.get("node_ids", [])))

        user_content = (
            f"Cluster theme: {c.get('label') or 'unlabeled'}\n"
            f"Concepts: {', '.join(names[:30])}\n"
            f"Recent things the user said:\n"
            + "\n".join(f"- {m}" for m in mentions[:_MENTIONS_PER_CLUSTER])
        )
        try:
            raw = await chat(
                [
                    {"role": "system", "content": reflection_system},
                    {"role": "user", "content": user_content},
                ],
                model=APP_CONFIG.reflection_model_resolved,
                response_format={"type": "json_object"},
                temperature=0.4,
            )
            data = json.loads(_strip_fence(raw))
            items = data.get("interpretations", []) if isinstance(data, dict) else []
        except Exception:
            logger.warning("interpretation reflection parse failure", extra={"cid": c["cid"]})
            continue

        for item in items[:2]:
            statement = (item.get("statement") or "").strip()
            if not statement:
                continue
            kind_raw = (item.get("kind") or "pattern").lower()
            kind = (
                InterpretationKind(kind_raw)
                if kind_raw in {k.value for k in InterpretationKind}
                else InterpretationKind.PATTERN
            )
            evidence_ids = [
                name_to_id[n] for n in item.get("evidence", []) if n in name_to_id
            ]
            confidence = float(item.get("confidence", 0.55))
            confidence = min(max(confidence, 0.5), 0.7)

            interp = Interpretation(
                user_id=user_id,
                statement=statement,
                kind=kind,
                category=_canonical_category(  # nomothetic index (A3) + C3 sanity
                    item.get("category") or "", APP_CONFIG.nomothetic_categories),
                inferential_step=(item.get("inferential_step") or "").strip(),
                what_would_change_this=(item.get("what_would_change_this") or "").strip(),
                attached_node_ids=evidence_ids,
                attached_cluster_ids=[c["cid"]],
                evidence=evidence_ids,
                confidence=confidence,
            )
            await save_interpretation(interp)
            created += 1

    if created:
        logger.info("interpretations_created", extra={"user_id": str(user_id), "count": created})
    return created


# --------------------------------------------------------------------------- #
# Motif reflection (interest-model §3): per-motif typed readings
# --------------------------------------------------------------------------- #

_MAX_MOTIFS_PER_RUN = 5
_MOTIF_SALIENCE_THRESHOLD = 0.45
_NON_MOTIFABLE = ["self", "boundary", "preference", "format_rule"]


def departure_score(
    node_salience: float,
    node_valence: float,
    user_salience_mean: float,
    user_valence_mean: float,
) -> float:
    """
    Departure-from-baseline (acceptance §9.1): a configuration that departs from
    the user's OWN affective baseline likely does psychological work for them —
    the unexpectedly intense interest against an otherwise even baseline is
    function-likely BECAUSE it is the exception. Pure; used to rank
    motif-reflection targets.
    """
    return abs(node_salience - user_salience_mean) + 0.5 * abs(node_valence - user_valence_mean)


def _build_motif_reflection_system(categories: list[str]) -> str:
    """
    The per-motif reflection prompt. One high-salience concept at a time; produces
    the motif's coexisting READINGS (§3): function / origin / belief /
    reframing. Idiographic discipline, distribution-never-verdict, no invented
    memories, "no function" is a complete result, what_would_change_this required.
    """
    base = (
        "You are reading ONE high-salience concept (a motif) in a person's "
        "interest map, from the verbatim things they said about it. Produce the "
        "motif's READINGS — tentative, sourced, rejectable hypotheses. Multiple "
        "readings COEXIST; never collapse them into one verdict.\n\n"
        "Reading kinds you may emit (0-4 total; emit ONLY what the evidence earns):\n"
        "- 'function': the work this does for them NOW — the need it satisfies. "
        "IDIOGRAPHIC: phrased in THIS person's own specifics and verbatim details. "
        "A statement that could fit many people is too coarse — do not produce it. "
        "Do NOT reproduce a generic function you would assign to many of their "
        "concepts; if the same function fits lots of their interests, sharpen it to "
        "what is specific to THIS concept, or omit it. "
        "Finding NO function is a complete, correct result: a conditioned taste "
        "often just is what it is, and inventing meaning is the overreach this "
        "system is built to avoid.\n"
        "- 'origin': where it came from, as a DISTRIBUTION over three routes — "
        "instinctual (long-standing), learned_episodic (learned from experience), "
        "reframing_consolidated (developed over time). Weights are "
        "relative plausibility, never a verdict. Include origin_episode ONLY if "
        "the user themselves recounted a concrete episode in the quotes — NEVER "
        "invent or embellish a memory; use \"\" otherwise.\n"
        "- 'belief': a limiting belief evidenced here — a learned "
        "proposition they treat as a reason not to pursue it, phrased in their own specifics "
        "(the generic shape is '<this interest> is <some specific cost>', filled "
        "only from their words). Include presses_on (which of the listed concepts "
        "it holds back) and context_sensitivity 0-1 (how much a different context "
        "loosens it).\n"
        "- 'reframing': HOW this motif's content reframes or sidesteps a limiting "
        "belief (statement = the mechanism). Emit only alongside, or pointing at, the "
        "belief it reframes.\n\n"
        "BUILD ONLY FROM THEIR WORDS: never import a person, relationship, "
        "scenario, or gender from these instructions or from other users; if a "
        "detail is not in their quotes it cannot appear. Use the person's OWN "
        "pronouns and self-description — never assume their gender.\n"
        "SUBJECT FIREWALL (producer C4e — write ABOUT the user, never AS them): refer "
        "to the user in a STABLE third person. NEVER attribute a piece character's "
        "pronoun, viewpoint, or attribute to the user — a character in a piece is not "
        "the author, so a reading must never use that character's 'he/him' for the user. "
        "NEVER write in the first person AS the user (no ventriloquism). If the user's "
        "own identity isn't established from their OUT-OF-PIECE self-description, "
        "use neutral reference ('the user', 'they') — not a guessed gendered pronoun "
        "and not the piece's pronoun.\n\n"
        "EVERY reading requires:\n"
        "- confidence 0.4-0.7 (early guesses; the user's response is what moves it),\n"
        "- what_would_change_this: the concrete evidence that would revise this "
        "reading — both honesty and the next thing worth listening for.\n\n"
        "INSUFFICIENT EVIDENCE IS A CORRECT OUTPUT. You MAY return an empty readings "
        "array ({\"readings\": []}). Returning NO readings is the right result when:\n"
        "- the user's verbatim words do not specifically support any reading kind for "
        "THIS concept,\n"
        "- the function/belief/origin would be a population-average guess rather than "
        "this user's own specifics,\n"
        "- you would have to invent psychology to produce a reading.\n"
        "'Insufficient evidence to ground a reading' is a complete and honest output. "
        "Do NOT produce a low-confidence speculative reading instead — return empty.\n"
    )
    cat = ""
    if categories:
        cat = (
            "\nTag 'function' and 'belief' readings with a `category` from this "
            "fixed list (a metadata index, NOT the statement):\n"
            + "\n".join(f"  - {c}" for c in categories)
            + "\nThe list is the deployment's configured families and nothing else; a "
            "reading that fits none of them belongs in the uncategorized entry or "
            "\"\" — NEVER stretch a family to cover a reading it does not actually "
            'describe. If none clearly fits, use "".\n'
        )
    schema = (
        "\nReturn JSON only: {\"readings\": [{\"kind\": \"function\"|\"origin\"|"
        '"belief"|"reframing", "statement": str, "category": str, '
        '"confidence": float, "what_would_change_this": str, '
        '"origin_distribution": {"instinctual": float, "learned_episodic": '
        'float, "reframing_consolidated": float} (origin only), '
        '"origin_episode": str (origin only), '
        '"presses_on": [concept names] (belief only), '
        '"context_sensitivity": float (belief only), '
        '"reframes_belief": str (reframing only — the belief statement it works '
        'around)}]}. If nothing earns a reading, return {"readings": []}.'
    )
    return base + cat + schema


async def _motif_targets(user_id: UUID) -> list[dict]:
    """
    Charged nodes still missing a function or origin reading, ranked by
    departure-from-baseline. Returns [{id, name, etype, salience, valence, have}].
    """
    async with get_session() as session:
        baseline = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE NOT n.entity_type IN $skip
            RETURN avg(coalesce(n.salience_score_mean, 0)) AS am,
                   avg(coalesce(n.valence_score_mean, 0)) AS vm
            """,
            uid=str(user_id),
            skip=_NON_MOTIFABLE,
        )
        brow = await baseline.single()
        user_am = float(brow["am"]) if brow and brow["am"] is not None else 0.0
        user_vm = float(brow["vm"]) if brow and brow["vm"] is not None else 0.0

        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE NOT n.entity_type IN $skip
              AND coalesce(n.salience_score_mean, n.salience_score, 0) >= $thr
              AND n.mention_count >= 3
            OPTIONAL MATCH (i:Interpretation {user_id: $uid})
            WHERE i.status <> 'rejected'
              AND i.kind IN ['function', 'origin', 'belief', 'reframing']
              AND n.id IN coalesce(i.attached_node_ids, [])
            WITH n, collect(DISTINCT i.kind) AS have
            WHERE NOT ('function' IN have AND 'origin' IN have)
            RETURN n.id AS id, n.name AS name, n.entity_type AS etype,
                   coalesce(n.salience_score_mean, 0) AS salience,
                   coalesce(n.valence_score_mean, 0) AS valence,
                   have
            """,
            uid=str(user_id),
            skip=_NON_MOTIFABLE,
            thr=_MOTIF_SALIENCE_THRESHOLD,
        )
        targets = [dict(r) async for r in result]

    targets.sort(
        key=lambda t: departure_score(t["salience"], t["valence"], user_am, user_vm),
        reverse=True,
    )
    return targets[:_MAX_MOTIFS_PER_RUN]


async def _existing_belief_ids(user_id: UUID) -> dict[str, str]:
    """statement → id for the user's non-rejected belief readings (reframing linking)."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'belief' AND i.status <> 'rejected'
            RETURN i.statement AS statement, i.id AS id
            """,
            uid=str(user_id),
        )
        return {r["statement"]: r["id"] async for r in result}


def _parse_motif_readings(
    items: list[dict],
    user_id: UUID,
    node_id: str,
    evidence_ids: list[str],
    existing_kinds: list[str],
    belief_ids: dict[str, str],
    function_statements: set[str],
) -> list[Interpretation]:
    """
    Map the model's readings into Interpretation rows. Beliefs resolve first so
    reframing readings in the same batch can link to them; a reframing naming
    an unknown belief creates that belief implicitly (low confidence) — the link
    is the load-bearing part. Kinds the node already has are skipped.
    """
    out: list[Interpretation] = []
    new_beliefs: dict[str, Interpretation] = {}

    def _clamped(item: dict) -> float:
        return min(max(float(item.get("confidence", 0.5)), 0.4), 0.7)

    # Pass 1: beliefs (so subversions can point at them).
    for item in items:
        if (item.get("kind") or "") != "belief":
            continue
        statement = (item.get("statement") or "").strip()
        if not statement or statement in belief_ids or "belief" in existing_kinds:
            continue
        interp = Interpretation(
            user_id=user_id,
            statement=statement,
            kind=InterpretationKind.BELIEF,
            category=_canonical_category(
                item.get("category") or "", APP_CONFIG.nomothetic_categories),
            what_would_change_this=(item.get("what_would_change_this") or "").strip(),
            presses_on=[str(p)[:80] for p in (item.get("presses_on") or [])][:8],
            context_sensitivity=min(max(float(item.get("context_sensitivity", 0.5)), 0.0), 1.0),
            attached_node_ids=[node_id],
            evidence=evidence_ids,
            confidence=_clamped(item),
        )
        new_beliefs[statement] = interp
        out.append(interp)

    # Pass 2: everything else.
    for item in items:
        kind_raw = (item.get("kind") or "").strip().lower()
        if kind_raw == "belief":
            continue
        if kind_raw not in {"function", "origin", "reframing"}:
            continue
        if kind_raw in existing_kinds:
            continue
        statement = (item.get("statement") or "").strip()
        if not statement:
            continue
        if kind_raw == "function":
            # C1: a 'function' duplicating one the user already has (on any node, or
            # earlier in this run) is the generic-repeat the dumps surfaced — skip it.
            norm = _norm_statement(statement)
            if norm in function_statements:
                continue
            function_statements.add(norm)

        interp = Interpretation(
            user_id=user_id,
            statement=statement,
            kind=InterpretationKind(kind_raw),
            category=_canonical_category(
                item.get("category") or "", APP_CONFIG.nomothetic_categories),
            what_would_change_this=(item.get("what_would_change_this") or "").strip(),
            attached_node_ids=[node_id],
            evidence=evidence_ids,
            confidence=_clamped(item),
        )

        if kind_raw == "origin":
            dist = item.get("origin_distribution") or {}
            interp.origin_innate = min(max(float(dist.get("instinctual", 0)), 0.0), 1.0)
            interp.origin_learned = min(
                max(float(dist.get("learned_episodic", 0)), 0.0), 1.0
            )
            interp.origin_reframing = min(
                max(float(dist.get("reframing_consolidated", 0)), 0.0), 1.0
            )
            interp.origin_episode = (item.get("origin_episode") or "").strip()

        if kind_raw == "reframing":
            target = (item.get("reframes_belief") or "").strip()
            if target in new_beliefs:
                interp.reframes_belief_id = str(new_beliefs[target].id)
            elif target in belief_ids:
                interp.reframes_belief_id = belief_ids[target]
            elif target:
                # The mechanism names a belief we don't hold yet — create it; the
                # link is what the explanation product needs (§3).
                implied = Interpretation(
                    user_id=user_id,
                    statement=target,
                    kind=InterpretationKind.BELIEF,
                    attached_node_ids=[node_id],
                    evidence=evidence_ids,
                    confidence=0.45,
                )
                new_beliefs[target] = implied
                out.append(implied)
                interp.reframes_belief_id = str(implied.id)

        out.append(interp)

    return out


async def reflect_motifs(user_id: UUID) -> int:
    """
    Per-motif typed readings (§3): for the most baseline-departing high-salience
    nodes still missing function/origin readings, ask the utility model for the
    coexisting readings and persist them. Returns the count created.
    """
    targets = await _motif_targets(user_id)
    if not targets:
        return 0

    system = _build_motif_reflection_system(APP_CONFIG.nomothetic_categories)
    belief_ids = await _existing_belief_ids(user_id)
    function_statements = await _existing_function_statements(user_id)  # C1 lexical pre-filter
    function_embeddings = await _existing_function_embeddings(user_id)   # C2 cosine dedup
    created = 0

    for t in targets:
        from services import graph_service, tier_3_gate

        # Tier-3 gate (three-tier model §Tier 3 — gating rule). Tier-1 and tier-2 are
        # unaffected; only the tier-3 reflection abstains on a node that
        # lacks the grounding to attempt a psychological reading honestly.
        if not await tier_3_gate.is_grounded(user_id, t["id"]):
            logger.info(
                "tier_3_gate_abstained",
                extra={"user_id": str(user_id), "node_id": t["id"]},
            )
            continue

        mentions = await graph_service.get_node_mentions(user_id, t["id"], limit=10)
        if not mentions:
            continue
        cooc = await graph_service.get_cooccurring_nodes(user_id, t["id"], limit=8)
        cooc_names = [n.name for n, _ in cooc]
        evidence_ids = [str(m.id) for m in mentions[:5]]

        user_content = (
            f"Motif: {t['name']} (type: {t['etype']})\n"
            f"Often appears alongside: {', '.join(cooc_names) or '(nothing yet)'}\n"
            f"What the user has said (verbatim):\n"
            + "\n".join(f"- {m.text}" for m in mentions if m.text)
        )
        try:
            raw = await chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
                model=APP_CONFIG.reflection_model_resolved,
                response_format={"type": "json_object"},
                temperature=0.4,
            )
            data = json.loads(_strip_fence(raw))
            items = data.get("readings", []) if isinstance(data, dict) else []
        except Exception:
            logger.warning("motif reflection parse failure", extra={"node_id": t["id"]})
            continue

        readings = _parse_motif_readings(
            items[:4], user_id, t["id"], evidence_ids, t.get("have") or [],
            belief_ids, function_statements,
        )
        for interp in readings:
            if interp.kind == InterpretationKind.FUNCTION:
                # C2: cosine dedup — skip a function reading that PARAPHRASES an
                # existing one (the lexical check only catches verbatim repeats).
                emb = await embedding.embed(interp.statement)
                if any(embedding.cosine(emb, e) >= APP_CONFIG.reading_dedup_threshold
                       for e in function_embeddings):
                    continue
                function_embeddings.append(emb)
            await save_interpretation(interp)
            if interp.kind == InterpretationKind.BELIEF:
                belief_ids[interp.statement] = str(interp.id)
            created += 1

    if created:
        logger.info(
            "motif_readings_created",
            extra={"user_id": str(user_id), "count": created},
        )
    return created


# --------------------------------------------------------------------------- #
# Surfacing + response (the efficacy loop)
# --------------------------------------------------------------------------- #

async def get_surfaceable(user_id: UUID, limit: int = 5) -> list[Interpretation]:
    """
    Candidate interpretations at/above the surface threshold not yet shown.
    Marks the returned ones surfaced so they aren't re-shown every poll.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.confidence >= $thr
              AND coalesce(i.user_response, '') = ''
              AND i.status IN ['candidate', 'surfaced']
            RETURN i ORDER BY i.confidence DESC LIMIT $limit
            """,
            uid=str(user_id),
            thr=_SURFACE_THRESHOLD,
            limit=limit,
        )
        interps = [Interpretation(**r["i"]) async for r in result]

        if interps:
            await session.run(
                """
                MATCH (i:Interpretation {user_id: $uid})
                WHERE i.id IN $ids
                SET i.status = 'surfaced', i.surfaced_at = $now, i.updated_at = $now
                """,
                uid=str(user_id),
                ids=[str(i.id) for i in interps],
                now=_now(),
            )
    return interps


async def respond(
    user_id: UUID, interpretation_id: UUID, response: UserResponse, note: str = ""
) -> bool:
    """
    Record the user's affirm/reject/qualify — the dominant confidence signal and
    the production efficacy score. Returns True if the interpretation was found.
    """
    if response == UserResponse.AFFIRMED:
        status, confidence = InterpretationStatus.AFFIRMED, 1.0
    elif response == UserResponse.REJECTED:
        status, confidence = InterpretationStatus.REJECTED, 0.0
    else:
        status, confidence = InterpretationStatus.QUALIFIED, None

    sets = ["i.status = $status", "i.user_response = $resp", "i.user_note = $note",
            "i.updated_at = $now"]
    params: dict = {
        "uid": str(user_id),
        "iid": str(interpretation_id),
        "status": status.value,
        "resp": response.value,
        "note": note,
        "now": _now(),
    }
    if confidence is not None:
        sets.append("i.confidence = $conf")
        params["conf"] = confidence

    async with get_session() as session:
        result = await session.run(
            f"""
            MATCH (i:Interpretation {{id: $iid, user_id: $uid}})
            SET {", ".join(sets)}
            RETURN i.id AS id
            """,
            **params,
        )
        return (await result.single()) is not None


async def reinforce(
    user_id: UUID, interpretation_ids: list, delta: float = 0.15
) -> int:
    """
    Indirect confidence signal, SIGNED. Positive: a 'checked' generation (B3) or a
    probe the user took up nudges the readings that fed it UP. Negative: a probe
    landing flat (uptake 'passed') nudges the function hypothesis DOWN — the §5.1
    reaction-loop error correction; a wrong function mispredicts its neighborhood
    and must move (§7 re-derivation). Gentler than a direct affirm/reject; clamped
    to [0.05, 0.95] so only the explicit respond() loop can saturate either end.
    Returns how many interpretations were touched.
    """
    ids = [str(i) for i in (interpretation_ids or [])]
    if not ids:
        return 0
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.id IN $ids
            SET i.confidence = CASE
                    WHEN coalesce(i.confidence, 0.5) + $delta > 0.95 THEN 0.95
                    WHEN coalesce(i.confidence, 0.5) + $delta < 0.05 THEN 0.05
                    ELSE coalesce(i.confidence, 0.5) + $delta END,
                i.updated_at = $now
            RETURN count(i) AS c
            """,
            uid=str(user_id),
            ids=ids,
            delta=delta,
            now=_now(),
        )
        row = await result.single()
        return int(row["c"]) if row else 0
