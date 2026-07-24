from config.loader import APP_CONFIG


def render(session_type: str = "primary") -> str | None:
    """
    App-specific behavioural rules. In the ANALYTIC branch (session_type='analytic')
    the primary capability is replaced by the analytic-register conduct (B10) when one
    is configured — same interlocutor, the "why" room. Falls back to the normal
    capability otherwise (the default, where there's no separate register).
    """
    if not APP_CONFIG.use_capability_layer:
        return None
    if session_type == "analytic" and APP_CONFIG.analytic_capability_text:
        return APP_CONFIG.analytic_capability_text
    return APP_CONFIG.capability_rules_text or None
