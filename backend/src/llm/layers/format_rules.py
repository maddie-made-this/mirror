from config.loader import APP_CONFIG
from core import request_context
from schemas.graph import GraphNode


def render(
    preference_nodes: list[GraphNode],
    target_words: int | None = None,
) -> str | None:
    """
    Prose-style rules: static baseline from config plus dynamic rules
    extracted from the user's 'format_rule' graph nodes (C3).
    Sorted by stability_score × mention_count so most-entrenched rules come first.

    target_words (P4.1): the user's LEARNED length target for this render mode, when one
    exists — appended as a soft directive that overrides the prompt's qualitative default.
    Explicit arg wins (tests); otherwise the per-request contextvar the message handler set
    is used. None/unset (the common case) injects nothing, so behaviour is unchanged.
    """
    if target_words is None:
        target_words = request_context.get_target_words()

    if not APP_CONFIG.use_format_layer:
        # The learned length target is delivery-tuning, not a "format rule" node — surface
        # it even when the format layer is off, so the adaptation still reaches the prose.
        return _length_directive(target_words)

    parts: list[str] = []

    if APP_CONFIG.static_format_rules_text:
        parts.append(APP_CONFIG.static_format_rules_text)

    format_nodes = [n for n in preference_nodes if n.entity_type == "format_rule"]
    if format_nodes:
        format_nodes.sort(
            key=lambda n: (n.stability_score * n.mention_count),
            reverse=True,
        )
        lines = [f"- {n.name}" for n in format_nodes]
        parts.append("User format preferences:\n" + "\n".join(lines))

    length = _length_directive(target_words)
    if length:
        parts.append(length)

    if not parts:
        return None

    return "[Format rules]\n" + "\n\n".join(parts)


def _length_directive(target_words: int | None) -> str | None:
    """A soft length target learned from the user's longer/shorter presses (P4.1)."""
    if not target_words or target_words <= 0:
        return None
    return (
        f"Length: aim for roughly {target_words} words — the user has tuned the length to "
        f"this. Treat it as a soft target, not a hard cap; never pad or truncate mid-thought."
    )
