"""
Tests for Telegram bot: auth, command routing, and message formatting.

Requirements: 12.8, 19.5, 22.5
"""

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Auth tests (Requirement 22.5)
# ---------------------------------------------------------------------------

class TestAuth:
    """Test user ID allowlist authentication."""

    def setup_method(self):
        """Reset cached allowed IDs before each test."""
        from telegram_bot import auth
        auth._allowed_ids = None

    def test_authorized_user(self):
        from telegram_bot.auth import is_authorized, reload_allowed_ids
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "123,456,789"}):
            reload_allowed_ids()
            assert is_authorized(123) is True
            assert is_authorized(456) is True
            assert is_authorized(789) is True

    def test_unauthorized_user(self):
        from telegram_bot.auth import is_authorized, reload_allowed_ids
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "123,456"}):
            reload_allowed_ids()
            assert is_authorized(999) is False

    def test_empty_allowlist_rejects_all(self):
        from telegram_bot.auth import is_authorized, reload_allowed_ids
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": ""}):
            reload_allowed_ids()
            assert is_authorized(123) is False

    def test_missing_env_var_rejects_all(self):
        from telegram_bot.auth import is_authorized, reload_allowed_ids
        env = os.environ.copy()
        env.pop("ALLOWED_USER_IDS", None)
        with patch.dict(os.environ, env, clear=True):
            reload_allowed_ids()
            assert is_authorized(123) is False

    def test_invalid_ids_ignored(self):
        from telegram_bot.auth import load_allowed_user_ids
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": "123,abc,456"}):
            ids = load_allowed_user_ids()
            assert ids == {123, 456}

    def test_whitespace_handling(self):
        from telegram_bot.auth import load_allowed_user_ids
        with patch.dict(os.environ, {"ALLOWED_USER_IDS": " 123 , 456 , 789 "}):
            ids = load_allowed_user_ids()
            assert ids == {123, 456, 789}


# ---------------------------------------------------------------------------
# Command Router tests (Requirement 12.8)
# ---------------------------------------------------------------------------

class TestCommandRouter:
    """Test command parsing and routing."""

    def _make_update_context(self):
        """Create mock Update and Context objects."""
        update = MagicMock()
        update.effective_message = AsyncMock()
        update.effective_message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123

        context = MagicMock()
        context.args = []
        context.user_data = {}
        return update, context

    @pytest.mark.asyncio
    async def test_start_command(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("start", [], update, context)
        assert "OpenClaw Market Intel Bot" in result

    @pytest.mark.asyncio
    async def test_help_command(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("help", [], update, context)
        assert "/picks" in result
        assert "/analyze" in result
        assert "/buy" in result
        assert "/sell" in result
        assert "/positions" in result
        assert "/account" in result
        assert "/add" in result
        assert "/remove" in result

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        # Unknown command falls through to help
        result = await router.handle("nonexistent", [], update, context)
        assert "/picks" in result  # help text

    @pytest.mark.asyncio
    async def test_analyze_no_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("analyze", [], update, context)
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_buy_no_args(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("buy", [], update, context)
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_buy_invalid_qty(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("buy", ["NVDA", "abc"], update, context)
        assert "number" in result.lower()

    @pytest.mark.asyncio
    async def test_buy_negative_qty(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("buy", ["NVDA", "-5"], update, context)
        assert "positive" in result.lower()

    @pytest.mark.asyncio
    async def test_sell_no_args(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("sell", [], update, context)
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_sell_stub_broker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("sell", ["AAPL", "10"], update, context)
        # Should work with stub broker
        assert "AAPL" in result or "Broker" in result

    @pytest.mark.asyncio
    async def test_buy_stub_broker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("buy", ["NVDA", "5"], update, context)
        assert "NVDA" in result or "Broker" in result

    @pytest.mark.asyncio
    async def test_positions_stub(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("positions", [], update, context)
        assert "Positions" in result or "positions" in result or "broker" in result.lower()

    @pytest.mark.asyncio
    async def test_account_stub(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("account", [], update, context)
        assert "Account" in result

    @pytest.mark.asyncio
    async def test_close_all_stub(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("close_all", [], update, context)
        assert "Broker" in result or "close" in result.lower()

    @pytest.mark.asyncio
    async def test_add_no_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("add", [], update, context)
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_remove_no_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("remove", [], update, context)
        assert "Usage" in result

    @pytest.mark.asyncio
    async def test_buy_by_pick_number_no_picks(self):
        from telegram_bot.command_router import CommandRouter, _last_picks
        _last_picks["stocks"] = []
        _last_picks["options"] = []
        router = CommandRouter()
        update, context = self._make_update_context()
        result = await router.handle("buy", ["1"], update, context)
        assert "No morning picks" in result


# ---------------------------------------------------------------------------
# Watchlist command tests (Requirements 17.2, 17.3, 17.5)
# ---------------------------------------------------------------------------

class TestWatchlistCommands:
    """Test /add and /remove watchlist commands."""

    def _make_update_context(self):
        update = MagicMock()
        update.effective_message = AsyncMock()
        update.effective_message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 123
        context = MagicMock()
        context.args = []
        context.user_data = {}
        return update, context

    @pytest.mark.asyncio
    async def test_add_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()

        mock_watchlist = {
            "all_tickers": ["AAPL", "MSFT"],
            "sectors": {"big_tech": ["AAPL", "MSFT"]},
        }

        mock_io = MagicMock()
        mock_io.load_watchlist.return_value = mock_watchlist.copy()
        with patch.dict("sys.modules", {"shared_memory_io": mock_io}):
            result = await router.handle("add", ["PLTR"], update, context)
            assert "Added" in result
            assert "PLTR" in result
            mock_io.save_watchlist.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_duplicate_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()

        mock_watchlist = {
            "all_tickers": ["AAPL", "MSFT"],
            "sectors": {"big_tech": ["AAPL", "MSFT"]},
        }

        mock_io = MagicMock()
        mock_io.load_watchlist.return_value = mock_watchlist
        with patch.dict("sys.modules", {"shared_memory_io": mock_io}):
            result = await router.handle("add", ["AAPL"], update, context)
            assert "already" in result.lower()

    @pytest.mark.asyncio
    async def test_remove_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()

        mock_watchlist = {
            "all_tickers": ["AAPL", "MSFT", "PLTR"],
            "sectors": {"big_tech": ["AAPL", "MSFT"], "custom": ["PLTR"]},
        }

        mock_io = MagicMock()
        mock_io.load_watchlist.return_value = mock_watchlist
        with patch.dict("sys.modules", {"shared_memory_io": mock_io}):
            result = await router.handle("remove", ["PLTR"], update, context)
            assert "Removed" in result
            assert "PLTR" in result
            mock_io.save_watchlist.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_nonexistent_ticker(self):
        from telegram_bot.command_router import CommandRouter
        router = CommandRouter()
        update, context = self._make_update_context()

        mock_watchlist = {
            "all_tickers": ["AAPL", "MSFT"],
            "sectors": {"big_tech": ["AAPL", "MSFT"]},
        }

        mock_io = MagicMock()
        mock_io.load_watchlist.return_value = mock_watchlist
        with patch.dict("sys.modules", {"shared_memory_io": mock_io}):
            result = await router.handle("remove", ["XYZ"], update, context)
            assert "not in" in result.lower()


# ---------------------------------------------------------------------------
# Message Formatter tests (Requirement 19.5)
# ---------------------------------------------------------------------------

class TestMessageFormatter:
    """Test message formatting and truncation."""

    def test_split_message_short(self):
        from agents.orchestrator.skills.message_formatter import split_message
        text = "Hello world"
        chunks = split_message(text, 4096)
        assert chunks == ["Hello world"]

    def test_split_message_long(self):
        from agents.orchestrator.skills.message_formatter import split_message
        # Create a message longer than 100 chars
        text = "Line\n" * 30  # 150 chars
        chunks = split_message(text, 50)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_truncate_message(self):
        from agents.orchestrator.skills.message_formatter import truncate_message
        text = "A" * 5000
        result = truncate_message(text, 4096)
        assert len(result) == 4096
        assert result.endswith("…")

    def test_truncate_short_message(self):
        from agents.orchestrator.skills.message_formatter import truncate_message
        text = "Short message"
        result = truncate_message(text, 4096)
        assert result == text

    def test_direction_emoji(self):
        from agents.orchestrator.skills.message_formatter import _direction_emoji
        assert _direction_emoji("CALL") == "🟢"
        assert _direction_emoji("BUY") == "🟢"
        assert _direction_emoji("PUT") == "🔴"
        assert _direction_emoji("SELL") == "🔴"
        assert _direction_emoji("SELL/SHORT") == "🔴"
        assert _direction_emoji("HOLD") == "🟡"

    def test_format_morning_analysis_empty(self):
        from agents.orchestrator.skills.message_formatter import format_morning_analysis
        result = format_morning_analysis({
            "options_picks": [],
            "stock_picks": [],
            "premarket_data": [],
            "combined": [],
        })
        assert "OpenClaw Morning Analysis" in result
        assert "Not financial advice" in result
        assert "$1,000" in result

    def test_format_morning_analysis_with_picks(self):
        from agents.orchestrator.skills.message_formatter import format_morning_analysis
        result = format_morning_analysis({
            "options_picks": [
                {
                    "ticker": "NVDA",
                    "direction": "CALL",
                    "composite_score": 8.5,
                    "confidence": "HIGH",
                    "option_contract": {
                        "strike": 128,
                        "expiry": "2026-01-17",
                        "mid_price": 2.45,
                        "volume": 1523,
                        "open_interest": 8900,
                        "implied_volatility": 0.42,
                    },
                },
            ],
            "stock_picks": [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "composite_score": 7.2,
                    "confidence": "MEDIUM",
                    "agent_scores": {
                        "fundamentals": {"score": 8.0, "direction": "CALL"},
                        "technical": {"score": 6.5, "direction": "CALL"},
                    },
                },
            ],
            "premarket_data": [],
            "combined": [],
        })
        assert "NVDA" in result
        assert "CALL" in result
        assert "AAPL" in result
        assert "BUY" in result
        assert "🟢" in result
        assert "$128" in result or "128" in result

    def test_format_eod_recap(self):
        from agents.orchestrator.skills.message_formatter import format_eod_recap
        result = format_eod_recap({
            "broker_pnl": {"daily_pnl": "125.50", "equity": "10125.50"},
            "trade_results": [
                {"ticker": "NVDA", "action": "BUY", "realized_pnl": "50.00"},
            ],
            "options_accuracy": 60.0,
            "stock_accuracy": 70.0,
            "overall_accuracy": 65.0,
            "weight_update": {"days_evaluated": 8, "weights_updated": True},
            "horizon_status": {"current_mode": "day_trade"},
        })
        assert "EOD Recap" in result
        assert "125.50" in result
        assert "60.0%" in result
        assert "70.0%" in result
        assert "65.0%" in result
        assert "Weights updated" in result

    def test_format_eod_recap_negative_pnl(self):
        from agents.orchestrator.skills.message_formatter import format_eod_recap
        result = format_eod_recap({
            "broker_pnl": {"daily_pnl": "-50.00", "equity": "9950.00"},
            "trade_results": [],
            "options_accuracy": "N/A",
            "stock_accuracy": "N/A",
            "overall_accuracy": "N/A",
            "weight_update": {"days_evaluated": 2, "weights_updated": False},
            "horizon_status": {"current_mode": "day_trade"},
        })
        assert "🔴" in result
        assert "-50.00" in result
        assert "unchanged" in result.lower() or "need" in result.lower()

    def test_morning_message_under_4096(self):
        """Verify a typical morning message fits within Telegram's limit."""
        from agents.orchestrator.skills.message_formatter import format_morning_analysis
        result = format_morning_analysis({
            "options_picks": [
                {"ticker": f"T{i}", "direction": "CALL" if i % 2 == 0 else "PUT",
                 "composite_score": 7.0 + i * 0.1, "confidence": "HIGH",
                 "option_contract": {"strike": 100 + i, "expiry": "2026-01-17",
                                     "mid_price": 2.0, "volume": 1000,
                                     "open_interest": 5000, "implied_volatility": 0.35}}
                for i in range(5)
            ],
            "stock_picks": [
                {"ticker": f"S{i}", "action": "BUY", "composite_score": 6.5 + i * 0.1,
                 "confidence": "MEDIUM", "agent_scores": {
                     "fundamentals": {"score": 7.0, "direction": "CALL"}}}
                for i in range(10)
            ],
            "premarket_data": [],
            "combined": [],
        })
        assert len(result) <= 4096


# ---------------------------------------------------------------------------
# Bot message splitting tests
# ---------------------------------------------------------------------------

class TestBotMessageSplitting:
    """Test the bot's message splitting utility."""

    def test_split_short_message(self):
        from telegram_bot.bot import split_message
        chunks = split_message("Hello", 4096)
        assert chunks == ["Hello"]

    def test_split_at_newline(self):
        from telegram_bot.bot import split_message
        text = "A" * 40 + "\n" + "B" * 40
        chunks = split_message(text, 50)
        assert len(chunks) == 2
        assert chunks[0] == "A" * 40
        assert chunks[1] == "B" * 40

    def test_split_no_newline(self):
        from telegram_bot.bot import split_message
        text = "A" * 100
        chunks = split_message(text, 50)
        assert len(chunks) == 2
        assert len(chunks[0]) == 50
        assert len(chunks[1]) == 50
