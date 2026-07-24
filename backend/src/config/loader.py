from config.types import AppConfig


def load_config() -> AppConfig:
    from config.default import DEFAULT_CONFIG

    return _apply_env_overrides(DEFAULT_CONFIG)


def _apply_env_overrides(config: AppConfig) -> AppConfig:
    """
    Apply infrastructure-level env vars onto the loaded config so the rest of
    the codebase reads one source of truth (APP_CONFIG).
    """
    # Lazy import: settings pulls in pydantic-settings; keep loader light.
    from core.settings import get_settings

    s = get_settings()
    config.expose_prompt_debug = s.expose_prompt_debug

    # Probe lever (Part A): repoint ONLY response generation, reversibly, via env.
    if s.response_model:
        config.response_model = s.response_model

    # Director/renderer split (Part B): env can flip the split on and repoint either
    # tier without editing committed config. The bool only turns ON from the env
    # (never silently off): env True OR committed default wins.
    config.use_director_split = s.use_director_split or config.use_director_split
    config.use_dual_render = s.use_dual_render or config.use_dual_render
    if s.director_model:
        config.director_model = s.director_model
    if s.renderer_model:
        config.renderer_model = s.renderer_model

    # Token caps: only override when the env sets a positive value, so the
    # committed config's defaults (typically 0 = uncapped) stand otherwise.
    if s.response_max_tokens > 0:
        config.response_max_tokens = s.response_max_tokens
    if s.utility_max_tokens > 0:
        config.utility_max_tokens = s.utility_max_tokens
    if s.moderation_max_tokens > 0:
        config.moderation_max_tokens = s.moderation_max_tokens
    if s.director_max_tokens > 0:
        config.director_max_tokens = s.director_max_tokens

    # The cheap tier itself: UTILITY_MODEL repoints every small-tier role at once
    # (extraction/matcher/headline/reflection all resolve through utility_model). The
    # frontier roles resolve through llm_model, so this can't downgrade generation.
    if s.utility_model:
        config.utility_model = s.utility_model

    # Small-model swaps (P5.3): env repoints a single cheap-tier call site; "" keeps
    # the config default (falls back to utility_model_resolved via the resolved props).
    if s.extraction_model:
        config.extraction_model = s.extraction_model
    if s.matcher_model:
        config.matcher_model = s.matcher_model
    if s.headline_model:
        config.headline_model = s.headline_model

    # Warming-up threshold (P5.4): only override with a positive env value.
    if s.warming_ttft_s > 0:
        config.warming_ttft_s = s.warming_ttft_s
    return config


APP_CONFIG: AppConfig = load_config()
