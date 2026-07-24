"""
Dynamics layer — session-depth guidance, rendered as craft direction.

Depth is about the CONVERSATION, not about the person's tolerance: how much
shared context exists so far, and therefore how much a demanding idea can be
raised directly and still land. The receptivity line adapts turn length to how
engaged they are today; the frame line distinguishes a hypothetical from
something live for them.
"""
from schemas.graph import GraphContext

_RAMP_LINES = {
    "early": (
        "Early in the session — establish what they're actually circling before "
        "going deep."
    ),
    "mid": (
        "The thread is established. Go further into the idea rather than "
        "broadening to new ones."
    ),
    "deep": (
        "Deep in the session — the shared context is rich enough to develop the "
        "argument's harder implications directly. Introduce new threads only "
        "where they serve the point being made."
    ),
}

_GATE_LINES = {
    "open": (
        "They're engaging more than usual today — a longer or more technical "
        "move will land."
    ),
    "guarded": (
        "They're more reserved than usual today — follow their lead and keep "
        "turns short."
    ),
}

_FRAME_LINES = {
    "fiction": (
        "Frame: hypothetical — you can build out scenarios and thought "
        "experiments freely; hold the premise consistently rather than hedging "
        "in and out of it."
    ),
    "real": (
        "Frame: this is something live for them, not a hypothetical — be "
        "concrete and careful."
    ),
}


def render(context: GraphContext) -> str | None:
    """
    Session-dial guidance from GraphContext.session_state. None when dynamics
    are unavailable (the layer simply drops out — prompts degrade gracefully).
    """
    ss = context.session_state
    if not ss:
        return None

    lines: list[str] = []
    ramp = _RAMP_LINES.get(str(ss.get("depth_ramp", "")))
    if ramp:
        lines.append(ramp)
    gate = _GATE_LINES.get(str(ss.get("gate_position", "")))
    if gate:
        lines.append(gate)
    frame = _FRAME_LINES.get(str(ss.get("frame", "")))
    if frame:
        lines.append(frame)
    region = str(ss.get("active_region") or "").strip()
    if region:
        lines.append(f'The session is currently living in their "{region}" territory.')

    if not lines:
        return None
    return (
        "SESSION DIALS (a read of this conversation right now — calibrate to it, "
        "never mention it):\n" + "\n".join(f"- {line}" for line in lines)
    )
