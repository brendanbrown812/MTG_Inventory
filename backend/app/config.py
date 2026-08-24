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

    # Set ANTHROPIC_API_KEY in backend/.env
    anthropic_api_key: str = ""

    # Structured mechanic enrichment is provider-neutral. The first adapter
    # uses Anthropic, while storage and downstream consumers do not.
    enrichment_provider: str = "anthropic"
    enrichment_model: str = "claude-haiku-4-5-20251001"

    # Strategic reasoning proposes bounded packages; deterministic code builds
    # and validates the actual deck.
    reasoning_provider: str = "anthropic"
    reasoning_model: str = "claude-sonnet-4-6"

    # Claude model for deck generation (reasoning — Sonnet is the right balance).
    # To switch: set DECKBUILDING_MODEL=<model> in backend/.env and restart.
    # Options (Aug 2025): claude-haiku-4-5-20251001, claude-sonnet-4-6, claude-opus-4-7
    deckbuilding_model: str = "claude-sonnet-4-6"


settings = Settings()
