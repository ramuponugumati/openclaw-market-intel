"""
Unit tests for config.py — credential validation and environment setup.

Validates Requirements: 22.1, 22.2, 22.3, 22.4
"""

import os
import pytest
from unittest.mock import patch

from config import (
    Config,
    REQUIRED_KEYS,
    validate_env,
    load_config,
    _parse_allowed_user_ids,
)


def _full_env() -> dict[str, str]:
    """Return a complete set of valid environment variables."""
    return {
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "FINNHUB_API_KEY": "fh-test-key",
        "FRED_API_KEY": "fred-test-key",
        "ALPACA_API_KEY": "alpaca-test-key",
        "ALPACA_SECRET_KEY": "alpaca-secret-test",
        "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
        "QUIVER_API_KEY": "quiver-test-key",
    }


class TestValidateEnv:
    """Tests for validate_env() — Requirement 22.3."""

    def test_all_keys_present(self):
        with patch.dict(os.environ, _full_env(), clear=True):
            missing = validate_env()
        assert missing == []

    def test_single_missing_key(self):
        env = _full_env()
        del env["FRED_API_KEY"]
        with patch.dict(os.environ, env, clear=True):
            missing = validate_env()
        assert missing == ["FRED_API_KEY"]

    def test_multiple_missing_keys(self):
        env = _full_env()
        del env["ANTHROPIC_API_KEY"]
        del env["TELEGRAM_BOT_TOKEN"]
        with patch.dict(os.environ, env, clear=True):
            missing = validate_env()
        assert "ANTHROPIC_API_KEY" in missing
        assert "TELEGRAM_BOT_TOKEN" in missing
        assert len(missing) == 2

    def test_empty_string_treated_as_missing(self):
        env = _full_env()
        env["FINNHUB_API_KEY"] = ""
        with patch.dict(os.environ, env, clear=True):
            missing = validate_env()
        assert missing == ["FINNHUB_API_KEY"]

    def test_whitespace_only_treated_as_missing(self):
        env = _full_env()
        env["ALPACA_API_KEY"] = "   "
        with patch.dict(os.environ, env, clear=True):
            missing = validate_env()
        assert missing == ["ALPACA_API_KEY"]


class TestLoadConfig:
    """Tests for load_config() — Requirements 22.1, 22.3, 22.4."""

    def test_loads_all_keys_successfully(self):
        with patch.dict(os.environ, _full_env(), clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.anthropic_api_key == "sk-ant-test-key"
        assert cfg.finnhub_api_key == "fh-test-key"
        assert cfg.fred_api_key == "fred-test-key"
        assert cfg.alpaca_api_key == "alpaca-test-key"
        assert cfg.alpaca_secret_key == "alpaca-secret-test"
        assert cfg.telegram_bot_token == "123456:ABC-DEF"
        assert cfg.quiver_api_key == "quiver-test-key"

    def test_raises_on_missing_keys(self):
        env = _full_env()
        del env["FRED_API_KEY"]
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="FRED_API_KEY"):
                load_config(exit_on_missing=False)

    def test_alpaca_mode_defaults_to_paper(self):
        with patch.dict(os.environ, _full_env(), clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.alpaca_mode == "paper"

    def test_alpaca_mode_paper_explicit(self):
        env = {**_full_env(), "ALPACA_MODE": "paper"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.alpaca_mode == "paper"
        assert cfg.alpaca_base_url == "https://paper-api.alpaca.markets"

    def test_alpaca_mode_live_explicit(self):
        env = {**_full_env(), "ALPACA_MODE": "live"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.alpaca_mode == "live"
        assert cfg.alpaca_base_url == "https://api.alpaca.markets"

    def test_alpaca_mode_invalid_defaults_to_paper(self):
        env = {**_full_env(), "ALPACA_MODE": "yolo"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.alpaca_mode == "paper"

    def test_alpaca_mode_case_insensitive(self):
        env = {**_full_env(), "ALPACA_MODE": "LIVE"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.alpaca_mode == "live"

    def test_strips_whitespace_from_keys(self):
        env = _full_env()
        env["ANTHROPIC_API_KEY"] = "  sk-ant-test-key  "
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.anthropic_api_key == "sk-ant-test-key"

    def test_config_is_immutable(self):
        with patch.dict(os.environ, _full_env(), clear=True):
            cfg = load_config(exit_on_missing=False)
        with pytest.raises(AttributeError):
            cfg.alpaca_mode = "live"


class TestAllowedUserIds:
    """Tests for ALLOWED_USER_IDS parsing."""

    def test_parses_comma_separated_ids(self):
        ids = _parse_allowed_user_ids("123,456,789")
        assert ids == [123, 456, 789]

    def test_handles_empty_string(self):
        assert _parse_allowed_user_ids("") == []

    def test_handles_whitespace(self):
        ids = _parse_allowed_user_ids(" 123 , 456 ")
        assert ids == [123, 456]

    def test_skips_invalid_entries(self):
        ids = _parse_allowed_user_ids("123,abc,456")
        assert ids == [123, 456]

    def test_loaded_in_config(self):
        env = {**_full_env(), "ALLOWED_USER_IDS": "111,222"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(exit_on_missing=False)
        assert cfg.allowed_user_ids == [111, 222]
