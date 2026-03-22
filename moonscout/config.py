"""
config.py — Centralised settings for MoonScout.

pydantic-settings reads all values from the .env file and validates them
at import time.  Any missing required variable raises a ValidationError
before the agents attempt to connect, implementing "fail fast" startup.
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Don't crash on extra variables the user might have in .env
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # MongoDB Atlas  (PC-10: must be mongodb+srv://)
    # ------------------------------------------------------------------
    mongodb_connection_uri: str

    @field_validator("mongodb_connection_uri")
    @classmethod
    def must_be_atlas_uri(cls, v: str) -> str:
        if not v.startswith("mongodb+srv://"):
            raise ValueError(
                "MONGODB_CONNECTION_URI must use the mongodb+srv:// scheme "
                "(Atlas connection string).  Local URIs are not supported."
            )
        return v

    # ------------------------------------------------------------------
    # Solana / Helius RPC
    # ------------------------------------------------------------------
    helius_api_key: str
    # Polling interval for ScoutAgent in seconds
    scout_poll_interval: float = 60.0

    # ------------------------------------------------------------------
    # Social API credentials
    # ------------------------------------------------------------------

    # Telegram scraper (user-account API via Telethon)
    telegram_api_id: int
    telegram_api_hash: str
    # Comma-separated channel usernames/IDs to monitor, e.g. "solanatradingalpha,pumpfun_calls"
    telegram_channels: str = ""
    # Telethon session file name (no extension) — stored in project root
    telegram_session_name: str = "moonscout_telegram"

    # Telegram bot (kept for future use — not currently active)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    discord_webhook_url: str

    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_secret: str

    # ------------------------------------------------------------------
    # uagents — deterministic agent seeds (keep secret; used to derive addresses)
    # ------------------------------------------------------------------
    scout_seed: str
    historian_seed: str
    analyst_seed: str
    telegram_agent_seed: str
    discord_agent_seed: str
    x_agent_seed: str

    # ------------------------------------------------------------------
    # ML / scoring config
    # ------------------------------------------------------------------
    # Minimum degen_score to persist a TokenIntelligence doc and broadcast
    degen_score_threshold: float = 70.0


# Module-level singleton — import this everywhere:
#   from moonscout.config import settings
#
# NOTE for tests: Settings() validates .env at import time.  Any test module
# that imports from moonscout.config needs a valid .env (or env vars) to be
# present before collection runs.  Use a conftest.py fixture or pytest-dotenv
# to load a test .env before tests import this module.
settings = Settings()
