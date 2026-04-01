"""
Configuration and Credential Validation Module

Loads all API keys and settings from environment variables at startup.
Validates that required credentials are present and logs clear error
messages identifying any missing keys before terminating.

Requirements: 22.1, 22.2, 22.3, 22.4
"""

import logging
import os
import sys
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# All required API keys — each must be set and non-empty
REQUIRED_KEYS = [
    "ANTHROPIC_API_KEY",
    "FINNHUB_API_KEY",
    "FRED_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "QUIVER_API_KEY",
]

VALID_ALPACA_MODES = ("paper", "live")


@dataclass(frozen=True)
class Config:
    """Immutable configuration loaded from environment variables."""

    anthropic_api_key: str
    finnhub_api_key: str
    fred_api_key: str
    alpaca_api_key: str
    alpaca_secret_key: str
    telegram_bot_token: str
    quiver_api_key: str
    alpaca_mode: str = "paper"
    allowed_user_ids: list[int] = field(default_factory=list)

    @property
    def alpaca_base_url(self) -> str:
        """Return the Alpaca API base URL based on the current mode."""
        if self.alpaca_mode == "live":
            return "https://api.alpaca.markets"
        return "https://paper-api.alpaca.markets"


def _parse_allowed_user_ids(raw: str) -> list[int]:
    """Parse comma-separated Telegram user IDs into a list of ints."""
    if not raw or not raw.strip():
        return []
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                logger.warning("Ignoring invalid ALLOWED_USER_IDS entry: %s", part)
    return ids


def validate_env() -> list[str]:
    """
    Check that all required environment variables are set and non-empty.

    Returns a list of missing key names (empty list means all present).
    """
    missing = []
    for key in REQUIRED_KEYS:
        value = os.environ.get(key, "").strip()
        if not value:
            missing.append(key)
    return missing


def load_config(*, exit_on_missing: bool = True) -> Config:
    """
    Load and validate configuration from environment variables.

    Args:
        exit_on_missing: If True (default), log errors and call sys.exit(1)
            when required keys are missing. Set to False for testing.

    Returns:
        A validated Config instance.

    Raises:
        SystemExit: When exit_on_missing is True and keys are missing.
        ValueError: When exit_on_missing is False and keys are missing.
    """
    missing = validate_env()

    if missing:
        for key in missing:
            logger.error("Missing required environment variable: %s", key)
        logger.error(
            "The following %d API key(s) must be set: %s",
            len(missing),
            ", ".join(missing),
        )
        if exit_on_missing:
            sys.exit(1)
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    # Load ALPACA_MODE with safe default
    alpaca_mode = os.environ.get("ALPACA_MODE", "paper").strip().lower()
    if alpaca_mode not in VALID_ALPACA_MODES:
        logger.warning(
            "Invalid ALPACA_MODE '%s' — defaulting to 'paper'. "
            "Set ALPACA_MODE=live explicitly for live trading.",
            alpaca_mode,
        )
        alpaca_mode = "paper"

    if alpaca_mode == "live":
        logger.warning(
            "ALPACA_MODE is set to 'live' — REAL MONEY trading is enabled."
        )
    else:
        logger.info("ALPACA_MODE is 'paper' — using paper trading.")

    allowed_user_ids = _parse_allowed_user_ids(
        os.environ.get("ALLOWED_USER_IDS", "")
    )

    return Config(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"].strip(),
        finnhub_api_key=os.environ["FINNHUB_API_KEY"].strip(),
        fred_api_key=os.environ["FRED_API_KEY"].strip(),
        alpaca_api_key=os.environ["ALPACA_API_KEY"].strip(),
        alpaca_secret_key=os.environ["ALPACA_SECRET_KEY"].strip(),
        telegram_bot_token=os.environ["TELEGRAM_BOT_TOKEN"].strip(),
        quiver_api_key=os.environ["QUIVER_API_KEY"].strip(),
        alpaca_mode=alpaca_mode,
        allowed_user_ids=allowed_user_ids,
    )
