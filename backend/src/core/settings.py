from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Comma-separated list of allowed CORS origins.
    # Production: ALLOWED_ORIGINS=https://app.example.com,https://staging.example.com
    allowed_origins: str = "http://localhost:3000"

    openrouter_api_key: str
    openai_api_key: str

    # Pin IPv4: on Windows "localhost" resolves to IPv6 [::1] first, which
    # Docker's bolt port-forward doesn't serve reliably (the WebSocket upgrade
    # the Neo4j Browser uses dies with it). .env overrides this, but the default
    # should stand on its own.
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    # No default: a credential must come from the environment (backend/.env), never
    # from committed source. Pydantic raises at startup if it is unset, which is the
    # intended behaviour — better a loud boot failure than a baked-in password.
    neo4j_password: str

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Base URL of the Supabase instance. Used to fetch the JWKS for verifying
    # user access tokens (Supabase signs them with an asymmetric ES256 key).
    supabase_url: str = "http://127.0.0.1:54321"

    # Direct Postgres (asyncpg) DSN for the Supabase database — chat history and
    # idempotency keys. Local Supabase exposes Postgres on port 54322.
    supabase_db_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    # Sent as HTTP-Referer and X-Title in OpenRouter requests.
    http_referer: str = "http://localhost:3000"
    app_title: str = "Mirror"

    # --- LLM backend routing (role-aware) ---
    # The architecture is split: the DIRECTOR reasons on a frontier model, the RENDERER
    # writes the prose. The renderer is the token-heavy tier, so it can be pinned to a
    # cheaper OpenAI-compatible provider independently of the director. Routing is
    # per-ROLE because a global flip would send the director to an endpoint that can't
    # serve it.
    llm_backend: str = "openrouter"      # default backend for ALL calls (incl. director)
    renderer_backend: str = ""           # renderer-only override; "" = fall back to llm_backend
    # Generic renderer provider — ANY OpenAI-compatible chat-completions endpoint. Model
    # and host are swappable config, so moving providers needs no code change.
    # "" = use OpenRouter like every other role.
    renderer_base_url: str = ""          # OpenAI-compatible chat-completions URL
    renderer_api_key: str = ""           # key for that provider
    renderer_model: str = ""             # the model id that provider expects

    # When true, responses carry the full labeled prompt breakdown for the
    # dev-panel context inspector. Leaks the system prompt — local only.
    expose_prompt_debug: bool = False

    # Background maintenance pipeline (clustering/interpretation/bridges).
    enable_scheduler: bool = True
    maintenance_interval_seconds: int = 120
    # Recompute every user's clusters/interpretations/bridges once on startup, so a
    # restart applies code/prompt changes instead of serving stale stored results.
    # Fine for a single-instance/dev backend; disable for large multi-user prod.
    recompute_on_start: bool = True

    # Per-tier output-token caps. 0 = uncapped (config default). Set in the
    # environment to bound completion length for cheap test runs without editing
    # committed config; loader._apply_env_overrides copies any >0 value onto APP_CONFIG.
    response_max_tokens: int = 0
    utility_max_tokens: int = 0
    moderation_max_tokens: int = 0
    # Director cap is non-zero in committed config (anti-402 reserve guard); env can
    # still override. 0 here = keep the committed default.
    director_max_tokens: int = 0

    # Probe lever (Part A): repoint ONLY response generation via the env, without
    # editing committed config — e.g. RESPONSE_MODEL=anthropic/claude-sonnet-4.6 to
    # test whether a frontier reasoner unlocks the behavior. "" = use config default.
    response_model: str = ""

    # Director/renderer split (Part B) levers — flip the split on and repoint either
    # tier from the env without editing committed config. USE_DIRECTOR_SPLIT=1 turns
    # it on; DIRECTOR_MODEL/RENDERER_MODEL override the resolved tiers ("" = default).
    use_director_split: bool = False
    director_model: str = ""
    # Dual-model render (Change 6): USE_DUAL_RENDER=1 turns it on (only takes effect
    # when the split is also on). Env True OR committed default wins; never off-by-env.
    use_dual_render: bool = False

    # The cheap tier itself. Setting UTILITY_MODEL repoints EVERY small-tier role at
    # once (extraction, matcher, headline, reflection) — they all fall back to
    # utility_model_resolved. The frontier roles (response/director/renderer) fall back
    # to llm_model instead, so this never touches generation. "" = use llm_model.
    utility_model: str = ""

    # Small-model swaps (L9 / P5.3): repoint individual cheap-tier call sites via env
    # (e.g. EXTRACTION_MODEL=anthropic/claude-haiku-4.5), overriding the utility tier
    # for that one role. "" = inherit utility_model_resolved.
    extraction_model: str = ""
    matcher_model: str = ""
    headline_model: str = ""

    # Warming-up UX (P5.4): first-token threshold in seconds. 0 = keep the config default.
    warming_ttft_s: float = 0.0

    # Field-level encryption (P5.1): Fernet key for the crown-jewel columns (timeline
    # origin episodes — Phase 6). urlsafe-base64 32 bytes (Fernet.generate_key()). Empty =
    # unset; core.crypto raises only WHEN a field is actually encrypted/decrypted, so the
    # app runs without it until the timeline feature is enabled.
    mirror_field_key: str = ""

    # Supabase service-role key (P5.1 delete job): needed for the auth admin user delete
    # step. Empty = skip that step with a warning (data stores are still purged).
    supabase_service_role_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
