from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Checks parent dir first (project root), then backend/ — last file wins on duplicates.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite:///./mtg_inventory.db"
    scryfall_base: str = "https://api.scryfall.com"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Optional shared key for personal/public deployments. When set, all API
    # routes except health/auth status require X-Spellbinder-Key.
    app_api_key: str = ""
    require_auth: bool = False
    # Set only when an upstream service such as Cloudflare Access performs
    # authentication before traffic reaches Spellbinder.
    external_auth_enabled: bool = False

    max_upload_bytes: int = 10 * 1024 * 1024
    max_request_bytes: int = 12 * 1024 * 1024
    max_deck_text_chars: int = 200_000
    max_ai_text_chars: int = 100_000
    max_scryfall_batch_size: int = 5_000
    max_enrichment_batch_size: int = 2_000
    max_embedding_batch_size: int = 5_000

    # Provider credentials are loaded from the environment and must never be
    # committed. OpenAI is the default for every model-assisted stage;
    # Anthropic remains available only as an explicitly selected provider.
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # Structured mechanic enrichment is provider-neutral. OpenAI Luna creates
    # the default profiles; storage and downstream consumers remain portable.
    enrichment_provider: str = "openai"
    enrichment_model: str = "gpt-5.6-luna"
    enrichment_reasoning_effort: str = "low"
    enrichment_max_output_tokens_per_card: int = 900

    # Semantic retrieval uses a persistent, versioned Oracle-card index. The
    # smaller vector size keeps a personal SQLite database compact while
    # retaining the text-embedding-3 model's semantic signal.
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 512
    embedding_request_batch_size: int = 100

    # Strategic reasoning proposes bounded packages; deterministic code builds
    # and validates the actual deck. Missing keys and provider failures fall
    # back to the local rules provider.
    openai_requests_enabled: bool = False
    # Local safety rails. These do not replace the OpenAI project budget, but
    # they block this application before a request is sent.
    openai_monthly_budget_usd: float = 1.00
    openai_single_request_limit_usd: float = 0.10
    reasoning_provider: str = "openai"
    reasoning_model: str = "gpt-5.6-luna"
    reasoning_effort: str = "medium"
    reasoning_max_output_tokens: int = 6_000
    review_provider: str = "openai"
    review_model: str = "gpt-5.6-luna"
    review_reasoning_effort: str = "low"
    review_max_output_tokens: int = 4_000
    review_fallback_model: str = "rules-v1"
    openai_timeout_seconds: float = 120.0
    openai_max_retries: int = 2


settings = Settings()
