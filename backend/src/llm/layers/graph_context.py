from config.loader import APP_CONFIG
from schemas.graph import GraphContext


def render(context: GraphContext) -> str | None:
    """
    Relevant nodes, edges (including negated ones with [NEGATED] prefix),
    and dormant high-mention nodes (C1, C4).
    Returns None if the context is empty — no point adding an empty block.
    """
    if not APP_CONFIG.use_graph_context_layer:
        return None
    if not (context.relevant_nodes or context.relevant_edges or context.dormant_nodes):
        return None

    lines: list[str] = ["[Graph context]"]

    if context.relevant_nodes:
        node_summaries = [
            f"- {n.id} (mentioned {n.mention_count}x, "
            f"valence: {n.valence.value}, salience: {n.salience_score:.2f})"
            for n in context.relevant_nodes
        ]
        lines.append("Relevant concepts:\n" + "\n".join(node_summaries))

    if context.relevant_edges:
        edge_summaries: list[str] = []
        for e in context.relevant_edges:
            label = e.relation_type.value
            if e.is_negated:
                edge_summaries.append(
                    f"- {e.source_id} → [NEGATED] {label} → {e.target_id}"
                )
            else:
                edge_summaries.append(f"- {e.source_id} → {label} → {e.target_id}")
        lines.append("Relationships:\n" + "\n".join(edge_summaries))

    if context.dormant_nodes:
        dormant = ", ".join(n.id for n in context.dormant_nodes)
        lines.append(
            f"Dormant concepts (high mention count, not seen recently): {dormant}"
        )

    return "\n\n".join(lines)
