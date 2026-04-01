"""
Integration tests for end-to-end wiring (Task 16.1) and shared memory
retention cleanup (Task 16.3).

Task 16.1: Verifies all imports resolve, morning analysis and EOD recap
pipelines can be invoked end-to-end with mocked external APIs, and
Telegram bot commands route correctly.

Task 16.3: Verifies cleanup_shared_memory() removes stale run files
(>30 days) and prunes picks history entries (>365 days), and that
cleanup is wired into the EOD recap pipeline.

Requirements: 1.3, 2.4, 2.6, 11.1, 12.2, 13.2, 13.3, 16.5
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def shared_mem(tmp_path):
    """Set up a temporary shared memory directory with all required files."""
    for subdir in ("runs", "picks", "weights", "config"):
        (tmp_path / subdir).mkdir()

    (tmp_path / "config" / "horizon_state.json").write_text(json.dumps({
        "current_mode": "day_trade",
        "consecutive_days_at_threshold": 0,
        "accuracy_history": [],
        "mode_transitions": [],
    }))

    (tmp_path / "weights" / "learned_weights.json").write_text(json.dumps({
        "updated": "2025-01-01T00:00:00Z",
        "weights": {
            "fundamentals": 0.18, "sentiment": 0.15, "macro": 0.10,
            "news": 0.15, "technical": 0.15, "premarket": 0.12,
            "congress": 0.15,
        },
        "accuracy_data": {},
        "days_evaluated": 0,
    }))

    (tmp_path / "config" / "watchlist.json").write_text(json.dumps({
        "all_tickers": ["AAPL", "NVDA", "MSFT"],
        "sectors": {"big_tech": ["AAPL", "NVDA", "MSFT"]},
        "etf_tickers": [],
    }))

    with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
        yield tmp_path


def _mock_agent_results():
    """Build mock agent results matching the expected structure."""
    agents = ["fundamentals", "sentiment", "macro", "news",
              "technical", "premarket", "congress"]
    results = {}
    for agent in agents:
        results[agent] = {
            "agent_id": agent,
            "run_id": "test_run",
            "status": "complete",
            "results": [
                {"ticker": "NVDA", "score": 8.0, "direction": "CALL"},
                {"ticker": "AAPL", "score": 6.5, "direction": "CALL"},
                {"ticker": "MSFT", "score": 3.5, "direction": "PUT"},
            ],
        }
    return results


# ===========================================================================
# Task 16.1 — Import Verification (Req 1.3)
# ===========================================================================

class TestImportVerification:
    """Verify every module in the project can be imported without errors."""

    # All modules that must be importable from the project root
    MODULES = [
        "shared_memory_io",
        "config",
        "tracker",
        "weight_adjuster",
        "horizon_manager",
        "broker.alpaca_client",
        "broker.order_manager",
        "telegram_bot.auth",
        "telegram_bot.bot",
        "telegram_bot.command_router",
        "agents.orchestrator.skills.fleet_launcher",
        "agents.orchestrator.skills.score_combiner",
        "agents.orchestrator.skills.pick_selector",
        "agents.orchestrator.skills.message_formatter",
        "agents.fundamentals.skills.fundamentals_analysis",
        "agents.sentiment.skills.sentiment_analysis",
        "agents.macro.skills.macro_analysis",
        "agents.news.skills.news_analysis",
        "agents.technical.skills.technical_analysis",
        "agents.options_chain.skills.options_analysis",
        "agents.premarket.skills.premarket_analysis",
        "agents.congress.skills.congress_analysis",
        "lambda_handlers.morning_analysis",
        "lambda_handlers.eod_recap",
    ]

    @pytest.mark.parametrize("module_path", MODULES)
    def test_module_imports_successfully(self, module_path):
        """Each project module should import without ImportError."""
        mod = importlib.import_module(module_path)
        assert mod is not None

    def test_no_circular_imports(self):
        """Importing all modules in sequence should not raise circular import errors."""
        for module_path in self.MODULES:
            # Force a fresh import check
            mod = importlib.import_module(module_path)
            assert mod is not None


# ===========================================================================
# Task 16.1 — Morning Analysis Pipeline E2E (Req 1.3, 2.4, 11.1, 13.2)
# ===========================================================================

class TestMorningAnalysisPipelineE2E:
    """End-to-end morning analysis: Lambda → orchestrator → agents →
    shared memory → score combination → pick selection → options
    enrichment → Telegram message delivery."""

    @patch("lambda_handlers.morning_analysis._send_telegram_message", return_value=True)
    @patch("lambda_handlers.morning_analysis.enrich_options_picks", side_effect=lambda x: x)
    @patch("lambda_handlers.morning_analysis.poll_completion")
    @patch("lambda_handlers.morning_analysis.launch_fleet")
    def test_full_morning_pipeline_produces_picks_and_sends_telegram(
        self, mock_launch, mock_poll, mock_enrich, mock_tg, shared_mem
    ):
        from lambda_handlers.morning_analysis import run_morning_analysis

        mock_launch.return_value = {a: "complete" for a in
            ["fundamentals", "sentiment", "macro", "news",
             "technical", "premarket", "congress"]}
        mock_poll.return_value = {
            "results": _mock_agent_results(),
            "timed_out": [],
            "all_complete": True,
        }

        result = run_morning_analysis()

        # Pipeline produces picks
        assert "run_id" in result
        assert isinstance(result["options_picks"], list)
        assert isinstance(result["stock_picks"], list)
        assert len(result["options_picks"]) > 0 or len(result["stock_picks"]) > 0

        # Telegram message was sent
        assert mock_tg.called

        # Picks were logged to history
        picks_file = shared_mem / "picks" / "picks_history.json"
        assert picks_file.exists()
        history = json.loads(picks_file.read_text())
        assert len(history) >= 1
        assert history[-1]["date"] == str(date.today())

    @patch("lambda_handlers.morning_analysis._send_telegram_message", return_value=True)
    @patch("lambda_handlers.morning_analysis.enrich_options_picks", side_effect=lambda x: x)
    @patch("lambda_handlers.morning_analysis.poll_completion")
    @patch("lambda_handlers.morning_analysis.launch_fleet")
    def test_morning_handler_returns_200(
        self, mock_launch, mock_poll, mock_enrich, mock_tg, shared_mem
    ):
        from lambda_handlers.morning_analysis import handler

        mock_launch.return_value = {}
        mock_poll.return_value = {
            "results": _mock_agent_results(),
            "timed_out": [],
            "all_complete": True,
        }

        resp = handler({}, None)
        assert resp["statusCode"] == 200
        assert "run_id" in resp["body"]
        assert resp["body"]["horizon"] == "day_trade"


# ===========================================================================
# Task 16.1 — EOD Recap Pipeline E2E (Req 13.3, 2.4)
# ===========================================================================

class TestEodRecapPipelineE2E:
    """End-to-end EOD recap: Lambda → evaluation → broker P&L →
    weight adjustment → horizon check → Telegram recap + cleanup."""

    @patch("lambda_handlers.eod_recap._send_telegram_message", return_value=True)
    @patch("lambda_handlers.eod_recap.AlpacaClient")
    @patch("lambda_handlers.eod_recap.check_transition")
    @patch("lambda_handlers.eod_recap.update_weights")
    @patch("lambda_handlers.eod_recap.evaluate_end_of_day")
    @patch("lambda_handlers.eod_recap.cleanup_shared_memory")
    def test_full_eod_pipeline(
        self, mock_cleanup, mock_eval, mock_weights, mock_horizon,
        mock_broker_cls, mock_tg, shared_mem
    ):
        from lambda_handlers.eod_recap import run_eod_recap

        mock_eval.return_value = {
            "date": str(date.today()),
            "options": [
                {"ticker": "NVDA", "direction": "CALL", "correct": True,
                 "open": 120.0, "close": 125.0, "change_pct": 4.17, "est_pnl": 250.0},
            ],
            "stocks": [
                {"ticker": "AAPL", "direction": "CALL", "correct": False,
                 "open": 180.0, "close": 178.0, "change_pct": -1.11},
            ],
            "total_pnl": 250.0,
        }

        mock_weights.return_value = {
            "weights_updated": True,
            "weights": {"fundamentals": 0.20},
            "days_evaluated": 10,
        }

        mock_horizon.return_value = {
            "current_mode": "day_trade",
            "transition": None,
            "notification": None,
        }

        mock_broker = MagicMock()
        mock_broker.get_account.return_value = {
            "daily_pnl": 150.0, "equity": 10150.0,
            "cash": 5000.0, "buying_power": 10000.0,
        }
        mock_broker_cls.return_value = mock_broker

        mock_cleanup.return_value = {"runs_deleted": 2, "picks_pruned": 0}

        result = run_eod_recap()

        # All pipeline stages executed
        mock_eval.assert_called_once()
        mock_weights.assert_called_once()
        mock_horizon.assert_called_once()
        mock_cleanup.assert_called_once()

        # Telegram message sent
        assert mock_tg.called

        # Result contains all expected keys
        assert "eod_results" in result
        assert "broker_pnl" in result
        assert "accuracy" in result
        assert "weight_update" in result
        assert "horizon" in result
        assert "cleanup" in result
        assert result["cleanup"]["runs_deleted"] == 2


# ===========================================================================
# Task 16.1 — Telegram Command Routing (Req 12.2)
# ===========================================================================

class TestTelegramCommandRouting:
    """Verify Telegram bot commands route correctly to orchestrator,
    broker, and watchlist management."""

    @pytest.fixture
    def router(self):
        from telegram_bot.command_router import CommandRouter
        return CommandRouter()

    @pytest.fixture
    def mock_update(self):
        update = MagicMock()
        update.effective_message = MagicMock()
        update.effective_message.reply_text = MagicMock(
            return_value=MagicMock()  # async mock
        )
        return update

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.user_data = {}
        return ctx

    @pytest.mark.asyncio
    async def test_start_command(self, router, mock_update, mock_context):
        result = await router.handle("start", [], mock_update, mock_context)
        assert "OpenClaw" in result
        assert "Welcome" in result

    @pytest.mark.asyncio
    async def test_help_command(self, router, mock_update, mock_context):
        result = await router.handle("help", [], mock_update, mock_context)
        assert "/picks" in result
        assert "/buy" in result
        assert "/sell" in result
        assert "/positions" in result

    @pytest.mark.asyncio
    async def test_unknown_command_returns_help(
        self, router, mock_update, mock_context
    ):
        result = await router.handle(
            "nonexistent_cmd", [], mock_update, mock_context
        )
        assert "/picks" in result  # help text

    @pytest.mark.asyncio
    async def test_add_ticker_to_watchlist(
        self, router, mock_update, mock_context, shared_mem
    ):
        result = await router.handle(
            "add", ["PLTR"], mock_update, mock_context
        )
        assert "Added" in result or "already" in result

    @pytest.mark.asyncio
    async def test_remove_ticker_from_watchlist(
        self, router, mock_update, mock_context, shared_mem
    ):
        result = await router.handle(
            "remove", ["AAPL"], mock_update, mock_context
        )
        assert "Removed" in result or "not in" in result


# ===========================================================================
# Task 16.3 — Shared Memory Retention Cleanup (Req 2.6, 16.5)
# ===========================================================================

class TestSharedMemoryCleanup:
    """Verify cleanup_shared_memory() removes stale run files and
    prunes old picks history entries."""

    def test_cleanup_removes_old_run_files(self, shared_mem):
        from shared_memory_io import cleanup_shared_memory

        runs_dir = shared_mem / "runs"

        # Create a "fresh" file (today)
        fresh = runs_dir / "fundamentals_20250101_053000.md"
        fresh.write_text("# fresh result")

        # Create an "old" file and backdate its mtime to 45 days ago
        old = runs_dir / "sentiment_20241115_053000.md"
        old.write_text("# old result")
        old_mtime = time.time() - (45 * 86400)
        os.utime(str(old), (old_mtime, old_mtime))

        result = cleanup_shared_memory()

        assert result["runs_deleted"] == 1
        assert not old.exists()
        assert fresh.exists()

    def test_cleanup_keeps_recent_run_files(self, shared_mem):
        from shared_memory_io import cleanup_shared_memory

        runs_dir = shared_mem / "runs"

        # Create files within the 30-day window
        for i in range(3):
            f = runs_dir / f"agent_{i}_run.md"
            f.write_text(f"# result {i}")

        result = cleanup_shared_memory()
        assert result["runs_deleted"] == 0

    def test_cleanup_prunes_old_picks_history(self, shared_mem):
        from shared_memory_io import cleanup_shared_memory

        picks_dir = shared_mem / "picks"
        today = date.today()

        history = [
            # Old entry — 400 days ago
            {
                "date": str(today - timedelta(days=400)),
                "options_picks": [],
                "stock_picks": [],
            },
            # Recent entry — 10 days ago
            {
                "date": str(today - timedelta(days=10)),
                "options_picks": [],
                "stock_picks": [],
            },
            # Today's entry
            {
                "date": str(today),
                "options_picks": [],
                "stock_picks": [],
            },
        ]
        (picks_dir / "picks_history.json").write_text(
            json.dumps(history, indent=2)
        )

        result = cleanup_shared_memory()

        assert result["picks_pruned"] == 1

        # Verify the old entry was removed
        kept = json.loads(
            (picks_dir / "picks_history.json").read_text()
        )
        assert len(kept) == 2
        dates = [e["date"] for e in kept]
        assert str(today - timedelta(days=400)) not in dates

    def test_cleanup_retains_365_day_picks(self, shared_mem):
        from shared_memory_io import cleanup_shared_memory

        picks_dir = shared_mem / "picks"
        today = date.today()

        # Entry exactly at 365 days should be kept
        history = [
            {
                "date": str(today - timedelta(days=365)),
                "options_picks": [],
                "stock_picks": [],
            },
        ]
        (picks_dir / "picks_history.json").write_text(
            json.dumps(history, indent=2)
        )

        result = cleanup_shared_memory()
        assert result["picks_pruned"] == 0

    def test_cleanup_handles_empty_directories(self, shared_mem):
        from shared_memory_io import cleanup_shared_memory

        result = cleanup_shared_memory()
        assert result["runs_deleted"] == 0
        assert result["picks_pruned"] == 0


class TestCleanupWiredIntoEodRecap:
    """Verify cleanup_shared_memory is called as part of EOD recap."""

    @patch("lambda_handlers.eod_recap._send_telegram_message", return_value=True)
    @patch("lambda_handlers.eod_recap.AlpacaClient")
    @patch("lambda_handlers.eod_recap.check_transition")
    @patch("lambda_handlers.eod_recap.update_weights")
    @patch("lambda_handlers.eod_recap.evaluate_end_of_day")
    @patch("lambda_handlers.eod_recap.cleanup_shared_memory")
    def test_eod_recap_calls_cleanup(
        self, mock_cleanup, mock_eval, mock_weights, mock_horizon,
        mock_broker_cls, mock_tg, shared_mem
    ):
        from lambda_handlers.eod_recap import run_eod_recap

        mock_eval.return_value = {"options": [], "stocks": [], "total_pnl": 0}
        mock_weights.return_value = {"weights_updated": False, "days_evaluated": 0}
        mock_horizon.return_value = {
            "current_mode": "day_trade", "transition": None, "notification": None,
        }
        mock_broker = MagicMock()
        mock_broker.get_account.return_value = {
            "daily_pnl": 0, "equity": 10000, "cash": 5000, "buying_power": 10000,
        }
        mock_broker_cls.return_value = mock_broker
        mock_cleanup.return_value = {"runs_deleted": 0, "picks_pruned": 0}

        result = run_eod_recap()

        mock_cleanup.assert_called_once()
        assert "cleanup" in result
