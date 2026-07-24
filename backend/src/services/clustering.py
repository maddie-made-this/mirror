"""
Community detection (the Cluster tier).

A background job (driven by the scheduler via services.maintenance) pulls a
user's graph — semantic :EDGE plus materialized :CO_OCCURS edges — into an
undirected networkx graph, runs Louvain community detection, writes a
`cluster_id` onto each :Node, and (re)creates one :Cluster node per community
with a cheap LLM-generated theme label and [:IN_CLUSTER] membership edges.

networkx (not Neo4j GDS) on purpose: the Docker image is bare neo4j:5 with no
GDS plugin, per-user graphs are small, and this runs off the request path.
"""

import hashlib
import math
import logging
import re
from uuid import UUID

import networkx as nx
from networkx.algorithms.community import louvain_communities

from config.loader import APP_CONFIG
from db.neo4j import get_session
from llm.client import chat

logger = logging.getLogger(__name__)


def sanitize_label(raw: str) -> str:
    """
    Clean a raw LLM theme label into a bare 2-4 word phrase.

    Cheaper models (the utility tier) ignore "no markdown" and return bulleted or
    numbered labels like "- Systems Thinking" or "1. Curiosity". Strip leading
    bullets/numbering and surrounding quotes, take the first line, collapse
    whitespace, and cap length. Robust to formatting rather than prompt-reliant.
    """
    s = (raw or "").strip()
    s = s.splitlines()[0] if s else s            # first line only
    s = re.sub(r"^\s*(\d+[.)]|[-*•·–—#>]+)\s*", "", s)  # leading bullet / number / heading
    # Strip a leading type prefix the cheap model adds despite instructions
    # ("Theme: ...", "Pattern: ..."), so the label is just the phrase.
    s = re.sub(
        r"^\s*(theme|pattern|label|topic|category|group|cluster|name)\s*:\s*",
        "", s, flags=re.IGNORECASE,
    )
    # Remove markdown emphasis chars ANYWHERE — cheap models sprinkle ** mid-label
    # (e.g. "Theme:** First Principles"), so end-only stripping misses them.
    s = re.sub(r"[*_`~]", "", s)
    s = s.strip(" \t\"'“”‘’")
    s = re.sub(r"\s+", " ", s).strip()           # collapse internal whitespace
    return s[:60]

# Don't bother clustering a graph too small to have structure.
_MIN_NODES_TO_CLUSTER = 4
# Only spend an LLM label call on communities of at least this size; smaller
# ones get a cheap fallback label (their largest member's name).
_MIN_SIZE_TO_LABEL = 3
# Cap the names sent to the labeling LLM call.
_MAX_NAMES_FOR_LABEL = 25

# Graph size at which the configured resolution applies unscaled. Above this the
# resolution is nudged up (see _resolution_for) to hold community size roughly
# constant as the graph grows.
_RESOLUTION_PIVOT_NODES = 40


def _resolution_for(node_count: int) -> float:
    """
    Louvain resolution for a graph of this size.

    Modularity optimisation has a RESOLUTION LIMIT: at a fixed resolution the
    smallest detectable community grows with sqrt(total edges), so the same
    settings that give tight communities on a small graph silently merge
    distinct concepts into broad ones as the graph accumulates. That is the
    "the longer I talk, the broader the clusters get" failure directly.

    Counteract it by raising resolution with graph size — higher resolution
    favours more, smaller communities — so cluster GRANULARITY stays roughly
    constant instead of cluster COUNT staying roughly constant.

    Growth is the FOURTH root of (n / pivot), not the square root the resolution
    limit strictly implies. sqrt is theoretically right but far too steep at the
    sizes a personal graph actually reaches: it hit the ceiling by ~160 nodes and
    over-fragmented well before that. The fourth root keeps the correction gentle
    across the hundreds-to-low-thousands range these graphs live in, and only
    approaches the cap in the low thousands.
    """
    base = APP_CONFIG.cluster_resolution
    if node_count <= _RESOLUTION_PIVOT_NODES:
        return base
    scaled = base * (node_count / _RESOLUTION_PIVOT_NODES) ** 0.25
    return min(scaled, APP_CONFIG.cluster_resolution_max)


async def _load_graph(user_id: UUID) -> tuple[dict[str, str], list[tuple[str, str, float]]]:
    """Return ({node_id: name}, [(src, tgt, weight), ...]) for this user."""
    async with get_session() as session:
        node_result = await session.run(
            "MATCH (n:Node {user_id: $uid}) RETURN n.id AS id, n.name AS name",
            uid=str(user_id),
        )
        names: dict[str, str] = {
            record["id"]: (record["name"] or record["id"]) async for record in node_result
        }

        edge_result = await session.run(
            """
            MATCH (a:Node {user_id: $uid})-[r:EDGE|CO_OCCURS]->(b:Node {user_id: $uid})
            RETURN a.id AS a, b.id AS b, coalesce(r.weight, 1.0) AS w
            """,
            uid=str(user_id),
        )
        edges = [
            (record["a"], record["b"], float(record["w"])) async for record in edge_result
        ]
    return names, edges


async def _mention_snippets(user_id: UUID, member_ids: list[str], limit: int = 12) -> list[str]:
    """A sample of the actual things the user said that produced these nodes."""
    async with get_session() as session:
        res = await session.run(
            """
            MATCH (m:Mention {user_id: $uid})-[:REFERENCES]->(n:Node)
            WHERE n.id IN $ids AND m.text IS NOT NULL
            RETURN DISTINCT m.text AS t ORDER BY m.text LIMIT $limit
            """,
            uid=str(user_id), ids=member_ids, limit=limit,
        )
        return [r["t"] async for r in res]


async def _label_cluster(
    member_names: list[str],
    snippets: list[str],
    avoid: list[str] | None = None,
) -> str:
    """
    Cheap LLM call: name the theme connecting a cluster's members in 2-4 words.
    Grounded in the user's actual words (mention snippets), not just node names —
    far better labels. `avoid` lists labels already used by other communities, so
    a collision is resolved by a genuinely distinct name (a different angle on the
    same material) rather than an awkward suffix. Falls back to the first member
    name on any failure.
    """
    sample = member_names[:_MAX_NAMES_FOR_LABEL]
    user_content = "Concepts: " + ", ".join(sample)
    if snippets:
        user_content += "\n\nThings the user actually said:\n" + "\n".join(
            f"- {s}" for s in snippets
        )
    if avoid:
        user_content += (
            "\n\nThese labels are already used by other groups — pick a DIFFERENT, "
            "more specific angle that distinguishes this group: " + ", ".join(avoid)
        )
    try:
        raw = await chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You name themes. Given related concepts from one person's "
                        "map and snippets of what they actually said, reply with "
                        "ONLY a 2-4 word theme label naming what connects them — just "
                        "the bare phrase. Do NOT prefix it with a type word like "
                        "'Theme:' or 'Pattern:'. No markdown, no asterisks, no "
                        "punctuation, no quotes, no explanation."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            model=APP_CONFIG.utility_model_resolved,
            temperature=0.2,
        )
        label = sanitize_label(raw)
        return label or (sample[0] if sample else "cluster")
    except Exception:
        logger.warning("cluster label generation failed; using fallback")
        return sample[0] if sample else "cluster"


def _unique_label(label: str, used: set[str]) -> str:
    """Final fallback: numeric-suffix a label that's still taken (' (2)', ' (3)')."""
    if label.lower() not in used:
        return label
    i = 2
    while f"{label} ({i})".lower() in used:
        i += 1
    return f"{label} ({i})"


async def _write_clusters(
    user_id: UUID,
    clusters: list[tuple[str, str, list[str]]],
) -> None:
    """Replace this user's cluster assignments atomically-ish in one session."""
    async with get_session() as session:
        # Clear prior clusters + memberships for a clean recompute.
        await session.run(
            "MATCH (c:Cluster {user_id: $uid}) DETACH DELETE c", uid=str(user_id)
        )
        await session.run(
            "MATCH (n:Node {user_id: $uid}) REMOVE n.cluster_id", uid=str(user_id)
        )
        for cid, label, members in clusters:
            await session.run(
                """
                CREATE (c:Cluster {id: $cid, user_id: $uid, label: $label, size: $size})
                WITH c
                UNWIND $members AS mid
                MATCH (n:Node {id: mid, user_id: $uid})
                SET n.cluster_id = $cid
                MERGE (n)-[:IN_CLUSTER]->(c)
                """,
                cid=cid,
                uid=str(user_id),
                label=label,
                size=len(members),
                members=members,
            )


async def cluster_user(user_id: UUID) -> int:
    """
    Recompute communities for one user and persist cluster_id + :Cluster nodes.
    Returns the number of clusters written (0 if skipped). Safe to call
    repeatedly — each run fully replaces the prior assignment.
    """
    names, edges = await _load_graph(user_id)
    if len(names) < _MIN_NODES_TO_CLUSTER or not edges:
        return 0

    g = nx.Graph()
    g.add_nodes_from(names.keys())
    for a, b, w in edges:
        if a == b:
            continue
        if g.has_edge(a, b):
            g[a][b]["weight"] += w
        else:
            g.add_edge(a, b, weight=w)

    if g.number_of_edges() == 0:
        return 0

    resolution = _resolution_for(g.number_of_nodes())
    communities = louvain_communities(
        g, weight="weight", seed=42, resolution=resolution
    )

    clusters: list[tuple[str, str, list[str]]] = []
    used: set[str] = set()  # lowercased labels already assigned, to keep them distinct
    for comm in communities:
        members = sorted(comm)
        member_names = [names.get(n, n) for n in members]
        # Stable id derived from membership: a cluster with the same members keeps
        # the same id across runs, so interpretations attached to it aren't
        # orphaned and re-generated every time the pipeline runs.
        sig = hashlib.sha1(";".join(members).encode()).hexdigest()[:12]
        cid = f"{user_id}:c:{sig}"
        if len(members) >= _MIN_SIZE_TO_LABEL:
            snippets = await _mention_snippets(user_id, members)
            label = await _label_cluster(member_names, snippets)
            # Collision → regenerate a genuinely distinct name (tell it what's taken).
            if label.lower() in used:
                label = await _label_cluster(member_names, snippets, avoid=list(used))
        else:
            label = sanitize_label(member_names[0]) if member_names else cid
        label = _unique_label(label, used)  # numeric suffix only if still colliding
        used.add(label.lower())
        clusters.append((cid, label, members))

    await _write_clusters(user_id, clusters)
    logger.info(
        "clustered_user",
        extra={"user_id": str(user_id), "clusters": len(clusters), "nodes": len(names)},
    )
    return len(clusters)
