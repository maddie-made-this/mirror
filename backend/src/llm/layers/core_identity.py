from config.loader import APP_CONFIG
from config.personas import get_active_persona


def render() -> str | None:
    """
    Persona, name, and voice for the assistant — assembled from the active narrator
    persona (config/personas.py: identity + hard rules).
    On by default: Mirror's persona is the conversational layer, so it is injected
    rather than deferring to the base model's own trained identity. A deployment
    that wants the bare model can switch it off (use_identity_layer).
    """
    if not APP_CONFIG.use_identity_layer:
        return None
    persona = get_active_persona()
    parts = [persona.identity]
    if persona.rules:
        parts.append(
            "HOW YOU OPERATE (hard rules):\n"
            + "\n\n".join(f"- {r}" for r in persona.rules)
        )
    return "\n\n".join(parts)
