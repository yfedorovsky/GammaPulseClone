"""Runtime configuration. Reads from environment or .env file.

Note: pydantic-settings prioritizes OS env vars over .env file.
If an env var is set but empty (e.g. ANTHROPIC_API_KEY=), it will
override the .env value. To fix: load_dotenv with override=True first.
"""
from functools import lru_cache
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env first so it overrides empty OS env vars
load_dotenv(".env", override=True)


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
    fred_api_key: str = ""  # FRED (Federal Reserve) — free, for NYMO/NAMO breadth data

    # Massive (formerly Polygon) — real-time Greeks & IV
    massive_api_key: str = ""
    massive_base_url: str = "https://api.massive.com"
    use_massive_greeks: bool = True  # feature flag; False = Tradier-only fallback

    # Discord listener — ported from Mac Mini bridge
    discord_token: str = ""          # User token (discord.py-self)
    discord_enabled: bool = False    # Off by default, opt-in
    anthropic_api_key: str = ""      # For Claude Haiku signal parsing

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
