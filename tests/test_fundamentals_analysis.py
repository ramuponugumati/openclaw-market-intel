"""
Unit tests for the Fundamentals Analysis Skill.

Validates Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 21.1, 21.4
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.fundamentals.skills.fundamentals_analysis import (
    analyze_ticker,
    run,
    write_to_shared_memory,
    _fetch_ticker_info,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_info(**overrides) -> dict:
    """Return a realistic yfinance .info dict with sensible defaults."""
    base = {
        "trailingPE": 25.0,
        "forwardPE": 20.0,
        "revenueGrowth": 0.10,
        "earningsGrowth": 0.08,
        "recommendationKey": "hold",
        "targetMeanPrice": 150.0,
        "currentPrice": 140.0,
        "regularMarketPrice": 140.0,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Requirement 3.2 — Score range and direction mapping
# ---------------------------------------------------------------------------

class TestScoreAndDirection:
    """Validates score 0-10 range and CALL/PUT/HOLD direction thresholds."""

    def test_neutral_baseline_returns_hold(self):
        """A ticker with average metrics should score ~5 and HOLD."""
        info = _make_info(earningsGrowth=0.03, revenueGrowth=0.05,
                          recommendationKey="hold", targetMeanPrice=145.0)
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("TEST")
        assert 4 < result["score"] < 6
        assert result["direction"] == "HOLD"

    def test_strong_fundamentals_return_call(self):
        """High earnings growth + buy rec + upside → score ≥ 6 → CALL."""
        info = _make_info(
            earningsGrowth=0.30,
            revenueGrowth=0.20,
            recommendationKey="strongBuy",
            targetMeanPrice=200.0,
            currentPrice=150.0,
        )
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("BULL")
        assert result["score"] >= 6
        assert result["direction"] == "CALL"

    def test_weak_fundamentals_return_put(self):
        """Negative earnings + sell rec + downside → score ≤ 4 → PUT."""
        info = _make_info(
            earningsGrowth=-0.15,
            revenueGrowth=-0.10,
            recommendationKey="strongSell",
            targetMeanPrice=100.0,
            currentPrice=150.0,
        )
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("BEAR")
        assert result["score"] <= 4
        assert result["direction"] == "PUT"

    def test_score_clamped_to_0_10(self):
        """Score must never exceed 8.0 (capped) or go below 0."""
        # Extremely bullish — all bonuses stack
        info = _make_info(
            earningsGrowth=0.50,
            revenueGrowth=0.30,
            forwardPE=15.0,
            trailingPE=30.0,
            recommendationKey="strongBuy",
            targetMeanPrice=300.0,
            currentPrice=100.0,
        )
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("MAX")
        assert 0 <= result["score"] <= 8.0

        # Extremely bearish — all penalties stack
        info_bear = _make_info(
            earningsGrowth=-0.50,
            revenueGrowth=-0.30,
            recommendationKey="strongSell",
            targetMeanPrice=50.0,
            currentPrice=150.0,
        )
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info_bear,
        ):
            result_bear = analyze_ticker("MIN")
        assert 0 <= result_bear["score"] <= 8.0


# ---------------------------------------------------------------------------
# Requirement 3.3 — Earnings growth > 20% adds 2.0
# ---------------------------------------------------------------------------

class TestEarningsGrowthScoring:
    """Validates earnings growth scoring thresholds."""

    def test_earnings_above_20pct_adds_2(self):
        """Earnings growth > 20% should add 2.0 to base."""
        info = _make_info(earningsGrowth=0.25, revenueGrowth=0.0,
                          recommendationKey="hold",
                          targetMeanPrice=140.0, currentPrice=140.0,
                          forwardPE=25.0, trailingPE=25.0)  # neutralize fwd PE bonus
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("EG25")
        # base 5.0 + 2.0 earnings = 7.0
        assert result["score"] == 7.0

    def test_earnings_exactly_20pct_does_not_add_2(self):
        """Earnings growth == 20% should NOT trigger the >20% bonus."""
        info = _make_info(earningsGrowth=0.20, revenueGrowth=0.0,
                          recommendationKey="hold",
                          targetMeanPrice=140.0, currentPrice=140.0,
                          forwardPE=25.0, trailingPE=25.0)  # neutralize fwd PE bonus
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("EG20")
        # 0.20 > 0.05 so gets +1.0 (the elif branch), not +2.0
        assert result["score"] == 6.0


# ---------------------------------------------------------------------------
# Requirement 3.4 — Analyst upside > 15% adds 1.0
# ---------------------------------------------------------------------------

class TestAnalystUpsideScoring:
    """Validates analyst target upside scoring."""

    def test_upside_above_15pct_adds_1(self):
        """Analyst target > 15% above current price adds 1.0."""
        # target=170, price=140 → upside = 21.4%
        info = _make_info(earningsGrowth=0.0, revenueGrowth=0.0,
                          recommendationKey="hold",
                          targetMeanPrice=170.0, currentPrice=140.0,
                          forwardPE=25.0, trailingPE=25.0)  # neutralize fwd PE bonus
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("UP21")
        # base 5.0 + 1.0 upside = 6.0
        assert result["score"] == 6.0

    def test_upside_exactly_15pct_does_not_add(self):
        """Upside == 15% should NOT trigger the >15% bonus."""
        # target=161, price=140 → upside = 15.0%
        info = _make_info(earningsGrowth=0.0, revenueGrowth=0.0,
                          recommendationKey="hold",
                          targetMeanPrice=161.0, currentPrice=140.0,
                          forwardPE=25.0, trailingPE=25.0)  # neutralize fwd PE bonus
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("UP15")
        assert result["score"] == 5.0


# ---------------------------------------------------------------------------
# Requirement 3.5 — yfinance failure returns neutral 5.0
# ---------------------------------------------------------------------------

class TestYfinanceFailure:
    """Validates graceful degradation on yfinance errors."""

    def test_empty_info_returns_neutral(self):
        """Empty yfinance response → score 5.0, HOLD."""
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value={},
        ):
            result = analyze_ticker("FAIL")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"
        assert "error" in result

    def test_exception_returns_neutral(self):
        """Exception during analysis → score 5.0, HOLD."""
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            side_effect=RuntimeError("network error"),
        ):
            result = analyze_ticker("ERR")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"
        assert "error" in result


# ---------------------------------------------------------------------------
# Requirement 3.1 — Return schema
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_successful_result_has_all_fields(self):
        info = _make_info()
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=info,
        ):
            result = analyze_ticker("AAPL")
        required_keys = {
            "ticker", "score", "direction", "pe", "fwd_pe",
            "revenue_growth", "earnings_growth", "analyst_rec",
            "upside_to_target", "price",
        }
        assert required_keys.issubset(result.keys())

    def test_error_result_has_ticker_score_direction(self):
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value={},
        ):
            result = analyze_ticker("BAD")
        assert result["ticker"] == "BAD"
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, returns sorted list
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_returns_sorted_by_score_descending(self):
        infos = {
            "LOW": _make_info(earningsGrowth=-0.15, revenueGrowth=-0.10,
                              recommendationKey="sell",
                              targetMeanPrice=100.0, currentPrice=150.0),
            "HIGH": _make_info(earningsGrowth=0.30, revenueGrowth=0.20,
                               recommendationKey="buy",
                               targetMeanPrice=200.0, currentPrice=150.0),
        }

        def mock_fetch(ticker):
            return infos.get(ticker, {})

        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            side_effect=mock_fetch,
        ):
            results = run(["LOW", "HIGH"])

        assert len(results) == 2
        assert results[0]["ticker"] == "HIGH"
        assert results[0]["score"] >= results[1]["score"]

    def test_accepts_config_parameter(self):
        """run() should accept an optional config dict without error."""
        with patch(
            "agents.fundamentals.skills.fundamentals_analysis._fetch_ticker_info",
            return_value=_make_info(),
        ):
            results = run(["AAPL"], config={"scoring": {"base_score": 5.0}})
        assert len(results) == 1


# ---------------------------------------------------------------------------
# write_to_shared_memory — delegates to shared_memory_io
# ---------------------------------------------------------------------------

class TestWriteToSharedMemory:
    """Validates shared memory integration."""

    def test_writes_and_reads_back(self, tmp_path):
        """Round-trip: write results, read them back via shared_memory_io."""
        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            # Ensure the runs dir exists
            (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

            sample = [
                {"ticker": "AAPL", "score": 7.5, "direction": "CALL", "pe": 28.0},
                {"ticker": "INTC", "score": 3.2, "direction": "PUT", "pe": 12.0},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            # Read back
            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("fundamentals", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "fundamentals"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "AAPL"
