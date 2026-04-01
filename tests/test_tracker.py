"""
Tests for tracker, weight adjustment, horizon progression, and EOD recap.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 16.1, 16.2, 16.5,
              18.1, 18.2, 18.3, 18.4, 18.5, 13.3, 19.4
"""

import json
import os
import sys
from datetime import date, timedelta
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
    """Set up a temporary shared memory directory."""
    picks_dir = tmp_path / "picks"
    picks_dir.mkdir()
    weights_dir = tmp_path / "weights"
    weights_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Write default horizon state
    horizon = {
        "current_mode": "day_trade",
        "consecutive_days_at_threshold": 0,
        "accuracy_history": [],
        "mode_transitions": [],
    }
    (config_dir / "horizon_state.json").write_text(json.dumps(horizon))

    # Write default weights
    weights = {
        "updated": "2025-01-01T00:00:00Z",
        "weights": {
            "fundamentals": 0.18, "sentiment": 0.15, "macro": 0.10,
            "news": 0.15, "technical": 0.15, "premarket": 0.12, "congress": 0.15,
        },
        "accuracy_data": {},
        "days_evaluated": 0,
    }
    (weights_dir / "learned_weights.json").write_text(json.dumps(weights))

    with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
        yield tmp_path


def _make_options_picks():
    return [
        {
            "ticker": "NVDA",
            "direction": "CALL",
            "composite_score": 8.5,
            "confidence": "HIGH",
            "option_contract": {"strike": 128, "expiry": "2026-01-17"},
            "agent_scores": {
                "fundamentals": {"score": 8.5, "direction": "CALL"},
                "sentiment": {"score": 7.0, "direction": "CALL"},
            },
        },
    ]


def _make_stock_picks():
    return [
        {
            "ticker": "AAPL",
            "direction": "CALL",
            "action": "BUY",
            "composite_score": 7.2,
            "confidence": "MEDIUM",
            "agent_scores": {
                "fundamentals": {"score": 6.5, "direction": "CALL"},
                "technical": {"score": 7.8, "direction": "CALL"},
            },
        },
    ]


# ===========================================================================
# Task 11.1 — Pick Tracker (Req 16.1, 16.2, 16.5)
# ===========================================================================

class TestLogMorningPicks:
    """Req 16.1: Log morning picks with all required fields."""

    def test_log_creates_history_file(self, shared_mem):
        from tracker import log_morning_picks, _load_picks_history

        log_morning_picks(_make_options_picks(), _make_stock_picks())
        history = _load_picks_history()
        assert len(history) == 1

    def test_log_contains_required_fields(self, shared_mem):
        from tracker import log_morning_picks, _load_picks_history

        log_morning_picks(_make_options_picks(), _make_stock_picks(), run_id="test_run")
        entry = _load_picks_history()[0]

        assert entry["date"] == str(date.today())
        assert entry["run_id"] == "test_run"
        assert entry["horizon"] == "day_trade"
        assert entry["eod_results"] is None

        opt = entry["options_picks"][0]
        assert opt["ticker"] == "NVDA"
        assert opt["direction"] == "CALL"
        assert opt["composite_score"] == 8.5
        assert opt["confidence"] == "HIGH"
        assert "agents" in opt

        stk = entry["stock_picks"][0]
        assert stk["ticker"] == "AAPL"
        assert stk["trade_action"] == "BUY"

    def test_multiple_logs_append(self, shared_mem):
        from tracker import log_morning_picks, _load_picks_history

        log_morning_picks(_make_options_picks(), _make_stock_picks())
        log_morning_picks(_make_options_picks(), _make_stock_picks())
        assert len(_load_picks_history()) == 2

    def test_history_retention_prunes_old(self, shared_mem):
        from tracker import _load_picks_history, _save_picks_history, _prune_old_entries

        old_date = str(date.today() - timedelta(days=400))
        recent_date = str(date.today() - timedelta(days=10))

        history = [
            {"date": old_date, "options_picks": [], "stock_picks": [], "eod_results": None},
            {"date": recent_date, "options_picks": [], "stock_picks": [], "eod_results": None},
        ]
        pruned = _prune_old_entries(history)
        assert len(pruned) == 1
        assert pruned[0]["date"] == recent_date


class TestEvaluateEndOfDay:
    """Req 16.2: EOD evaluation computes correctness and P&L."""

    def test_evaluate_with_no_picks_returns_error(self, shared_mem):
        from tracker import evaluate_end_of_day
        result = evaluate_end_of_day()
        assert "error" in result

    @patch("tracker.yf")
    def test_evaluate_correct_call(self, mock_yf, shared_mem):
        from tracker import log_morning_picks, evaluate_end_of_day

        log_morning_picks(_make_options_picks(), _make_stock_picks())

        # Mock yfinance: close > open → CALL is correct
        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.__getitem__ = lambda self, key: MagicMock(
            iloc=MagicMock(__getitem__=lambda s, i: 130.0 if key == "Close" else 125.0)
        )
        mock_yf.Ticker.return_value.history.return_value = mock_hist

        result = evaluate_end_of_day()
        assert "error" not in result
        assert len(result["options"]) == 1
        assert result["options"][0]["correct"] is True
        assert result["options"][0]["est_pnl"] > 0

    @patch("tracker.yf")
    def test_evaluate_incorrect_call(self, mock_yf, shared_mem):
        from tracker import log_morning_picks, evaluate_end_of_day

        log_morning_picks(_make_options_picks(), _make_stock_picks())

        # Mock yfinance: close < open → CALL is incorrect
        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.__getitem__ = lambda self, key: MagicMock(
            iloc=MagicMock(__getitem__=lambda s, i: 120.0 if key == "Close" else 125.0)
        )
        mock_yf.Ticker.return_value.history.return_value = mock_hist

        result = evaluate_end_of_day()
        assert result["options"][0]["correct"] is False

    @patch("tracker.yf")
    def test_evaluate_appends_to_history(self, mock_yf, shared_mem):
        from tracker import log_morning_picks, evaluate_end_of_day, _load_picks_history

        log_morning_picks(_make_options_picks(), _make_stock_picks())

        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.__getitem__ = lambda self, key: MagicMock(
            iloc=MagicMock(__getitem__=lambda s, i: 130.0 if key == "Close" else 125.0)
        )
        mock_yf.Ticker.return_value.history.return_value = mock_hist

        evaluate_end_of_day()
        history = _load_picks_history()
        assert history[0]["eod_results"] is not None


# ===========================================================================
# Task 11.2 — Weight Adjustment (Req 15.1, 15.2, 15.3, 15.4, 15.5)
# ===========================================================================

def _build_evaluated_history(num_days: int, accuracy_pct: float = 0.7) -> list[dict]:
    """Build a synthetic pick history with EOD results for testing."""
    history = []
    for i in range(num_days):
        d = str(date.today() - timedelta(days=num_days - i))
        entry = {
            "date": d,
            "options_picks": [
                {
                    "ticker": "NVDA",
                    "direction": "CALL",
                    "composite_score": 8.0,
                    "agents": {
                        "fundamentals": {"score": 8.0, "direction": "CALL"},
                        "sentiment": {"score": 7.0, "direction": "CALL"},
                        "technical": {"score": 6.5, "direction": "CALL"},
                    },
                },
            ],
            "stock_picks": [
                {
                    "ticker": "AAPL",
                    "trade_action": "BUY",
                    "composite_score": 7.0,
                    "agents": {
                        "fundamentals": {"score": 7.0, "direction": "CALL"},
                        "news": {"score": 6.0, "direction": "CALL"},
                    },
                },
            ],
            "eod_results": {
                "date": d,
                "options": [
                    {"ticker": "NVDA", "direction": "CALL", "correct": i % int(1 / accuracy_pct) != 0 if accuracy_pct < 1 else True, "open": 125, "close": 130, "change_pct": 4.0, "est_pnl": 250},
                ],
                "stocks": [
                    {"ticker": "AAPL", "action": "BUY", "correct": True, "open": 170, "close": 175, "change_pct": 2.9},
                ],
                "total_pnl": 250,
            },
        }
        history.append(entry)
    return history


class TestWeightAdjustment:
    """Req 15.1-15.5: Weight adjustment engine."""

    def test_no_update_below_min_days(self, shared_mem):
        from weight_adjuster import update_weights
        # No history → should not update
        result = update_weights()
        assert result["weights_updated"] is False
        assert result["days_evaluated"] == 0

    def test_update_with_sufficient_history(self, shared_mem):
        from tracker import _save_picks_history
        from weight_adjuster import update_weights

        history = _build_evaluated_history(10)
        _save_picks_history(history)

        result = update_weights()
        assert result["weights_updated"] is True
        assert result["days_evaluated"] == 10

        # Weights should sum to ~1.0
        total = sum(result["weights"].values())
        assert abs(total - 1.0) < 0.01

    def test_accuracy_data_populated(self, shared_mem):
        from tracker import _save_picks_history
        from weight_adjuster import update_weights

        history = _build_evaluated_history(7)
        _save_picks_history(history)

        result = update_weights()
        acc = result["accuracy_data"]
        # Agents that contributed should have total > 0
        assert acc["fundamentals"]["total"] > 0
        assert "accuracy" in acc["fundamentals"]

    def test_weights_persisted_to_shared_memory(self, shared_mem):
        from tracker import _save_picks_history
        from weight_adjuster import update_weights
        import shared_memory_io

        history = _build_evaluated_history(6)
        _save_picks_history(history)

        update_weights()
        saved = shared_memory_io.load_weights()
        assert "weights" in saved
        assert saved["days_evaluated"] == 6

    def test_agents_with_no_data_get_default_accuracy(self, shared_mem):
        from weight_adjuster import compute_agent_accuracy

        # Empty history → all agents get 0.5 default
        acc = compute_agent_accuracy([])
        for agent_data in acc.values():
            assert agent_data["accuracy"] == 0.5


# ===========================================================================
# Task 11.3 — Horizon Progression (Req 18.1-18.5)
# ===========================================================================

class TestHorizonManager:
    """Req 18.1-18.5: Trading horizon state machine."""

    def test_default_mode_is_day_trade(self, shared_mem):
        from horizon_manager import get_current_mode
        assert get_current_mode() == "day_trade"

    def test_no_transition_below_threshold(self, shared_mem):
        from horizon_manager import check_transition
        result = check_transition(0.50)
        assert result["current_mode"] == "day_trade"
        assert result["transition"] is None

    def test_upgrade_to_swing_trade(self, shared_mem):
        """Req 18.2: accuracy >65% for 30 consecutive days → swing_trade."""
        import shared_memory_io
        from horizon_manager import check_transition

        # Pre-populate 29 days of >65% accuracy
        state = shared_memory_io.load_horizon_state()
        state["accuracy_history"] = [
            {"date": str(date.today() - timedelta(days=30 - i)), "accuracy": 0.70}
            for i in range(29)
        ]
        shared_memory_io.save_horizon_state(state)

        # 30th day should trigger upgrade
        result = check_transition(0.70)
        assert result["current_mode"] == "swing_trade"
        assert result["transition"] is not None
        assert "swing_trade" in result["transition"]
        assert result["notification"] is not None

    def test_upgrade_to_long_term(self, shared_mem):
        """Req 18.3: accuracy >75% for 90 consecutive days → long_term."""
        import shared_memory_io
        from horizon_manager import check_transition

        state = shared_memory_io.load_horizon_state()
        state["current_mode"] = "swing_trade"
        state["accuracy_history"] = [
            {"date": str(date.today() - timedelta(days=90 - i)), "accuracy": 0.80}
            for i in range(89)
        ]
        shared_memory_io.save_horizon_state(state)

        result = check_transition(0.80)
        assert result["current_mode"] == "long_term"

    def test_revert_on_consecutive_below_threshold(self, shared_mem):
        """Req 18.5: 10 consecutive days below threshold → revert."""
        import shared_memory_io
        from horizon_manager import check_transition

        state = shared_memory_io.load_horizon_state()
        state["current_mode"] = "swing_trade"
        state["accuracy_history"] = [
            {"date": str(date.today() - timedelta(days=10 - i)), "accuracy": 0.50}
            for i in range(9)
        ]
        shared_memory_io.save_horizon_state(state)

        # 10th day below threshold
        result = check_transition(0.50)
        assert result["current_mode"] == "day_trade"
        assert "REVERTED" in result["notification"]

    def test_no_revert_from_day_trade(self, shared_mem):
        """day_trade is the lowest mode — can't revert further."""
        from horizon_manager import check_transition
        result = check_transition(0.30)
        assert result["current_mode"] == "day_trade"

    def test_state_persisted_after_check(self, shared_mem):
        import shared_memory_io
        from horizon_manager import check_transition

        check_transition(0.60)
        state = shared_memory_io.load_horizon_state()
        assert len(state["accuracy_history"]) == 1
        assert state["accuracy_history"][0]["accuracy"] == 0.60

    def test_mode_config_returns_correct_expiry(self, shared_mem):
        from horizon_manager import get_mode_config
        cfg = get_mode_config("day_trade")
        assert cfg["expiry_range"] == (1, 7)

        cfg = get_mode_config("swing_trade")
        assert cfg["expiry_range"] == (7, 30)


# ===========================================================================
# Task 11.4 — EOD Recap Lambda (Req 13.3, 19.4)
# ===========================================================================

class TestEodRecap:
    """Req 13.3, 19.4: EOD recap Lambda logic."""

    def test_compute_accuracy_from_results(self, shared_mem):
        from lambda_handlers.eod_recap import _compute_accuracy_from_results

        eod = {
            "options": [
                {"ticker": "NVDA", "correct": True},
                {"ticker": "AAPL", "correct": False},
            ],
            "stocks": [
                {"ticker": "MSFT", "correct": True},
                {"ticker": "TSLA", "correct": True},
            ],
        }
        acc = _compute_accuracy_from_results(eod)
        assert acc["options_accuracy"] == 50.0
        assert acc["stock_accuracy"] == 100.0
        assert acc["overall_accuracy"] == 75.0

    def test_compute_accuracy_empty_results(self, shared_mem):
        from lambda_handlers.eod_recap import _compute_accuracy_from_results

        acc = _compute_accuracy_from_results({"options": [], "stocks": []})
        assert acc["overall_accuracy"] == 0.0

    @patch("lambda_handlers.eod_recap._send_telegram_message")
    @patch("lambda_handlers.eod_recap.AlpacaClient")
    @patch("lambda_handlers.eod_recap.evaluate_end_of_day")
    @patch("lambda_handlers.eod_recap.update_weights")
    @patch("lambda_handlers.eod_recap.check_transition")
    def test_run_eod_recap_pipeline(
        self, mock_horizon, mock_weights, mock_eval, mock_alpaca_cls, mock_tg, shared_mem
    ):
        from lambda_handlers.eod_recap import run_eod_recap

        mock_eval.return_value = {
            "date": str(date.today()),
            "options": [{"ticker": "NVDA", "correct": True, "est_pnl": 100}],
            "stocks": [{"ticker": "AAPL", "correct": True}],
            "total_pnl": 100,
        }
        mock_client = MagicMock()
        mock_client.get_account.return_value = {
            "daily_pnl": 150.0,
            "equity": 10150.0,
            "cash": 5000.0,
            "buying_power": 10000.0,
        }
        mock_alpaca_cls.return_value = mock_client

        mock_weights.return_value = {
            "weights_updated": True,
            "weights": {"fundamentals": 0.2},
            "previous_weights": {"fundamentals": 0.18},
            "accuracy_data": {},
            "days_evaluated": 10,
        }
        mock_horizon.return_value = {
            "current_mode": "day_trade",
            "transition": None,
            "notification": None,
        }

        result = run_eod_recap()

        assert result["accuracy"]["overall_accuracy"] == 100.0
        assert result["broker_pnl"]["daily_pnl"] == 150.0
        assert mock_tg.called  # Telegram message was sent

    @patch("lambda_handlers.eod_recap.run_eod_recap")
    def test_handler_returns_200_on_success(self, mock_run, shared_mem):
        from lambda_handlers.eod_recap import handler

        mock_run.return_value = {
            "accuracy": {"overall_accuracy": 75.0},
            "horizon": {"current_mode": "day_trade"},
        }
        resp = handler({}, None)
        assert resp["statusCode"] == 200

    @patch("lambda_handlers.eod_recap._send_telegram_message")
    @patch("lambda_handlers.eod_recap.run_eod_recap")
    def test_handler_returns_500_on_failure(self, mock_run, mock_tg, shared_mem):
        from lambda_handlers.eod_recap import handler

        mock_run.side_effect = RuntimeError("boom")
        resp = handler({}, None)
        assert resp["statusCode"] == 500
        assert mock_tg.called  # Failure notification sent

    @patch("lambda_handlers.eod_recap._send_telegram_message")
    @patch("lambda_handlers.eod_recap.AlpacaClient")
    @patch("lambda_handlers.eod_recap.evaluate_end_of_day")
    @patch("lambda_handlers.eod_recap.update_weights")
    @patch("lambda_handlers.eod_recap.check_transition")
    def test_horizon_notification_sent(
        self, mock_horizon, mock_weights, mock_eval, mock_alpaca_cls, mock_tg, shared_mem
    ):
        """When horizon transitions, a notification should be sent via Telegram."""
        from lambda_handlers.eod_recap import run_eod_recap

        mock_eval.return_value = {
            "options": [{"ticker": "NVDA", "correct": True}],
            "stocks": [],
            "total_pnl": 0,
        }
        mock_alpaca_cls.return_value.get_account.return_value = {
            "daily_pnl": 0, "equity": 10000, "cash": 5000, "buying_power": 10000,
        }
        mock_weights.return_value = {
            "weights_updated": False, "weights": {}, "previous_weights": {},
            "accuracy_data": {}, "days_evaluated": 3,
        }
        mock_horizon.return_value = {
            "current_mode": "swing_trade",
            "transition": "day_trade → swing_trade",
            "notification": "🎉 *Trading Mode UPGRADED*",
        }

        run_eod_recap()
        # Should have been called at least twice: recap message + notification
        assert mock_tg.call_count >= 2
