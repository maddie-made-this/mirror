"""
Bridge detection.

Bridges are the high-value, paid-insight structures: short connections linking
two otherwise-separate thematic clusters. Detected topologically (betweenness +
inter-community edges) over the same networkx graph clustering uses, then phrased
by the LLM into a sourced, rejectable hypothesis and emitted as a :Interpretation
of kind 'bridge'. Run from the scheduler after clustering.
"""

import json
import logging
import re
from uuid import UUID

import networkx as nx

from config.loader import APP_CONFIG
from db.neo4j import get_session
from llm.client import chat
from schemas.interpretation import Interpretation, InterpretationKind
from services import embedding
from services.clustering import _load_graph
from services.interpretation import _strip_fence, save_interpretation

logger = logging.getLogger(__name__)

_MAX_BRIDGES_PER_RUN = 3


def _clean_bridge(s: str) -> str:
    """
    Parse-time backstop for the bridge phrasing: cheap models sometimes still
    leak template structure despite the prompt. Drop any '<theme A>' angle-bracket
    placeholders, and rewrite an 'A / B' slash (offering two readings) into prose.
    """
    s = re.sub(r"<[^>]*>", "", s)              # drop <placeholder> tokens
    s = re.sub(r"\(\s*(in\s*)?\)", "", s)      # clean up now-empty "(in )" / "()"
    s = re.sub(r"\s*/\s*", " or ", s)          # "same thread / in tension" -> "... or ..."
    return re.sub(r"\s+", " ", s).strip()



# Kept as a module constant (matching tier_2_matcher._MATCHER_SYSTEM and friends)
# so the voice invariant below is testable rather than buried in a call.
_BRIDGE_SYSTEM = (
    "You name a connection bridging two themes in a person's "
    "map, as ONE natural, sourced, rejectable question. Use the "
    "ACTUAL concept names given below — NEVER placeholders like "
    "'X', 'Y', or '<theme>'. Write a sentence a real person "
    "would say: name the two concrete things and the felt "
    "thread between them, then invite a look. Do NOT "
    "use a slash to offer two readings ('same thread / in "
    "tension') — commit to one.\n"
    "PERSON: write ABOUT the person in a stable THIRD person "
    "('they', 'their'), never 'you' or 'your'. Every other "
    "reading kind is third person because those statements are "
    "injected into a system prompt where 'you' addresses the "
    "MODEL; a bridge that says 'you' would render the same card "
    "pane in two different grammatical persons. Use neutral "
    "reference — never a guessed gendered pronoun.\n"
    "For example: 'The pull they describe in debugging and in "
    "editing prose might be the same thing — worth a look?'. "
    "Return JSON only: "
    '{"statement": str, "inferential_step": str}.'
)


async def _node_clusters(user_id: UUID) -> tuple[dict[str, str], dict[str, str]]:
    """Return ({node_id: cluster_id}, {cluster_id: label}) for this user."""
    async with get_session() as session:
        nres = await session.run(
            """
            MATCH (n:Node {user_id: $uid}) WHERE n.cluster_id IS NOT NULL
            RETURN n.id AS id, n.cluster_id AS cid
            """,
            uid=str(user_id),
        )
        node_cluster = {r["id"]: r["cid"] async for r in nres}
        cres = await session.run(
            "MATCH (c:Cluster {user_id: $uid}) RETURN c.id AS id, c.label AS label",
            uid=str(user_id),
        )
        labels = {r["id"]: (r["label"] or r["id"]) async for r in cres}
    return node_cluster, labels


async def _existing_bridge_embeddings(user_id: UUID) -> list[list[float]]:
    """Embeddings of existing (non-rejected) bridge statements, for cosine dedup (C2).
    Replaces the cluster-id-pair key, which churned each run and let ~24 rewordings of
    one connection through."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'bridge' AND i.status <> 'rejected'
            RETURN i.statement AS statement
            """,
            uid=str(user_id),
        )
        stmts = [r["statement"] async for r in result if r["statement"]]
    return await embedding.embed_batch(stmts) if stmts else []


async def detect_user_bridges(user_id: UUID) -> int:
    """Find inter-cluster bridges, phrase them, persist as interpretations."""
    node_cluster, labels = await _node_clusters(user_id)
    if len(set(node_cluster.values())) < 2:
        return 0

    names, edges = await _load_graph(user_id)
    g = nx.Graph()
    g.add_nodes_from(names.keys())
    for a, b, w in edges:
        if a != b:
            g.add_edge(a, b, weight=g.get_edge_data(a, b, {}).get("weight", 0) + w)
    if g.number_of_edges() == 0:
        return 0

    betweenness = nx.betweenness_centrality(g, weight="weight")

    # Inter-community edges, ranked by the betweenness of their endpoints.
    candidates: list[tuple[float, str, str]] = []
    for a, b in g.edges():
        ca, cb = node_cluster.get(a), node_cluster.get(b)
        if ca and cb and ca != cb:
            score = betweenness.get(a, 0) + betweenness.get(b, 0)
            candidates.append((score, a, b))
    candidates.sort(reverse=True)

    existing_emb = await _existing_bridge_embeddings(user_id)  # C2 cosine dedup base
    used_clusters: set[str] = set()  # each community bridges at most once per run
    created = 0

    for score, a, b in candidates:
        if created >= _MAX_BRIDGES_PER_RUN:
            break
        ca, cb = node_cluster[a], node_cluster[b]
        pair = frozenset((ca, cb))
        # Diversity: don't hub many near-identical bridges off one community —
        # surface a few *distinct* connections rather than a repetitive fan.
        if ca in used_clusters or cb in used_clusters:
            continue
        used_clusters.add(ca)
        used_clusters.add(cb)

        try:
            raw = await chat(
                [
                    {"role": "system", "content": _BRIDGE_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Theme A: {labels.get(ca)} (linking concept: {names.get(a)})\n"
                            f"Theme B: {labels.get(cb)} (linking concept: {names.get(b)})"
                        ),
                    },
                ],
                model=APP_CONFIG.utility_model_resolved,
                response_format={"type": "json_object"},
                temperature=0.4,
            )
            data = json.loads(_strip_fence(raw))
            statement = _clean_bridge((data.get("statement") or "").strip())
        except Exception:
            logger.warning("bridge phrasing failed", extra={"pair": list(pair)})
            continue
        if not statement:
            continue

        # C2: cosine dedup on the bridge TEXT (replaces the churning cluster-id key).
        bridge_emb = await embedding.embed(statement)
        if any(embedding.cosine(bridge_emb, e) >= APP_CONFIG.bridge_dedup_threshold
               for e in existing_emb):
            logger.info("skipping near-duplicate bridge", extra={"pair": list(pair)})
            continue
        existing_emb.append(bridge_emb)

        await save_interpretation(
            Interpretation(
                user_id=user_id,
                statement=statement,
                kind=InterpretationKind.BRIDGE,
                inferential_step=(data.get("inferential_step") or "").strip(),
                attached_node_ids=[a, b],
                attached_cluster_ids=[ca, cb],
                evidence=[a, b],
                # Bridges are the high-value, cross-community "paid" insight —
                # rank them above within-cluster patterns/tensions when surfacing.
                confidence=0.75,
            )
        )
        created += 1

    if created:
        logger.info("bridges_created", extra={"user_id": str(user_id), "count": created})
    return created
