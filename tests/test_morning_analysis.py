"""
Tests for morning analysis Lambda handler, retry logic, and Telegram queue.

Requirements: 13.1, 13.2, 13.4, 13.5, 21.5
"""

import json
import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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
    for subdir in ("runs", "picks", "weights", "config"):
        (tmp_path / subdir).mkdir()

    # Default horizon state
    (tmp_path / "config" / "horizon_state.json").write_text(json.dumps({
        "current_mode": "day_trade",
        "consecutive_days_at_threshold": 0,
        "accuracy_history": [],
        "mode_transitions": [],
    }))

    # Default weights
    (tmp_path / "weights" / "learned_weights.json").write_text(json.dumps({
        "updated": "2025-01-01T00:00:00Z",
        "weights": {
            "fundamentals": 0.18, "sentiment": 0.15, "macro": 0.10,
            "news": 0.15, "technical": 0.15, "premarket": 0.12, "congress": 0.15,
        },
        "accuracy_data": {},
        "days_evaluated": 0,
    }))

    # Default watchlist
    (tmp_path / "config" / "watchlist.json").write_text(json.dumps({
        "all_tickers": ["AAPL", "NVDA", "MSFT"],
        "sectors": {"big_tech": ["AAPL", "NVDA", "MSFT"]},
    }))

    with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
        yield tmp_path


@pytest.fixture(autouse=True)
def _clear_telegram_queue():
    """Clear the Telegram message queue between tests."""
    from lambda_handlers import morning_analysis
    morning_analysis._telegram_message_queue.clear()
    yield
    morning_analysis._telegram_message_queue.clear()


def _mock_agent_results():
    """Build mock agent results for score combination."""
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
                {"ticker": "MSFT", "score": 4.0, "direction": "PUT"},
            ],
        }
    return results


# ===========================================================================
# Task 13.1 — Morning Analysis Pipeline (Req 13.1, 13.2, 13.4)
# ===========================================================================

class TestMorningAnalysisPipeline:
    """Req 13.1, 13.2, 13.4: Morning analysis Lambda handler."""

    @patch("lambda_handlers.morning_analysis._send_telegram_message")
    @patch("lambda_handlers.morning_analysis.enrich_options_picks", side_effect=lambda x: x)
    @patch("lambda_handlers.morning_analysis.poll_completion")
    @patch("lambda_handlers.morning_analysis.launch_fleet")
    def test_run_morning_analysis_full_pipeline(
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

        assert "run_id" in result
        assert len(result["options_picks"]) > 0
        assert len(result["stock_picks"]) > 0
        assert result["timed_out"] == []
        assert result["horizon"] == "day_trade"
        assert mock_tg.called

    @patch("lambda_handlers.morning_analysis._send_telegram_message")
    @patch("lambda_handlers.morning_analysis.enrich_options_picks", side_effect=lambda x: x)
    @patch("lambda_handlers.morning_analysis.poll_completion")
    @patch("lambda_handlers.morning_analysis.launch_fleet")
    def test_pipeline_handles_timed_out_agents(
        self, mock_launch, mock_poll, mock_enrich, mock_tg, shared_mem
    ):
        from lambda_handlers.morning_analysis import run_morning_analysis

        # Only 5 agents complete, 2 timed out
        partial_results = _mock_agent_results()
        del partial_results["macro"]
        del partial_results["congress"]

        mock_launch.return_value = {a: "complete" for a in partial_results}
        mock_poll.return_value = {
            "results": partial_results,
            "timed_out": ["macro", "congress"],
            "all_complete": False,
        }

        result = run_morning_analysis()

        assert result["timed_out"] == ["macro", "congress"]
        # Should still produce picks from available agents
        assert len(result["combined"]) > 0

    @patch("lambda_handlers.morning_analysis._send_telegram_message")
    @patch("lambda_handlers.morning_analysis.enrich_options_picks", side_effect=lambda x: x)
    @patch("lambda_handlers.morning_analysis.poll_completion")
    @patch("lambda_handlers.morning_analysis.launch_fleet")
    def test_picks_logged_via_tracker(
        self, mock_launch, mock_poll, mock_enrich, mock_tg, shared_mem
    ):
        from lambda_handlers.morning_analysis import run_morning_analysis

        mock_launch.return_value = {}
        mock_poll.return_value = {
            "results": _mock_agent_results(),
            "timed_out": [],
            "all_complete": True,
        }

        run_morning_analysis()

        # Verify picks were logged to shared memory
        picks_file = shared_mem / "picks" / "picks_history.json"
        assert picks_file.exists()
        history = json.loads(picks_file.read_text())
        assert len(history) == 1
        assert history[0]["date"] == str(date.today())

    @patch("lambda_handlers.morning_analysis._send_telegram_message", return_value=True)
    @patch("lambda_handlers.morning_analysis.enrich_options_picks", side_effect=lambda x: x)
    @patch("lambda_handlers.morning_analysis.poll_completion")
    @patch("lambda_handlers.morning_analysis.launch_fleet")
    def test_handler_returns_200_on_success(
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


# ===========================================================================
# Task 13.2 — Retry Logic (Req 13.5)
# ===========================================================================

class TestLambdaRetryLogic:
    """Req 13.5: Retry-once-after-60s on Lambda failure."""

    @patch("lambda_handlers.morning_analysis._flush_telegram_queue")
    @patch("lambda_handlers.morning_analysis._send_telegram_message")
    @patch("lambda_handlers.morning_analysis.run_morning_analysis")
    @patch("lambda_handlers.morning_analysis.time.sleep")
    def test_retry_once_on_failure(
        self, mock_sleep, mock_run, mock_tg, mock_flush, shared_mem
    ):
        from lambda_handlers.morning_analysis import handler

        # First call fails, second succeeds
        mock_run.side_effect = [
            RuntimeError("transient error"),
            {"run_id": "r1", "options_picks": [], "stock_picks": [],
             "combined": [], "timed_out": [], "horizon": "day_trade"},
        ]

        resp = handler({}, None)

        assert resp["statusCode"] == 200
        mock_sleep.assert_called_once_with(60)
        assert mock_run.call_count == 2

    @patch("lambda_handlers.morning_analysis._flush_telegram_queue")
    @patch("lambda_handlers.morning_analysis._send_telegram_message")
    @patch("lambda_handlers.morning_analysis.run_morning_analysis")
    @patch("lambda_handlers.morning_analysis.time.sleep")
    def test_failure_notification_on_final_failure(
        self, mock_sleep, mock_run, mock_tg, mock_flush, shared_mem
    ):
        from lambda_handlers.morning_analysis import handler

        mock_run.side_effect = RuntimeError("persistent error")

        resp = handler({}, None)

        assert resp["statusCode"] == 500
        assert resp["body"]["attempts"] == 2
        # Should have sent failure notification
        assert mock_tg.called
        failure_msg = mock_tg.call_args[0][0]
        assert "Failed" in failure_msg

    @patch("lambda_handlers.morning_analysis._flush_telegram_queue")
    @patch("lambda_handlers.morning_analysis._send_telegram_message")
    @patch("lambda_handlers.morning_analysis.run_morning_analysis")
    @patch("lambda_handlers.morning_analysis.time.sleep")
    def test_no_retry_on_second_attempt(
        self, mock_sleep, mock_run, mock_tg, mock_flush, shared_mem
    ):
        from lambda_handlers.morning_analysis import handler

        mock_run.side_effect = RuntimeError("still broken")

        # Simulate already being on retry attempt
        resp = handler({"_retry_attempt": 1}, None)

        assert resp["statusCode"] == 500
        # Should NOT have retried (already at max)
        mock_sleep.assert_not_called()


# ===========================================================================
# Task 13.2 — Telegram Queue Retry (Req 21.5)
# ===========================================================================

class TestTelegramMessageQueue:
    """Req 21.5: Queue unsent messages and retry."""

    def test_failed_send_queues_message(self, shared_mem):
        from lambda_handlers.morning_analysis import (
            _send_telegram_message, _telegram_message_queue,
        )

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }):
            with patch("lambda_handlers.morning_analysis.requests.post") as mock_post:
                mock_post.side_effect = ConnectionError("network down")
                result = _send_telegram_message("test message")

        assert result is False
        assert len(_telegram_message_queue) == 1
        assert _telegram_message_queue[0] == "test message"

    def test_failed_http_status_queues_message(self, shared_mem):
        from lambda_handlers.morning_analysis import (
            _send_telegram_message, _telegram_message_queue,
        )

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }):
            with patch("lambda_handlers.morning_analysis.requests.post") as mock_post:
                mock_resp = MagicMock()
                mock_resp.ok = False
                mock_resp.status_code = 429
                mock_resp.text = "Too Many Requests"
                mock_post.return_value = mock_resp
                _send_telegram_message("rate limited msg")

        assert len(_telegram_message_queue) == 1

    def test_flush_queue_retries_and_sends(self, shared_mem):
        from lambda_handlers.morning_analysis import (
            _telegram_message_queue, _flush_telegram_queue,
        )

        _telegram_message_queue.extend(["msg1", "msg2"])

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }):
            with patch("lambda_handlers.morning_analysis.requests.post") as mock_post:
                mock_resp = MagicMock()
                mock_resp.ok = True
                mock_post.return_value = mock_resp

                sent = _flush_telegram_queue()

        assert sent == 2
        assert len(_telegram_message_queue) == 0

    def test_flush_queue_partial_success(self, shared_mem):
        from lambda_handlers.morning_analysis import (
            _telegram_message_queue, _flush_telegram_queue,
        )

        _telegram_message_queue.extend(["msg1", "msg2"])

        def _side_effect(url, **kwargs):
            resp = MagicMock()
            text = kwargs.get("json", {}).get("text", "")
            # msg1 always succeeds, msg2 always fails
            resp.ok = (text == "msg1")
            return resp

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }):
            with patch("lambda_handlers.morning_analysis.requests.post", side_effect=_side_effect):
                with patch("lambda_handlers.morning_analysis.time.sleep"):
                    sent = _flush_telegram_queue()

        assert sent >= 1
        # msg2 should remain in queue after all retries
        assert "msg2" in _telegram_message_queue

    def test_successful_send_does_not_queue(self, shared_mem):
        from lambda_handlers.morning_analysis import (
            _send_telegram_message, _telegram_message_queue,
        )

        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "test-token",
            "TELEGRAM_CHAT_ID": "12345",
        }):
            with patch("lambda_handlers.morning_analysis.requests.post") as mock_post:
                mock_resp = MagicMock()
                mock_resp.ok = True
                mock_post.return_value = mock_resp
                result = _send_telegram_message("success msg")

        assert result is True
        assert len(_telegram_message_queue) == 0

    def test_no_credentials_skips_send(self, shared_mem):
        from lambda_handlers.morning_analysis import _send_telegram_message

        with patch.dict(os.environ, {}, clear=True):
            result = _send_telegram_message("no creds")

        assert result is False


# ===========================================================================
# EOD Recap Retry Logic (Req 13.5)
# ===========================================================================

class TestEodRecapRetryLogic:
    """Req 13.5: EOD recap retry-once-after-60s."""

    @patch("lambda_handlers.eod_recap._flush_telegram_queue")
    @patch("lambda_handlers.eod_recap._send_telegram_message")
    @patch("lambda_handlers.eod_recap.run_eod_recap")
    @patch("lambda_handlers.eod_recap.time.sleep")
    def test_eod_retry_once_on_failure(
        self, mock_sleep, mock_run, mock_tg, mock_flush, shared_mem
    ):
        from lambda_handlers.eod_recap import handler

        mock_run.side_effect = [
            RuntimeError("transient"),
            {
                "accuracy": {"overall_accuracy": 70.0},
                "horizon": {"current_mode": "day_trade"},
            },
        ]

        resp = handler({}, None)
        assert resp["statusCode"] == 200
        mock_sleep.assert_called_once_with(60)

    @patch("lambda_handlers.eod_recap._flush_telegram_queue")
    @patch("lambda_handlers.eod_recap._send_telegram_message")
    @patch("lambda_handlers.eod_recap.run_eod_recap")
    @patch("lambda_handlers.eod_recap.time.sleep")
    def test_eod_final_failure_sends_notification(
        self, mock_sleep, mock_run, mock_tg, mock_flush, shared_mem
    ):
        from lambda_handlers.eod_recap import handler

        mock_run.side_effect = RuntimeError("persistent")

        resp = handler({}, None)
        assert resp["statusCode"] == 500
        assert mock_tg.called
