from config.loader import APP_CONFIG
from schemas.graph import GraphNode


def render(preference_nodes: list[GraphNode]) -> str | None:
    """
    Explicit user preferences stored as 'preference' graph nodes.
    Format rules are handled separately in format_rules.py.
    """
    if not APP_CONFIG.use_graph_context_layer:
        return None

    prefs = [n for n in preference_nodes if n.entity_type == "preference"]
    if not prefs:
        return None

    lines = [f"- {n.name}" for n in prefs]
    return "[User preferences]\n" + "\n".join(lines)
