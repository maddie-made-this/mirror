from config.loader import APP_CONFIG


def render() -> str | None:
    """
    Optional content-boundary layer, sourced from config.

    Off by default: the hosted models this app targets apply their own content
    policy, so restating it in-prompt only spends tokens. Available for a
    deployment that wants its boundaries stated explicitly.
    """
    if not APP_CONFIG.use_safety_layer:
        return None
    if not APP_CONFIG.safety_rules_text:
        return None
    return APP_CONFIG.safety_rules_text
