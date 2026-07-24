import itertools
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from slugify import slugify

from config.loader import APP_CONFIG
from db.neo4j import get_session
from schemas.graph import GraphContext, GraphEdge, GraphNode, Mention

logger = logging.getLogger(__name__)


def make_node_id(entity_type: str, name: str) -> str:
    return f"{entity_type}:{slugify(name)}"


async def ensure_self_node(user_id: UUID, display_name: str) -> str:
    """
    Idempotent — call once per message before the ingest loop.
    Creates the canonical self-node for this user if it doesn't exist, or
    refreshes its name if the user changed their display name.
    Returns the canonical node_id: "self:{user_id}".
    """
    node_id = f"self:{user_id}"
    async with get_session() as session:
        await session.run(
            """
            MERGE (n:Node {id: $id, user_id: $uid})
            ON CREATE SET
              n.name = $name,
              n.entity_type = 'self',
              n.mention_count = 0,
              n.spontaneous_mention_count = 0,
              n.stability_score = 0.1,
              n.valence = 'neutral',
              n.valence_score = 0.0,
              n.valence_score_last = 0.0,
              n.valence_score_mean = 0.0,
              n.valence_score_min = 0.0,
              n.valence_score_max = 0.0,
              n.salience_score = 0.0,
              n.salience_score_last = 0.0,
              n.salience_score_mean = 0.0,
              n.knowledge_source = 'user_stated',
              n.first_session = 0,
              n.last_session = 0,
              n.created_at = datetime(),
              n.last_mentioned_at = datetime(),
              n.user_id = $uid
            ON MATCH SET n.name = $name
            """,
            id=node_id, uid=str(user_id), name=display_name,
        )
    return node_id


async def get_user_graph(
    user_id: UUID,
    *,
    limit: int = 500,
    min_mentions: int = 1,
    entity_types: list[str] | None = None,
    include_negated: bool = False,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """
    Return nodes and edges for the visualization endpoint.

    Nodes are filtered by mention count and (optionally) entity type, ordered by
    mention count and capped at `limit`. Edges are restricted to the returned
    node set so the client never receives a dangling edge.
    """
    async with get_session() as session:
        node_result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.mention_count >= $min_mentions
              AND ($entity_types IS NULL OR n.entity_type IN $entity_types)
            RETURN n
            ORDER BY n.mention_count DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            min_mentions=min_mentions,
            entity_types=entity_types,
            limit=limit,
        )
        # Build defensively: one malformed record (e.g. an edge written by an
        # older path, or a node with a cross-mode entity type) must never 500
        # the whole map — skip it and log.
        nodes = []
        async for record in node_result:
            try:
                nodes.append(GraphNode(**record["n"]))
            except Exception:
                logger.warning("skipping unparseable node", extra={"raw": dict(record["n"])})
        node_ids = [n.id for n in nodes]

        edges: list[GraphEdge] = []
        if node_ids:
            edge_result = await session.run(
                """
                MATCH (src:Node {user_id: $uid})-[e:EDGE]->(tgt:Node {user_id: $uid})
                WHERE src.id IN $ids AND tgt.id IN $ids
                  AND ($include_negated OR NOT coalesce(e.is_negated, false))
                RETURN e
                """,
                uid=str(user_id),
                ids=node_ids,
                include_negated=include_negated,
            )
            async for record in edge_result:
                try:
                    edges.append(GraphEdge(**record["e"]))
                except Exception:
                    logger.warning("skipping unparseable edge")

    # NOTE: co-occurrence (:CO_OCCURS) is deliberately NOT returned here. It drives
    # CLUSTERING only (read straight from Neo4j in services/clustering.py) and must
    # stay OUT of the layout — a near-complete co-occurrence subgraph turns the force
    # sim into a hairball (map spec §1B). The map fetches it separately, render-only,
    # via get_cooccurrence_edges + the graph endpoint's include_cooccurrence flag.
    return nodes, edges


async def get_cooccurrence_edges(
    user_id: UUID, node_ids: list[str], limit: int = 1500
) -> list[dict]:
    """
    Materialized :CO_OCCURS edges among the given node set, for the map's optional
    faint co-occurrence layer. Lightweight (source_id/target_id/weight only) — these
    aren't semantic :EDGE relationships, so they don't carry causal_class etc.
    Ordered by weight desc and capped so a dense graph can't hairball the client.
    """
    if not node_ids:
        return []
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (a:Node {user_id: $uid})-[c:CO_OCCURS]->(b:Node {user_id: $uid})
            WHERE a.id IN $ids AND b.id IN $ids
            RETURN a.id AS source_id, b.id AS target_id, coalesce(c.weight, 1.0) AS weight
            ORDER BY weight DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            ids=node_ids,
            limit=limit,
        )
        return [
            {
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "weight": float(r["weight"]),
            }
            async for r in result
        ]


# Reduced reinforcement weight for an OFFERED-and-ACCEPTED directional-chip tap vs a
# volunteered 'check' (1.0) — a tap is weaker evidence than a volunteered ask
# (anti-passivity, reshape §P0.3A/§9.2). CONTESTABLE.
CHIP_REINFORCE_WEIGHT = 0.3


async def reinforce_nodes(user_id: UUID, node_ids: list[str], weight: float = 1.0) -> int:
    """
    Positive direct-feedback signal (B3): the user 'checked' a generation these nodes fed
    (weight 1.0), or tapped an offered directional chip (weight 0.3 — weaker evidence,
    reshape §P0.3A). Bump a WEIGHTED reinforcement counter on each — a dominant signal
    (A1.4), distinct from extraction/inference, available to future ranking/steering.
    Returns how many nodes were touched.
    """
    if not node_ids:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.id IN $ids
            SET n.reinforced_count = coalesce(n.reinforced_count, 0) + $weight,
                n.last_reinforced_at = $now
            RETURN count(n) AS c
            """,
            uid=str(user_id),
            ids=node_ids,
            now=now,
            weight=weight,
        )
        row = await result.single()
        return int(row["c"]) if row else 0


_NODE_AGGREGATE_FIELDS = {
    "created_at",
    "last_mentioned_at",
    "mention_count",
    "spontaneous_mention_count",
    "source_quotes",
    "valence",
    "valence_score",
    "valence_score_last",
    "valence_score_mean",
    "valence_score_min",
    "valence_score_max",
    "salience_score",
    "salience_score_last",
    "salience_score_mean",
}


async def upsert_node(
    tx,
    node: GraphNode,
    user_id: UUID,
    *,
    spontaneous: bool = False,
) -> tuple[GraphNode, bool]:
    """
    Merge on node.id + user_id within the supplied Neo4j transaction.
    Returns (node, created).

    Valence is tracked as four aggregates — last, mean, min, max — and salience as
    last and mean. The mean is maintained with a single-pass Welford update so we
    never need to re-scan historical mentions. Voice and tense are preserved
    upstream (see normalize_predicate); this only aggregates affect.
    """
    now = datetime.now(timezone.utc).isoformat()
    spontaneous_int = 1 if spontaneous else 0
    v = node.valence_score
    a = node.salience_score

    result = await tx.run(
        """
        MERGE (n:Node {id: $id, user_id: $uid})
        ON CREATE SET
            n += $props,
            n.created_at = $now,
            n.last_mentioned_at = $now,
            n.mention_count = 1,
            n.spontaneous_mention_count = $spontaneous,
            n.valence = $valence,
            n.valence_score = $v,
            n.valence_score_last = $v,
            n.valence_score_mean = $v,
            n.valence_score_min = $v,
            n.valence_score_max = $v,
            n.salience_score = $a,
            n.salience_score_last = $a,
            n.salience_score_mean = $a,
            n.user_id = $uid
        ON MATCH SET
            n.valence_score_mean = n.valence_score_mean
                + ($v - n.valence_score_mean) / (n.mention_count + 1),
            n.salience_score_mean = n.salience_score_mean
                + ($a - n.salience_score_mean) / (n.mention_count + 1),
            n.valence_score_min = CASE WHEN $v < n.valence_score_min THEN $v
                                       ELSE n.valence_score_min END,
            n.valence_score_max = CASE WHEN $v > n.valence_score_max THEN $v
                                       ELSE n.valence_score_max END,
            n.valence_score_last = $v,
            n.valence_score = $v,
            n.valence = $valence,
            n.salience_score_last = $a,
            n.salience_score = $a,
            n.mention_count = n.mention_count + 1,
            n.spontaneous_mention_count = n.spontaneous_mention_count + $spontaneous,
            n.last_mentioned_at = $now,
            n.last_session = $last_session
        RETURN n, (n.mention_count = 1) AS created
        """,
        id=node.id,
        uid=str(user_id),
        props=node.model_dump(mode="json", exclude=_NODE_AGGREGATE_FIELDS),
        now=now,
        last_session=node.last_session,
        v=v,
        a=a,
        valence=node.valence.value,
        spontaneous=spontaneous_int,
    )
    record = await result.single()
    return GraphNode(**record["n"]), record["created"]


async def bump_node_aggregates_tx(
    tx,
    node_id: str,
    user_id: UUID,
    *,
    valence: float,
    salience: float,
    valence_enum: str,
    session_number: int,
    spontaneous: bool = False,
) -> GraphNode:
    """
    Increment the aggregate stats on an already-existing node without a full
    re-upsert. Called when the cluster-aware ingest resolves a proposition to an
    existing node rather than creating a new one — avoids overwriting the node's
    canonical name with the surface form from this particular mention.

    Raises RuntimeError if the node does not exist (Qdrant/Neo4j out of sync).
    """
    now = datetime.now(timezone.utc).isoformat()
    result = await tx.run(
        """
        MATCH (n:Node {id: $id, user_id: $uid})
        SET
            n.valence_score_mean = n.valence_score_mean
                + ($v - n.valence_score_mean) / (n.mention_count + 1),
            n.salience_score_mean = n.salience_score_mean
                + ($a - n.salience_score_mean) / (n.mention_count + 1),
            n.valence_score_min = CASE WHEN $v < n.valence_score_min THEN $v
                                       ELSE n.valence_score_min END,
            n.valence_score_max = CASE WHEN $v > n.valence_score_max THEN $v
                                       ELSE n.valence_score_max END,
            n.valence_score_last = $v,
            n.valence_score = $v,
            n.valence = $valence,
            n.salience_score_last = $a,
            n.salience_score = $a,
            n.mention_count = n.mention_count + 1,
            n.spontaneous_mention_count = n.spontaneous_mention_count + $spontaneous,
            n.last_mentioned_at = $now,
            n.last_session = $session
        RETURN n
        """,
        id=node_id, uid=str(user_id),
        v=valence, a=salience, valence=valence_enum,
        session=session_number, now=now,
        spontaneous=1 if spontaneous else 0,
    )
    record = await result.single()
    if record is None:
        raise RuntimeError(
            f"bump_node_aggregates_tx: node '{node_id}' not found for user {user_id}"
        )
    return GraphNode(**record["n"])


async def upsert_edge(tx, edge: GraphEdge, user_id: UUID) -> tuple[GraphEdge, bool]:
    """
    Merge on source_id + target_id + relation_type + user_id within the supplied
    transaction. Returns (edge, created). Increments weight on match. The closed
    relation taxonomy dedups by exact match — no embedding-similarity step.
    """
    now = datetime.now(timezone.utc).isoformat()
    rel_type = edge.relation_type.value

    result = await tx.run(
        """
        MATCH (src:Node {id: $src_id, user_id: $uid})
        MATCH (tgt:Node {id: $tgt_id, user_id: $uid})
        MERGE (src)-[e:EDGE {relation_type: $rel_type, user_id: $uid}]->(tgt)
        ON CREATE SET
            e += $props,
            e.relation_type = $rel_type,
            e.created_at = $now,
            e.weight = 1.0,
            e.user_id = $uid
        ON MATCH SET
            e.weight = e.weight + 1.0,
            e.last_seen_at = $now,
            e.last_session = $last_session
        RETURN e, (e.weight = 1.0) AS created
        """,
        src_id=edge.source_id,
        tgt_id=edge.target_id,
        rel_type=rel_type,
        uid=str(user_id),
        props=edge.model_dump(
            mode="json",
            exclude={"created_at", "weight", "relation_type"},
        ),
        now=now,
        last_session=edge.last_session,
    )
    record = await result.single()
    return GraphEdge(**record["e"]), record["created"]


async def create_mention(
    tx,
    mention: Mention,
    subject_node_id: str,
    object_node_id: str,
) -> Mention:
    """
    Create a :Mention node and link it to subject + object via [:REFERENCES].
    Idempotent on Mention.id. Runs inside the supplied transaction.
    """
    await tx.run(
        """
        MERGE (m:Mention {id: $id, user_id: $uid})
        ON CREATE SET m += $props, m.created_at = $now
        WITH m
        MATCH (subj:Node {id: $subj_id, user_id: $uid})
        MATCH (obj:Node {id: $obj_id, user_id: $uid})
        MERGE (m)-[:REFERENCES {role: 'subject'}]->(subj)
        MERGE (m)-[:REFERENCES {role: 'object'}]->(obj)
        """,
        id=str(mention.id),
        uid=str(mention.user_id),
        subj_id=subject_node_id,
        obj_id=object_node_id,
        props=mention.model_dump(
            mode="json", exclude={"id", "created_at", "user_id"}
        ),
        now=mention.created_at.isoformat(),
    )
    return mention


async def bump_cooccurrence_edges(
    node_ids: list[str] | set[str],
    user_id: UUID,
    session_number: int,
) -> None:
    """
    Materialize symmetric co-occurrence: for every pair of nodes touched in the
    same turn, MERGE a :CO_OCCURS edge (canonical-ordered so each pair has one
    edge) and increment its weight. Distinct from the semantic :EDGE — clustering
    (services/clustering.py) reads both together. Cheap on-the-fly co-occurrence
    via Mention traversal (get_cooccurring_nodes) is kept for ad-hoc queries; this
    materializes it so community detection doesn't re-traverse Mentions each run.
    """
    ids = sorted(set(node_ids))
    if len(ids) < 2:
        return
    pairs = [{"a": a, "b": b} for a, b in itertools.combinations(ids, 2)]
    now = datetime.now(timezone.utc).isoformat()
    async with get_session() as session:
        await session.run(
            """
            UNWIND $pairs AS pair
            MATCH (a:Node {id: pair.a, user_id: $uid})
            MATCH (b:Node {id: pair.b, user_id: $uid})
            MERGE (a)-[c:CO_OCCURS {user_id: $uid}]->(b)
            ON CREATE SET c.weight = 1.0, c.created_at = $now, c.last_session = $session
            ON MATCH  SET c.weight = c.weight + 1.0, c.last_session = $session
            """,
            pairs=pairs,
            uid=str(user_id),
            now=now,
            session=session_number,
        )


async def get_node_mentions(
    user_id: UUID, node_id: str, limit: int = 20
) -> list[Mention]:
    """Return the most recent mentions that reference the given node."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (m:Mention {user_id: $uid})-[:REFERENCES]->(n:Node {id: $nid})
            RETURN DISTINCT m
            ORDER BY m.created_at DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            nid=node_id,
            limit=limit,
        )
        return [Mention(**record["m"]) async for record in result]


async def get_cooccurring_nodes(
    user_id: UUID, node_id: str, limit: int = 10
) -> list[tuple[GraphNode, int]]:
    """Nodes most often co-mentioned with the given node."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n1:Node {id: $nid, user_id: $uid})<-[:REFERENCES]-(m:Mention)
                  -[:REFERENCES]->(n2:Node {user_id: $uid})
            WHERE n2.id <> $nid
            RETURN n2, count(DISTINCT m) AS cooc
            ORDER BY cooc DESC
            LIMIT $limit
            """,
            nid=node_id,
            uid=str(user_id),
            limit=limit,
        )
        return [
            (GraphNode(**record["n2"]), record["cooc"]) async for record in result
        ]


async def get_top_predicates(user_id: UUID, limit: int = 15) -> list[str]:
    """
    Return the user's most-used natural-language predicate phrases, descending by
    frequency. Read from :Mention nodes — edges now carry only the canonical
    relation_type, while the natural phrase lives on the mention.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (m:Mention {user_id: $uid})
            WITH coalesce(m.predicate, '') AS rel, count(*) AS c
            WHERE rel <> ''
            RETURN rel
            ORDER BY c DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            limit=limit,
        )
        return [record["rel"] async for record in result]


async def get_edges_between(node_ids: list[str], user_id: UUID) -> list[GraphEdge]:
    """
    Return all edges between these nodes, INCLUDING negated ones.
    Negated edges are included so the LLM can reason with them (C4).
    The visualisation endpoint (get_user_graph) filters them out separately.

    source_id/target_id are taken from the matched node TOPOLOGY, not the edge
    properties — the topology is authoritative and some older edges were written
    without those properties stored. And, like get_user_graph, each edge is built
    defensively: one malformed edge must never throw and blank out the whole
    GraphContext (which silently starved flow-1 grounding + flow-2 injection).
    """
    if not node_ids:
        return []
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (src:Node {user_id: $uid})-[e:EDGE]->(tgt:Node {user_id: $uid})
            WHERE src.id IN $ids AND tgt.id IN $ids
            RETURN e, src.id AS sid, tgt.id AS tid
            """,
            uid=str(user_id),
            ids=node_ids,
        )
        edges: list[GraphEdge] = []
        async for record in result:
            try:
                data = dict(record["e"])
                data["source_id"] = record["sid"]
                data["target_id"] = record["tid"]
                edges.append(GraphEdge(**data))
            except Exception:
                logger.warning("skipping unparseable edge in get_edges_between")
        return edges


async def get_dormant_nodes(
    user_id: UUID,
    current_session: int,
    dormancy_threshold: int = 5,
    min_mention_count: int = 3,
) -> list[GraphNode]:
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.mention_count >= $min_mentions
              AND (n.last_session IS NULL OR $current - n.last_session >= $threshold)
            RETURN n
            ORDER BY n.mention_count DESC
            LIMIT 5
            """,
            uid=str(user_id),
            min_mentions=min_mention_count,
            current=current_session,
            threshold=dormancy_threshold,
        )
        return [GraphNode(**record["n"]) async for record in result]


async def get_user_clusters(user_id: UUID) -> list[dict]:
    """Return this user's detected clusters (id, label, size), largest first."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (c:Cluster {user_id: $uid})
            RETURN c.id AS id, c.label AS label, c.size AS size
            ORDER BY c.size DESC
            """,
            uid=str(user_id),
        )
        return [
            {"id": r["id"], "label": r["label"], "size": r["size"]}
            async for r in result
        ]


async def get_cluster_similarity(user_id: UUID) -> list[dict]:
    """
    Inter-community semantic adjacency: [{a, b, score}] from centroid cosine
    (see services.cluster_similarity). Scalars only — never the centroids/vectors.
    The frontend uses it to pull semantically near communities spatially closer.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (x:Cluster {user_id: $uid})-[r:CLUSTER_SIMILAR]->(y:Cluster)
            RETURN x.id AS a, y.id AS b, r.score AS score
            """,
            uid=str(user_id),
        )
        return [
            {"a": r["a"], "b": r["b"], "score": float(r["score"])}
            async for r in result
        ]


async def get_overlay_interpretations(
    user_id: UUID,
    *,
    min_confidence: float = 0.6,
    limit: int = 6,
) -> list[dict]:
    """
    High-confidence, not-rejected interpretations to render as map overlays:
    region markers (one attached cluster) and bridge connections (two clusters).
    Capped so the map reveals a few striking insights, not a tentative swarm.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.confidence >= $minc
              AND i.status IN ['candidate', 'surfaced', 'affirmed', 'qualified']
              AND coalesce(i.attached_cluster_ids, []) <> []
            RETURN i.id AS id, i.statement AS statement, i.kind AS kind,
                   i.confidence AS confidence,
                   i.attached_cluster_ids AS cluster_ids
            ORDER BY i.confidence DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            minc=min_confidence,
            limit=limit,
        )
        return [dict(r) async for r in result]


async def get_node_interpretations(user_id: UUID, node_id: str) -> list[dict]:
    """
    Interpretations that explain or cite this node — the "why" behind an inferred
    node, walked back to the reasoning. Matches the node in attached_node_ids or
    evidence, highest confidence first.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE $nid IN coalesce(i.attached_node_ids, [])
               OR $nid IN coalesce(i.evidence, [])
            RETURN i.id AS id, i.statement AS statement, i.kind AS kind,
                   i.confidence AS confidence,
                   coalesce(i.inferential_step, '') AS inferential_step
            ORDER BY i.confidence DESC
            LIMIT 5
            """,
            uid=str(user_id), nid=node_id,
        )
        return [dict(r) async for r in result]


async def get_interpretations_for_nodes(
    user_id: UUID,
    node_ids: list[str],
    *,
    min_confidence: float = 0.6,
    limit: int = 3,
) -> list[dict]:
    """
    Flow 2 (B5): the idiographic interpretations relevant to THIS turn — those that
    explain/cite any of the turn's relevant nodes (or a cluster those nodes belong
    to), high-confidence and not rejected. Returns {id, statement} for injection into
    the response prompt. The statement is the generative payload (never the category).

    Only the GENERATIVE reading kinds are injected — function (what the interest does
    for them, the prime payload), belief, pattern/tension, and the interest-model
    origin/reframing/dynamics. 'bridge' is excluded: it's a map-overlay prompt
    ("Theme A connects to Theme B — worth exploring?"), a question for the user, not
    a directive that deepens a piece. Ordered function-first, then by confidence.
    """
    if not node_ids:
        return []
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.confidence >= $minc
              AND i.status <> 'rejected'
              AND coalesce(i.kind, 'pattern') IN
                  ['angle','function','belief','reframing','origin','dynamics','pattern','tension']
              AND (
                any(nid IN coalesce(i.attached_node_ids, []) WHERE nid IN $ids)
                OR any(nid IN coalesce(i.evidence, []) WHERE nid IN $ids)
                OR EXISTS {
                    MATCH (n:Node {user_id: $uid})
                    WHERE n.id IN $ids
                      AND n.cluster_id IN coalesce(i.attached_cluster_ids, [])
                }
              )
            RETURN i.id AS id, i.statement AS statement,
                   CASE coalesce(i.kind, 'pattern')
                        WHEN 'angle' THEN 0
                        WHEN 'function' THEN 1 WHEN 'belief' THEN 2
                        WHEN 'reframing' THEN 3 ELSE 4 END AS kind_rank
            ORDER BY kind_rank ASC, i.confidence DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            ids=node_ids,
            minc=min_confidence,
            limit=limit,
        )
        return [{"id": r["id"], "statement": r["statement"]} async for r in result]


async def stamp_provenance(
    user_id: UUID,
    node_ids: list[str],
    *,
    source: str,
    elicited: str,
) -> int:
    """
    Stamp a provenance signal onto existing nodes (product reshape §1.2). Used by the
    'This story' panel correction (P2.1 — a user fixing the panel is high-value volunteered
    signal: source='conversation', elicited='volunteered') and the directional-chip accept
    path (P0.3A — source='offered_chip', elicited='offered_and_accepted'). Sets the fine
    provenance axis; `knowledge_source` (the coarse legacy anchor) is untouched. Returns the
    number of nodes touched.
    """
    if not node_ids:
        return 0
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.id IN $ids
            SET n.prov_source = $source, n.prov_elicited = $elicited
            RETURN count(n) AS c
            """,
            uid=str(user_id), ids=node_ids, source=source, elicited=elicited,
        )
        row = await result.single()
        return int(row["c"]) if row else 0


async def get_active_concepts(user_id: UUID, *, limit: int = 12) -> list[dict]:
    """The 'You' panel (P2.1): the user's most-active concept nodes (highest mention_count,
    excluding the self node), as {id, name}. A light summary read, not the full graph."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE coalesce(n.entity_type, '') <> 'self'
            RETURN n.id AS id, n.name AS name
            ORDER BY coalesce(n.mention_count, 0) DESC
            LIMIT $limit
            """,
            uid=str(user_id), limit=limit,
        )
        return [dict(r) async for r in result]


async def get_node_names(user_id: UUID, node_ids: list[str]) -> dict[str, str]:
    """Resolve node slugs → display names (P2.4 thinking view). Missing ids are omitted."""
    if not node_ids:
        return {}
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.id IN $ids
            RETURN n.id AS id, n.name AS name
            """,
            uid=str(user_id), ids=node_ids,
        )
        return {r["id"]: r["name"] async for r in result}


async def get_interpretation_statements(
    user_id: UUID, interp_ids: list[str]
) -> list[dict]:
    """Resolve interpretation ids → {id, statement, kind, confidence} (P2.4 thinking view)."""
    if not interp_ids:
        return []
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.id IN $ids
            RETURN i.id AS id, i.statement AS statement,
                   coalesce(i.kind, 'pattern') AS kind, i.confidence AS confidence
            """,
            uid=str(user_id), ids=interp_ids,
        )
        return [dict(r) async for r in result]


async def get_top_angles(user_id: UUID, *, limit: int = 5) -> list[dict]:
    """
    The 'You' panel (P2.1): this user's strongest tier-2 ANGLE readings — the felt
    character of their clusters ('what kind of pull this is'), highest confidence first,
    not rejected. Returns {id, statement, confidence}.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE coalesce(i.kind, '') = 'angle'
              AND i.status IN ['candidate', 'surfaced', 'affirmed', 'qualified']
            RETURN i.id AS id, i.statement AS statement, i.confidence AS confidence
            ORDER BY i.confidence DESC
            LIMIT $limit
            """,
            uid=str(user_id), limit=limit,
        )
        return [dict(r) async for r in result]


async def get_high_salience_unknowns(
    user_id: UUID, *, threshold: float = 0.5, limit: int = 5
) -> list[GraphNode]:
    """
    Steering candidate (flow 3): nodes the user activates around (high salience) whose
    FUNCTION is not yet understood — no kind='function' interpretation explains them.
    The tier-3 frontier: likely to land AND fills the biggest gap. Highest steering value.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.entity_type <> 'self'
              AND coalesce(n.salience_score_mean, n.salience_score, 0) >= $thr
              AND NOT EXISTS {
                MATCH (i:Interpretation {user_id: $uid})
                WHERE i.kind = 'function'
                  AND (n.id IN coalesce(i.attached_node_ids, [])
                       OR n.id IN coalesce(i.evidence, []))
              }
            RETURN n
            ORDER BY coalesce(n.salience_score_mean, n.salience_score, 0) DESC,
                     n.mention_count DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            thr=threshold,
            limit=limit,
        )
        return [GraphNode(**record["n"]) async for record in result]


async def get_function_probe_candidates(
    user_id: UUID, *, min_confidence: float = 0.6, limit: int = 5
) -> list[dict]:
    """
    §5.1 primary engine feed: credible function readings whose candidate
    configurations (generated at maintenance) are waiting to be probed.
    Returns [{id, statement, candidates, node_ids}], most confident first.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'function'
              AND i.status <> 'rejected'
              AND coalesce(i.confidence, 0) >= $minc
              AND coalesce(i.candidates, []) <> []
            RETURN i.id AS id, i.statement AS statement,
                   i.candidates AS candidates,
                   coalesce(i.attached_node_ids, []) AS node_ids
            ORDER BY i.confidence DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            minc=min_confidence,
            limit=limit,
        )
        return [dict(r) async for r in result]


async def get_node_origin_reading(user_id: UUID, node_id: str) -> dict | None:
    """
    The node's best origin reading (§6 probe-type routing): which acquisition
    route the current evidence leans toward. None if no origin reading exists.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.kind = 'origin' AND i.status <> 'rejected'
              AND $nid IN coalesce(i.attached_node_ids, [])
            RETURN i.id AS id,
                   coalesce(i.origin_innate, 0) AS instinctual,
                   coalesce(i.origin_learned, 0) AS conditioned,
                   coalesce(i.origin_reframing, 0) AS reframing
            ORDER BY i.confidence DESC
            LIMIT 1
            """,
            uid=str(user_id),
            nid=node_id,
        )
        row = await result.single()
        return dict(row) if row else None


async def get_similarity_probe_nodes(user_id: UUID, *, limit: int = 5) -> list[dict]:
    """
    §5.2 secondary engine feed: high-salience nodes whose adjacent candidates
    (similarity engine, maintenance-generated) are waiting to be probed.
    Returns [{id, name, candidates}].
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE coalesce(n.adjacent_candidates, []) <> []
            RETURN n.id AS id, n.name AS name, n.adjacent_candidates AS candidates
            ORDER BY coalesce(n.salience_score_mean, n.salience_score, 0) DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            limit=limit,
        )
        return [dict(r) async for r in result]


async def get_untested_maybe_interpretations(
    user_id: UUID, *, limit: int = 5
) -> list[dict]:
    """
    Steering candidate (flow 3): the system's low-confidence guesses not yet
    confirmed — an opening to test them gently. Returns {id, statement}.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE coalesce(i.confidence, 0.5) < 0.6
              AND i.status IN ['candidate', 'surfaced']
              AND coalesce(i.user_response, '') = ''
              AND coalesce(i.statement, '') <> ''
            RETURN i.id AS id, i.statement AS statement
            ORDER BY i.confidence DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            limit=limit,
        )
        return [{"id": r["id"], "statement": r["statement"]} async for r in result]


_READING_GROUPS = {
    "angle": "angle",          # tier-2 — the felt character of the node's cluster
    "origin": "origin",
    "function": "function",
    "dynamics": "dynamics",
    "reframing": "reframing",
    "belief": "beliefs",
}


async def get_node_readings(user_id: UUID, node_id: str) -> dict:
    """
    The explanation product (§8 / frontend §2.3): a developed motif's
    COEXISTING readings, grouped by kind, each carrying its own confidence,
    status, what-would-change-this, and the user's own words as evidence.
    Reframing readings resolve their belief statement so the panel can say
    "born as a workaround for X; now its own thing". Never collapsed.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (i:Interpretation {user_id: $uid})
            WHERE i.status <> 'rejected'
              AND ($nid IN coalesce(i.attached_node_ids, [])
                   OR $nid IN coalesce(i.evidence, [])
                   OR EXISTS {
                        MATCH (n:Node {id: $nid, user_id: $uid})
                        WHERE n.cluster_id IN coalesce(i.attached_cluster_ids, [])
                   })
            RETURN i
            ORDER BY i.confidence DESC
            """,
            uid=str(user_id),
            nid=node_id,
        )
        raw = [dict(r["i"]) async for r in result]

        # Resolve evidence ids → verbatim mention texts (node ids in the same
        # list simply don't match :Mention and drop out). Cap 3 per reading.
        evidence_ids = sorted({e for i in raw for e in (i.get("evidence") or [])})
        quotes: dict[str, str] = {}
        if evidence_ids:
            mres = await session.run(
                """
                MATCH (m:Mention {user_id: $uid}) WHERE m.id IN $ids
                RETURN m.id AS id, m.text AS text
                """,
                uid=str(user_id),
                ids=evidence_ids,
            )
            quotes = {r["id"]: r["text"] async for r in mres}

        # Resolve reframing → belief statements.
        belief_targets = sorted(
            {i["reframes_belief_id"] for i in raw if i.get("reframes_belief_id")}
        )
        belief_statements: dict[str, str] = {}
        if belief_targets:
            bres = await session.run(
                """
                MATCH (b:Interpretation {user_id: $uid}) WHERE b.id IN $ids
                RETURN b.id AS id, b.statement AS statement
                """,
                uid=str(user_id),
                ids=belief_targets,
            )
            belief_statements = {r["id"]: r["statement"] async for r in bres}

        # C3b: the stored synthesized headline (preferred over copying a reading).
        hres = await session.run(
            "MATCH (n:Node {id: $nid, user_id: $uid}) RETURN n.headline AS h",
            uid=str(user_id), nid=node_id,
        )
        hrow = await hres.single()
        stored_headline = (hrow["h"] if hrow else None) or ""

    grouped: dict[str, list[dict]] = {
        "angle": [], "origin": [], "function": [], "dynamics": [],
        "reframing": [], "beliefs": [], "other": [],
    }
    headline = stored_headline  # C3b: prefer the synthesized headline; copy is fallback
    for i in raw:
        kind = str(i.get("kind") or "pattern")
        item = {
            "id": i.get("id"),
            "kind": kind,
            "statement": i.get("statement") or "",
            "category": i.get("category") or "",
            "confidence": float(i.get("confidence") or 0.5),
            "status": i.get("status") or "candidate",
            "what_would_change_this": i.get("what_would_change_this") or "",
            "evidence_quotes": [
                quotes[e] for e in (i.get("evidence") or []) if e in quotes
            ][:3],
        }
        if kind == "origin":
            item["origin_distribution"] = {
                "instinctual": float(i.get("origin_innate") or 0),
                "learned_episodic": float(i.get("origin_learned") or 0),
                "reframing_consolidated": float(i.get("origin_reframing") or 0),
            }
            item["origin_episode"] = i.get("origin_episode") or ""
        if kind == "reframing":
            item["belief_statement"] = belief_statements.get(
                i.get("reframes_belief_id") or "", ""
            )
        if kind == "belief":
            item["presses_on"] = list(i.get("presses_on") or [])
            item["context_sensitivity"] = float(i.get("context_sensitivity") or 0.5)
        grouped[_READING_GROUPS.get(kind, "other")].append(item)

        # Headline: the strongest function statement wins; else strongest anything.
        if not headline and kind == "function":
            headline = item["statement"]
    if not headline and raw:
        headline = str(raw[0].get("statement") or "")

    return {"headline": headline, **grouped}


async def get_user_mention_entity_types(user_id: UUID) -> list[str]:
    """Every entity type present across this user's mentions, unfiltered.

    The episodic page's filter chips need a STABLE list. Deriving them from the
    currently-loaded (already-filtered, already-paginated) rows made the chips
    collapse to whatever survived the filter, so selecting one hid the rest and
    there was no way back to a second choice.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (:Mention {user_id: $uid})-[:REFERENCES]->(n:Node)
            WHERE n.entity_type IS NOT NULL AND n.entity_type <> ''
            RETURN DISTINCT n.entity_type AS entity_type
            ORDER BY entity_type
            """,
            uid=str(user_id),
        )
        return [r["entity_type"] async for r in result]


async def get_user_mentions(
    user_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    entity_types: list[str] | None = None,
    q: str = "",
) -> list[dict]:
    """
    The EPISODIC page (frontend §3.1): the user-wide verbatim record, newest
    first, filterable by entity type and text search. Each row carries the
    node(s) it fed — the receipts that make every abstraction traceable.

    `entity_types` INTERSECTS: a mention must touch a node of EVERY selected
    type, not any of them. Selecting two types narrows rather than widens, which
    is what makes stacking filters useful.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (m:Mention {user_id: $uid})
            WHERE $q = '' OR toLower(m.text) CONTAINS toLower($q)
            OPTIONAL MATCH (m)-[:REFERENCES]->(n:Node)
            WITH m, collect(DISTINCT {
                id: n.id, name: n.name, entity_type: n.entity_type
            }) AS nodes
            WHERE size($etypes) = 0
               OR all(t IN $etypes WHERE any(x IN nodes WHERE x.entity_type = t))
            RETURN m.id AS id, m.text AS text, m.predicate AS predicate,
                   coalesce(m.valence_score, 0) AS valence_score,
                   coalesce(m.salience_score, 0) AS salience_score,
                   m.session_number AS session_number,
                   m.conversation_id AS conversation_id,
                   toString(m.created_at) AS created_at,
                   nodes
            ORDER BY m.created_at DESC
            SKIP $offset LIMIT $limit
            """,
            uid=str(user_id),
            q=q,
            etypes=list(entity_types or []),
            offset=offset,
            limit=limit,
        )
        return [dict(r) async for r in result]


async def get_understanding(user_id: UUID, *, limit: int = 100) -> list[dict]:
    """
    The SEMANTIC page (frontend §3.2): the list twin of the map — motifs and
    concepts with their readings summary, high-salience/consolidated first. Same data
    as the canvas, browsable.
    """
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE NOT n.entity_type IN ['self', 'preference', 'format_rule']
            OPTIONAL MATCH (i:Interpretation {user_id: $uid})
            WHERE i.status <> 'rejected'
              AND n.id IN coalesce(i.attached_node_ids, [])
            WITH n, collect(i) AS readings
            RETURN n.id AS id, n.name AS name, n.entity_type AS entity_type,
                   n.mention_count AS mention_count,
                   coalesce(n.salience_score_mean, 0) AS salience,
                   coalesce(n.motif, false) AS motif,
                   coalesce(n.motif_confidence, 0) AS motif_confidence,
                   n.cluster_id AS cluster_id,
                   [r IN readings | {
                       id: r.id, kind: r.kind, statement: r.statement,
                       confidence: r.confidence, status: r.status
                   }] AS readings
            ORDER BY motif DESC, salience DESC, n.mention_count DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            limit=limit,
        )
        return [dict(r) async for r in result]


async def get_preference_nodes(user_id: UUID) -> list[GraphNode]:
    """Fetch all preference and format_rule nodes for this user (C3)."""
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.entity_type IN ['preference', 'format_rule']
            RETURN n
            ORDER BY n.mention_count DESC
            """,
            uid=str(user_id),
        )
        return [GraphNode(**record["n"]) async for record in result]


async def get_identity_seed(
    user_id: UUID, limit: int | None = None
) -> list[GraphNode]:
    """
    The stable identity facts for the user-subject self-model (Change 2): the
    deterministic complement to semantic retrieval. Returns the highest-salience
    USER-subject nodes of the deployment's configured identity entity types
    (values/goals/standing preferences), consolidated motifs first.

    Unioned into every conversation's context so the piece is oriented to who the
    user is before the first message happens to retrieve those facts. USER-subject
    only — the subject firewall (extraction redesign §7) keeps real-person and
    character facts out of the self-model seed. Returns [] when the deployment
    configures no identity types; retrieval alone then governs context.
    """
    types = APP_CONFIG.identity_seed_entity_types
    if not types:
        return []
    cap = limit if limit is not None else APP_CONFIG.identity_seed_limit
    async with get_session() as session:
        result = await session.run(
            """
            MATCH (n:Node {user_id: $uid})
            WHERE n.entity_type IN $types
              AND coalesce(n.subject_kind, 'user') = 'user'
            RETURN n
            ORDER BY coalesce(n.motif, false) DESC, n.mention_count DESC
            LIMIT $limit
            """,
            uid=str(user_id),
            types=types,
            limit=cap,
        )
        return [GraphNode(**record["n"]) async for record in result]


async def build_graph_context(
    message: str,
    user_id: UUID,
    session_number: int,
) -> GraphContext:
    """
    Embed the current message, find similar nodes via Qdrant, fetch their edges
    and dormant nodes from Neo4j, and return a GraphContext.
    Moved here from extraction.py — graph reads belong in the graph service (E7).

    Change 2: the message-driven retrieval is unioned with a deterministic identity
    seed (get_identity_seed) so stable orientation/role facts are always present —
    critically on a conversation's first turn, before any message has triggered
    retrieval. Retrieved nodes lead (they set the turn's active_region); identity
    facts not already retrieved are appended; edges are computed over the union.
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from db.qdrant import get_client
    from services.embedding import embed

    msg_embedding = await embed(message)

    response = await get_client().query_points(
        collection_name=APP_CONFIG.node_collection,
        query=msg_embedding,
        query_filter=Filter(
            must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
        ),
        limit=APP_CONFIG.context_retrieval_limit,
        score_threshold=APP_CONFIG.context_retrieval_threshold,
    )
    results = response.points

    relevant_node_ids = [r.payload["node_id"] for r in results if r.payload]

    retrieved_nodes: list[GraphNode] = []
    if relevant_node_ids:
        async with get_session() as session:
            result = await session.run(
                "MATCH (n:Node {user_id: $uid}) WHERE n.id IN $ids RETURN n",
                uid=str(user_id),
                ids=relevant_node_ids,
            )
            retrieved_nodes = [GraphNode(**record["n"]) async for record in result]

    # Deterministic identity seed, unioned with retrieval (dedup by id, retrieval
    # first so the message still governs the active region).
    retrieved_ids = {n.id for n in retrieved_nodes}
    seed_extra = [n for n in await get_identity_seed(user_id) if n.id not in retrieved_ids]
    relevant_nodes = retrieved_nodes + seed_extra

    all_ids = [n.id for n in relevant_nodes]
    relevant_edges = await get_edges_between(all_ids, user_id)
    dormant_nodes = await get_dormant_nodes(user_id, session_number)

    return GraphContext(
        relevant_nodes=relevant_nodes,
        relevant_edges=relevant_edges,
        dormant_nodes=dormant_nodes,
    )
