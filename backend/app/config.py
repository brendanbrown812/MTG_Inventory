from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./mtg_inventory.db"
    scryfall_base: str = "https://api.scryfall.com"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"


settings = Settings()
