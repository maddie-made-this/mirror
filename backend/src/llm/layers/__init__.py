# Prompt layer modules — each exports a render() function.
# render() returns str | None (or list[dict] for recent_messages).
# The builder in llm/prompts.py composes the final message list.
