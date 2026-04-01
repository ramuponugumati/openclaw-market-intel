"""
Unit tests for the Congressional Trades Analysis Skill.

Validates Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 21.1, 21.4
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.congress.skills.congress_analysis import (
    score_congress_signal,
    run,
    write_to_shared_memory,
    fetch_recent_congress_trades,
    _fetch_quiver_trades,
    _fetch_capitol_trades,
    PRIORITY_POLITICIANS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(politician: str = "John Doe", ticker: str = "AAPL",
                transaction: str = "Purchase", amount: str = "$50,001 - $100,000",
                date: str = "2026-01-10", party: str = "R",
                chamber: str = "House") -> dict:
    """Return a realistic trade dict."""
    return {
        "politician": politician,
        "ticker": ticker,
        "transaction": transaction,
        "amount": amount,
        "date": date,
        "party": party,
        "chamber": chamber,
    }


# ---------------------------------------------------------------------------
# Requirement 10.2 — Priority politician list
# ---------------------------------------------------------------------------

class TestPriorityPoliticianList:
    """Validates the priority politician list is maintained."""

    def test_priority_list_contains_known_traders(self):
        """Priority list should include key politicians."""
        assert "Nancy Pelosi" in PRIORITY_POLITICIANS
        assert "Tommy Tuberville" in PRIORITY_POLITICIANS
        assert "Marjorie Taylor Greene" in PRIORITY_POLITICIANS


# ---------------------------------------------------------------------------
# Requirement 10.3 — Priority buy adds +2.0 with label
# ---------------------------------------------------------------------------

class TestPriorityBuyScoring:
    """Validates priority politician buy scoring."""

    def test_priority_buy_adds_2_points(self):
        """A priority politician purchase should add 2.0 to base 5.0."""
        trades = [_make_trade(politician="Nancy Pelosi", ticker="NVDA",
                              transaction="Purchase")]
        result = score_congress_signal("NVDA", trades)
        assert result["score"] == 7.0
        assert result["direction"] == "CALL"
        assert result["congress_buys"] == 1
        assert "🏛️" in result["priority_signal"]
        assert "BOUGHT" in result["priority_signal"]

    def test_priority_sell_subtracts_2_points(self):
        """A priority politician sale should subtract 2.0 from base 5.0."""
        trades = [_make_trade(politician="Tommy Tuberville", ticker="INTC",
                              transaction="Sale")]
        result = score_congress_signal("INTC", trades)
        assert result["score"] == 3.0
        assert result["direction"] == "PUT"
        assert result["congress_sells"] == 1
        assert "SOLD" in result["priority_signal"]


# ---------------------------------------------------------------------------
# Requirement 10.4 — Non-priority buy adds +0.5
# ---------------------------------------------------------------------------

class TestNonPriorityScoring:
    """Validates non-priority politician scoring."""

    def test_non_priority_buy_adds_half_point(self):
        """A non-priority politician purchase should add 0.5."""
        trades = [_make_trade(politician="Unknown Rep", ticker="AAPL",
                              transaction="Purchase")]
        result = score_congress_signal("AAPL", trades)
        assert result["score"] == 5.5
        assert result["direction"] == "HOLD"
        assert result["congress_buys"] == 1
        assert result["priority_signal"] is None

    def test_non_priority_sell_subtracts_half_point(self):
        """A non-priority politician sale should subtract 0.5."""
        trades = [_make_trade(politician="Unknown Rep", ticker="AAPL",
                              transaction="Sale")]
        result = score_congress_signal("AAPL", trades)
        assert result["score"] == 4.5
        assert result["direction"] == "HOLD"
        assert result["congress_sells"] == 1


# ---------------------------------------------------------------------------
# Requirement 10.6 — Both APIs fail → neutral scores
# ---------------------------------------------------------------------------

class TestBothAPIFailure:
    """Validates neutral fallback when both data sources fail."""

    def test_no_trades_returns_neutral(self):
        """No trades for a ticker → score 5.0, HOLD."""
        result = score_congress_signal("AAPL", [])
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"
        assert result["congress_buys"] == 0
        assert result["congress_sells"] == 0

    def test_run_with_both_apis_failing_returns_neutral(self):
        """When both APIs fail, all tickers get neutral 5.0."""
        with patch(
            "agents.congress.skills.congress_analysis._fetch_quiver_trades",
            return_value=[],
        ), patch(
            "agents.congress.skills.congress_analysis._fetch_capitol_trades",
            return_value=[],
        ):
            results = run(["AAPL", "NVDA"])
        assert len(results) == 2
        for r in results:
            assert r["score"] == 5.0
            assert r["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

class TestScoreClamping:
    """Validates score stays within 0-10 range."""

    def test_score_clamped_at_10(self):
        """Multiple priority buys should not exceed 10."""
        trades = [
            _make_trade(politician="Nancy Pelosi", ticker="NVDA", transaction="Purchase"),
            _make_trade(politician="Tommy Tuberville", ticker="NVDA", transaction="Purchase"),
            _make_trade(politician="Jim Jordan", ticker="NVDA", transaction="Purchase"),
        ]
        result = score_congress_signal("NVDA", trades)
        assert result["score"] <= 10.0

    def test_score_clamped_at_0(self):
        """Multiple priority sells should not go below 0."""
        trades = [
            _make_trade(politician="Nancy Pelosi", ticker="INTC", transaction="Sale"),
            _make_trade(politician="Tommy Tuberville", ticker="INTC", transaction="Sale"),
            _make_trade(politician="Jim Jordan", ticker="INTC", transaction="Sale"),
        ]
        result = score_congress_signal("INTC", trades)
        assert result["score"] >= 0.0


# ---------------------------------------------------------------------------
# Requirement 10.5 — Extra tickers outside watchlist
# ---------------------------------------------------------------------------

class TestExtraTickersOutsideWatchlist:
    """Validates outside-watchlist signal detection."""

    def test_extra_tickers_flagged(self):
        """Tickers traded by congress but not in watchlist should be included."""
        trades = [
            _make_trade(politician="Nancy Pelosi", ticker="RBLX", transaction="Purchase"),
            _make_trade(politician="Unknown Rep", ticker="AAPL", transaction="Purchase"),
        ]
        with patch(
            "agents.congress.skills.congress_analysis.fetch_recent_congress_trades",
            return_value=trades,
        ):
            results = run(["AAPL"])

        # AAPL is in watchlist, RBLX is extra
        rblx_results = [r for r in results if r["ticker"] == "RBLX"]
        assert len(rblx_results) == 1
        assert rblx_results[0].get("outside_watchlist") is True

    def test_max_5_extra_tickers(self):
        """At most 5 extra tickers should be included."""
        extra_trades = [
            _make_trade(politician="Nancy Pelosi", ticker=f"EX{i}", transaction="Purchase")
            for i in range(10)
        ]
        with patch(
            "agents.congress.skills.congress_analysis.fetch_recent_congress_trades",
            return_value=extra_trades,
        ):
            results = run(["AAPL"])

        outside = [r for r in results if r.get("outside_watchlist")]
        assert len(outside) <= 5


# ---------------------------------------------------------------------------
# Requirement 10.1 — Quiver primary, Capitol Trades fallback
# ---------------------------------------------------------------------------

class TestDataSourceFallback:
    """Validates primary/fallback data source logic."""

    def test_quiver_used_as_primary(self):
        """When Quiver returns data, Capitol Trades should not be called."""
        quiver_trades = [_make_trade(ticker="AAPL")]
        with patch(
            "agents.congress.skills.congress_analysis._fetch_quiver_trades",
            return_value=quiver_trades,
        ) as mock_quiver, patch(
            "agents.congress.skills.congress_analysis._fetch_capitol_trades",
        ) as mock_capitol:
            result = fetch_recent_congress_trades(14, "test-key")
            mock_quiver.assert_called_once()
            mock_capitol.assert_not_called()
            assert len(result) == 1

    def test_capitol_trades_used_as_fallback(self):
        """When Quiver returns empty, Capitol Trades should be called."""
        capitol_trades = [_make_trade(ticker="MSFT")]
        with patch(
            "agents.congress.skills.congress_analysis._fetch_quiver_trades",
            return_value=[],
        ), patch(
            "agents.congress.skills.congress_analysis._fetch_capitol_trades",
            return_value=capitol_trades,
        ) as mock_capitol:
            result = fetch_recent_congress_trades(14, "test-key")
            mock_capitol.assert_called_once()
            assert len(result) == 1


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_accepts_config_with_api_key(self):
        """run() should pass quiver_api_key from config."""
        with patch(
            "agents.congress.skills.congress_analysis.fetch_recent_congress_trades",
            return_value=[],
        ) as mock_fetch:
            results = run(["AAPL"], config={"quiver_api_key": "my-key"})
            mock_fetch.assert_called_once_with(days_back=14, api_key="my-key")
            assert len(results) == 1

    def test_sorted_by_signal_strength(self):
        """Results should be sorted by distance from neutral 5.0."""
        trades = [
            _make_trade(politician="Nancy Pelosi", ticker="NVDA", transaction="Purchase"),
            _make_trade(politician="Unknown Rep", ticker="AAPL", transaction="Purchase"),
        ]
        with patch(
            "agents.congress.skills.congress_analysis.fetch_recent_congress_trades",
            return_value=trades,
        ):
            results = run(["AAPL", "NVDA", "MSFT"])

        # NVDA (+2.0 priority) should be first, AAPL (+0.5) second, MSFT (5.0) last
        scores = [r["score"] for r in results]
        distances = [abs(s - 5.0) for s in scores]
        assert distances == sorted(distances, reverse=True)


# ---------------------------------------------------------------------------
# write_to_shared_memory — delegates to shared_memory_io
# ---------------------------------------------------------------------------

class TestWriteToSharedMemory:
    """Validates shared memory integration."""

    def test_writes_and_reads_back(self, tmp_path):
        """Round-trip: write results, read them back via shared_memory_io."""
        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

            sample = [
                {"ticker": "NVDA", "score": 7.0, "direction": "CALL",
                 "congress_buys": 1, "congress_sells": 0,
                 "priority_signal": "🏛️ Nancy Pelosi BOUGHT"},
                {"ticker": "AAPL", "score": 5.0, "direction": "HOLD",
                 "congress_buys": 0, "congress_sells": 0,
                 "priority_signal": None},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("congress", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "congress"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "NVDA"
