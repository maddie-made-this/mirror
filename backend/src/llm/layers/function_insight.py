from schemas.graph import GraphContext


def render(context: GraphContext) -> str | None:
    """
    Flow 2 (B5) — function-informed generation. Injects the IDIOGRAPHIC interpretation
    statements relevant to this turn (A3: the user's own specifics, never a category)
    so the model writes from understanding, not surface-matching: not "user likes
    debugging" but "debugging here is the relief of a world that is more consistent
    than they are" → it writes the relief, not just the activity.

    These are tentative reads, used to DEEPEN — never announced or explained to the
    user (that's the analytic branch's job). Returns None when there's nothing to add.
    """
    statements = [
        (i.get("statement") or "").strip()
        for i in context.interpretations
        if (i.get("statement") or "").strip()
    ]
    if not statements:
        return None

    body = "\n".join(f"- {s}" for s in statements)
    return (
        "[What you've come to understand about this person]\n"
        "Tentative reads from everything they've shared — use them to deepen what "
        "you write (lean into what serves the underlying need), but NEVER announce, "
        "explain, or quote them back. Show the understanding; don't state it.\n"
        + body
    )
