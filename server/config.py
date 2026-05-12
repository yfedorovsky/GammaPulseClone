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

    # scan_interval_seconds: lowered 120 -> 60 (2026-05-12).
    # Triggered by Bug #3 (close-window latency): FL0WG0D's 3:45 PM MU 9/18
    # sweeps + 3:50 PM SLV ATM call buyer fired our alerts at 16:04-16:10
    # ET (14-25 min late, post-close). 60s cycle + tighter close-window
    # CHAIN_TTL (in worker.py) gets us to ≤2 min from print->Telegram.
    # The chain cache TTL absorbs most of the API cost (cache hits on 2nd
    # scan within the prior cache window).
    scan_interval_seconds: int = 60   # was 120; bumped 2026-05-12
    stream_poll_seconds: int = 5      # spot poll fallback

    risk_free_rate: float = 0.045

    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    snapshot_db: str = "./snapshots.db"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    finnhub_api_key: str = ""
    fred_api_key: str = ""  # FRED (Federal Reserve) — free, for NYMO/NAMO breadth data

    # ThetaData (Options Standard, subbed Apr 17 2026) — real-time OPRA Greeks,
    # NBBO, full tick stream with ISO sweep condition codes. Replaces Massive.
    # Runs against the locally-installed Theta Terminal (java -jar) — no cloud
    # API key needed; auth is handled by Terminal's Theta Data credentials.
    use_thetadata_greeks: bool = True   # Primary Greeks source, default on
    thetadata_rest_url: str = "http://127.0.0.1:25503"
    thetadata_ws_url: str = "ws://127.0.0.1:25520/v1/events"
    thetadata_sweep_enabled: bool = True  # Enables sweep_detector background task

    # Massive (formerly Polygon) — DEPRECATED as of Apr 17 2026.
    # Kept wired for 1-flag rollback window. Planned removal: after Monday
    # Apr 20 2026 market-open validation of Theta Greeks parity.
    massive_api_key: str = ""
    massive_base_url: str = "https://api.massive.com"
    use_massive_greeks: bool = False  # DEPRECATED; True only for emergency rollback

    # Discord listener — ported from Mac Mini bridge
    discord_token: str = ""          # User token (discord.py-self)
    discord_enabled: bool = False    # Off by default, opt-in
    anthropic_api_key: str = ""      # For Claude Haiku signal parsing

    # Flow alert filter (May 6 2026 spam-reduction project)
    # OFF   — legacy gate (HIGH/$5M/OTM/max 2 per cycle), no spam reduction
    # LIGHT — drop LOW unless sweep/$5M; drop NEUTRAL+HARD; per-ticker 5/hr cap
    # FULL  — LIGHT + multi-leg cluster collapser (≥3 same-ticker in 60s → 1 summary)
    # Backtested on May 6 data: 1,267 → ~270 alerts (-78%) at FULL.
    # Read fresh by `flow_alert_filter._level()` so .env edits take effect at
    # the next 30s scan cycle without restart.
    flow_alert_filter_level: str = "LIGHT"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
