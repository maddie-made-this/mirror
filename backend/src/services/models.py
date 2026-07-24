"""
The user-selectable response-model registry.

ONE tier is user-facing: the response/generation model. The director, renderer and
utility tiers stay deployment config (see AppConfig) — they are architectural
choices, not preferences, and letting a visitor put a cheap model on the director
would quietly wreck output quality while looking like an app bug.

The registry is SERVER-OWNED and validated on read. A stored preference that is
not in this list (stale row, hand-edited DB, a model we retired) resolves to None
and the caller falls back to the configured default, so a bad value can never
reach the provider as a 404.

Every id below was verified against the live OpenRouter catalogue.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelChoice:
    id: str          # OpenRouter slug — must resolve at the provider
    label: str       # what the user picks
    blurb: str       # one line explaining the trade-off


# Ordered for display: strongest first within each family.
RESPONSE_MODELS: list[ModelChoice] = [
    ModelChoice("anthropic/claude-opus-4.8", "Claude Opus 4.8",
                "Deepest reasoning. Slowest and priciest."),
    ModelChoice("anthropic/claude-sonnet-5", "Claude Sonnet 5",
                "The balanced default — strong reasoning at practical cost."),
    ModelChoice("anthropic/claude-haiku-4.5", "Claude Haiku 4.5",
                "Fast and cheap. Best for quick back-and-forth."),
    ModelChoice("openai/gpt-5.6-sol", "GPT-5.6 Sol",
                "OpenAI's frontier tier. ~1M token context."),
    ModelChoice("openai/gpt-5.6-terra", "GPT-5.6 Terra",
                "Mid-tier with a ~1M token context window."),
    ModelChoice("openai/gpt-5.6-luna", "GPT-5.6 Luna",
                "Cheapest of the long-context family."),
    ModelChoice("google/gemini-3.1-pro-preview", "Gemini 3.1 Pro",
                "Google's frontier model."),
    ModelChoice("google/gemini-3.5-flash", "Gemini 3.5 Flash",
                "Fast Google tier."),
    ModelChoice("meta-llama/llama-4-maverick", "Llama 4 Maverick",
                "Open-weight. Useful as a provider-independent baseline."),
]

_BY_ID = {m.id: m for m in RESPONSE_MODELS}


def resolve(preferred: str | None) -> str | None:
    """
    Validate a stored preference against the registry.

    Returns the model id when it is a known, currently-offered choice; None
    otherwise (unset, retired, or junk) so the caller keeps the configured
    default. Never raises — a bad preference must not break a turn.
    """
    if not preferred:
        return None
    return _BY_ID[preferred].id if preferred in _BY_ID else None


def catalogue() -> list[dict]:
    """The registry as JSON for the settings picker."""
    return [{"id": m.id, "label": m.label, "blurb": m.blurb} for m in RESPONSE_MODELS]
