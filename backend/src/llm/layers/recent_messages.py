from config.loader import APP_CONFIG
from schemas.message import ConversationTurn


def render(
    turns: list[ConversationTurn],
    limit: int | None = None,
) -> list[dict[str, str]] | None:
    """
    Returns recent turns as a list of message dicts for the messages array —
    NOT a string, because history goes into the messages list, not the system prompt.
    Returns None if there is no history.
    """
    if not APP_CONFIG.use_recent_messages_layer or not turns:
        return None

    effective_limit = limit if limit is not None else APP_CONFIG.recent_messages_limit
    recent = turns[-effective_limit:]

    messages: list[dict[str, str]] = []
    for turn in recent:
        messages.append({"role": "user", "content": turn.user_message})
        messages.append({"role": "assistant", "content": turn.response_text})
    return messages
