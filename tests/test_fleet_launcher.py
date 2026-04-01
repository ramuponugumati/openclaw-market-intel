"""
Unit tests for the Fleet Launcher Skill.

Validates Requirements: 1.3, 1.4, 2.1, 2.3, 2.4, 2.5, 21.3
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.orchestrator.skills.fleet_launcher import (
    launch_fleet,
    poll_completion,
    SUB_AGENTS,
    _import_agent_module,
    _run_agent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_WATCHLIST = {
    "updated": "2025-01-01T00:00:00Z",
    "sectors": {"big_tech": ["AAPL", "MSFT"]},
    "etf_tickers": [],
    "all_tickers": ["AAPL", "MSFT"],
}

SAMPLE_AGENT_RESULT = [
    {"ticker": "AAPL", "score": 7.0, "direction": "CALL"},
    {"ticker": "MSFT", "score": 5.5, "direction": "HOLD"},
]


def _make_mock_agent_module():
    """Return a mock module with run() and write_to_shared_memory()."""
    mod = MagicMock()
    mod.run.return_value = SAMPLE_AGENT_RESULT
    mod.write_to_shared_memory.return_value = "/tmp/test_result.md"
    return mod


# ---------------------------------------------------------------------------
# Task 5.1 — launch_fleet tests
# ---------------------------------------------------------------------------

class TestLaunchFleet:
    """Tests for launch_fleet() — Req 1.3, 1.4, 2.1."""

    @patch("agents.orchestrator.skills.fleet_launcher._import_agent_module")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_launch_fleet_all_agents_complete(self, mock_sio, mock_import):
        """All 7 agents should be launched concurrently and return 'complete'."""
        mock_sio.load_watchlist.return_value = SAMPLE_WATCHLIST
        mock_sio.write_manifest.return_value = "/tmp/manifest.md"

        mock_mod = _make_mock_agent_module()
        mock_import.return_value = mock_mod

        result = launch_fleet("test_run_001")

        # All 7 agents should be in the result
        assert len(result) == 7
        for agent_id in SUB_AGENTS:
            assert agent_id in result
            assert result[agent_id] == "complete"

        # Manifest should have been written
        mock_sio.write_manifest.assert_called_once_with("test_run_001", "morning_analysis")

        # Each agent's run() should have been called with the watchlist
        assert mock_mod.run.call_count == 7
        assert mock_mod.write_to_shared_memory.call_count == 7

    @patch("agents.orchestrator.skills.fleet_launcher._import_agent_module")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_launch_fleet_writes_manifest_first(self, mock_sio, mock_import):
        """Manifest should be written before agents are launched."""
        mock_sio.load_watchlist.return_value = SAMPLE_WATCHLIST
        mock_sio.write_manifest.return_value = "/tmp/manifest.md"
        mock_import.return_value = _make_mock_agent_module()

        launch_fleet("run_manifest_test")

        mock_sio.write_manifest.assert_called_once_with("run_manifest_test", "morning_analysis")

    @patch("agents.orchestrator.skills.fleet_launcher._import_agent_module")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_launch_fleet_empty_watchlist_returns_errors(self, mock_sio, mock_import):
        """If watchlist is empty, all agents should return 'error'."""
        mock_sio.load_watchlist.return_value = {"all_tickers": []}
        mock_sio.write_manifest.return_value = "/tmp/manifest.md"

        result = launch_fleet("empty_wl_run")

        for agent_id in SUB_AGENTS:
            assert result[agent_id] == "error"

        # No agent modules should have been imported
        mock_import.assert_not_called()

    @patch("agents.orchestrator.skills.fleet_launcher._import_agent_module")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_launch_fleet_agent_failure_returns_error(self, mock_sio, mock_import):
        """If an agent raises an exception, its status should be 'error'."""
        mock_sio.load_watchlist.return_value = SAMPLE_WATCHLIST
        mock_sio.write_manifest.return_value = "/tmp/manifest.md"

        failing_mod = MagicMock()
        failing_mod.run.side_effect = RuntimeError("API down")

        mock_import.return_value = failing_mod

        result = launch_fleet("fail_run")

        # All agents should report error since they all use the same mock
        for agent_id in SUB_AGENTS:
            assert result[agent_id] == "error"

    @patch("agents.orchestrator.skills.fleet_launcher._import_agent_module")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_launch_fleet_updates_manifest_per_agent(self, mock_sio, mock_import):
        """Manifest status should be updated for each agent after completion."""
        mock_sio.load_watchlist.return_value = SAMPLE_WATCHLIST
        mock_sio.write_manifest.return_value = "/tmp/manifest.md"
        mock_import.return_value = _make_mock_agent_module()

        launch_fleet("manifest_update_run")

        # update_manifest_status should be called once per agent
        assert mock_sio.update_manifest_status.call_count == 7

    @patch("agents.orchestrator.skills.fleet_launcher._import_agent_module")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_launch_fleet_custom_run_type(self, mock_sio, mock_import):
        """Custom run_type should be passed to write_manifest."""
        mock_sio.load_watchlist.return_value = SAMPLE_WATCHLIST
        mock_sio.write_manifest.return_value = "/tmp/manifest.md"
        mock_import.return_value = _make_mock_agent_module()

        launch_fleet("adhoc_run", run_type="ad_hoc")

        mock_sio.write_manifest.assert_called_once_with("adhoc_run", "ad_hoc")


# ---------------------------------------------------------------------------
# Task 5.2 — poll_completion tests
# ---------------------------------------------------------------------------

class TestPollCompletion:
    """Tests for poll_completion() — Req 2.3, 2.4, 2.5, 21.3."""

    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_all_results_present_immediately(self, mock_sio):
        """If all 7 result files exist on first poll, return immediately."""
        parsed = {
            "agent_id": "test",
            "run_id": "run_001",
            "timestamp": "2026-01-15T05:31:00Z",
            "status": "complete",
            "tickers_analyzed": 2,
            "results": SAMPLE_AGENT_RESULT,
        }
        mock_sio.read_agent_result.return_value = parsed

        result = poll_completion("run_001", timeout_s=10, interval_s=1)

        assert result["all_complete"] is True
        assert result["timed_out"] == []
        assert len(result["results"]) == 7

    @patch("agents.orchestrator.skills.fleet_launcher.time")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_timeout_with_missing_agents(self, mock_sio, mock_time):
        """If some agents don't produce results, they should be timed out."""
        # Simulate monotonic clock: start at 0, then jump past deadline
        mock_time.monotonic.side_effect = [0, 0, 200, 200, 200, 200, 200, 200, 200, 200]

        # Only fundamentals and sentiment have results
        def _read_result(agent_id, run_id):
            if agent_id in ("fundamentals", "sentiment"):
                return {
                    "agent_id": agent_id,
                    "run_id": run_id,
                    "timestamp": "2026-01-15T05:31:00Z",
                    "status": "complete",
                    "tickers_analyzed": 2,
                    "results": SAMPLE_AGENT_RESULT,
                }
            return None

        mock_sio.read_agent_result.side_effect = _read_result

        result = poll_completion("run_timeout", timeout_s=120, interval_s=5)

        assert result["all_complete"] is False
        assert len(result["results"]) == 2
        assert "fundamentals" in result["results"]
        assert "sentiment" in result["results"]
        # 5 agents should be timed out
        assert len(result["timed_out"]) == 5
        for agent_id in result["timed_out"]:
            mock_sio.update_manifest_status.assert_any_call(
                "run_timeout", agent_id, "timed_out"
            )

    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_poll_updates_manifest_on_completion(self, mock_sio):
        """Each completed agent should have its manifest status updated."""
        parsed = {
            "agent_id": "test",
            "run_id": "run_002",
            "timestamp": "2026-01-15T05:31:00Z",
            "status": "complete",
            "tickers_analyzed": 2,
            "results": SAMPLE_AGENT_RESULT,
        }
        mock_sio.read_agent_result.return_value = parsed

        poll_completion("run_002", timeout_s=10, interval_s=1)

        # Should be called once per agent with 'complete'
        assert mock_sio.update_manifest_status.call_count == 7
        for agent_id in SUB_AGENTS:
            mock_sio.update_manifest_status.assert_any_call(
                "run_002", agent_id, "complete"
            )

    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_poll_returns_parsed_results(self, mock_sio):
        """Returned results should contain the parsed agent result dicts."""
        parsed = {
            "agent_id": "fundamentals",
            "run_id": "run_003",
            "timestamp": "2026-01-15T05:31:00Z",
            "status": "complete",
            "tickers_analyzed": 2,
            "results": SAMPLE_AGENT_RESULT,
        }
        mock_sio.read_agent_result.return_value = parsed

        result = poll_completion("run_003", timeout_s=10, interval_s=1)

        for agent_id in SUB_AGENTS:
            assert agent_id in result["results"]
            assert result["results"][agent_id]["status"] == "complete"
            assert result["results"][agent_id]["results"] == SAMPLE_AGENT_RESULT

    @patch("agents.orchestrator.skills.fleet_launcher.time")
    @patch("agents.orchestrator.skills.fleet_launcher.shared_memory_io")
    def test_poll_proceeds_with_partial_results_on_timeout(self, mock_sio, mock_time):
        """On timeout, should return available results and list timed-out agents."""
        # Clock: start=0, first check=0, then past deadline
        mock_time.monotonic.side_effect = [0, 0, 200, 200, 200, 200, 200, 200, 200]

        # Only macro has results
        def _read_result(agent_id, run_id):
            if agent_id == "macro":
                return {
                    "agent_id": "macro",
                    "run_id": run_id,
                    "status": "complete",
                    "tickers_analyzed": 2,
                    "results": SAMPLE_AGENT_RESULT,
                }
            return None

        mock_sio.read_agent_result.side_effect = _read_result

        result = poll_completion("run_partial", timeout_s=120, interval_s=5)

        assert result["all_complete"] is False
        assert "macro" in result["results"]
        assert len(result["timed_out"]) == 6
        assert "macro" not in result["timed_out"]
