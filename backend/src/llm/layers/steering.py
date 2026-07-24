from schemas.graph import GraphContext


def render(context: GraphContext) -> str | None:
    """
    Flow 3 (B5) + the narrative-appropriateness gate (B6). Injects the steering
    objective as a STANDING CURIOSITY, not a per-turn mandate — wrapped in the §5C
    gate so the model self-regulates off conversational state: it acts only at seams
    (lulls/transitions/wind-downs/user-seeking-direction) and only when the objective
    fits the moment; a moment of real momentum is sacred; otherwise it holds,
    patiently. No separate knob — aggressiveness self-regulates, which also protects
    data integrity (a shoehorned probe produces contaminated reactions).
    """
    objective = (context.steering_objective or "").strip()
    if not objective:
        return None

    return (
        "[A standing curiosity — hold it lightly]\n"
        f"{objective}\n"
        "Pursue this ONLY if THIS moment is a natural opening — a lull, a transition, "
        "a wind-down, or the user looking for direction — AND it can enter naturally "
        "given where the conversation already is. If the moment has momentum or is at "
        "a peak of interest, follow that fully and hold this for later; it is patient "
        "and will keep. Never rupture a working moment to pursue it, and never announce "
        "it as an agenda — weave it in, or wait."
    )
