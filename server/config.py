"""Runtime configuration. Reads from environment or .env file."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    tradier_token: str = ""
    tradier_base_url: str = "https://sandbox.tradier.com/v1"

    scan_interval_seconds: int = 120  # chain refresh every 2 minutes
    stream_poll_seconds: int = 5      # spot poll fallback

    risk_free_rate: float = 0.045

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    snapshot_db: str = "./snapshots.db"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    finnhub_api_key: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
