"""
Unit tests for the Pre-Market Analysis Skill.

Validates Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 21.1, 21.4
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.premarket.skills.premarket_analysis import (
    assess_market_bias,
    detect_market_regime,
    get_ticker_trend,
    get_futures_snapshot,
    get_global_markets,
    get_premarket_movers,
    score_ticker,
    run,
    write_to_shared_memory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_futures_history(prev_close: float, current: float) -> pd.DataFrame:
    """Build a 2-day DataFrame mimicking yfinance futures output."""
    dates = pd.date_range(end=pd.Timestamp.now(), periods=2, freq="B")
    return pd.DataFrame({"Close": [prev_close, current]}, index=dates)


def _make_ticker_info(
    pre_market_price: float = 0,
    previous_close: float = 100.0,
) -> dict:
    """Build a mock yfinance .info dict."""
    info = {"previousClose": previous_close}
    if pre_market_price:
        info["preMarketPrice"] = pre_market_price
    return info


# ---------------------------------------------------------------------------
# Req 9.4 — Bullish bias when avg S&P + Nasdaq futures > +0.5%
# ---------------------------------------------------------------------------

class TestMarketBiasBullish:
    """Validates bullish bias detection."""

    def test_bullish_when_avg_futures_above_half_pct(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 0.8, "signal": "bullish"},
            {"symbol": "NQ=F", "name": "Nasdaq Futures", "price": 18000, "change_pct": 0.6, "signal": "bullish"},
        ]
        assert assess_market_bias(futures) == "bullish"

    def test_neutral_when_avg_futures_between_neg_half_and_pos_half(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 0.2, "signal": "flat"},
            {"symbol": "NQ=F", "name": "Nasdaq Futures", "price": 18000, "change_pct": 0.3, "signal": "flat"},
        ]
        assert assess_market_bias(futures) == "neutral"

    def test_bearish_when_avg_futures_below_neg_half_pct(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": -0.8, "signal": "bearish"},
            {"symbol": "NQ=F", "name": "Nasdaq Futures", "price": 18000, "change_pct": -0.6, "signal": "bearish"},
        ]
        assert assess_market_bias(futures) == "bearish"


# ---------------------------------------------------------------------------
# Req 9.5 — VIX > 25 overrides to bearish
# ---------------------------------------------------------------------------

class TestVIXOverride:
    """Validates VIX override logic."""

    def test_vix_above_25_overrides_bullish_to_bearish(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 1.0, "signal": "bullish"},
            {"symbol": "NQ=F", "name": "Nasdaq Futures", "price": 18000, "change_pct": 1.0, "signal": "bullish"},
            {"symbol": "^VIX", "name": "VIX", "price": 30.0, "change_pct": 5.0, "signal": "bearish"},
        ]
        assert assess_market_bias(futures) == "bearish"

    def test_vix_below_25_does_not_override(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 1.0, "signal": "bullish"},
            {"symbol": "NQ=F", "name": "Nasdaq Futures", "price": 18000, "change_pct": 1.0, "signal": "bullish"},
            {"symbol": "^VIX", "name": "VIX", "price": 18.0, "change_pct": -2.0, "signal": "flat"},
        ]
        assert assess_market_bias(futures) == "bullish"

    def test_vix_exactly_25_does_not_override(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 1.0, "signal": "bullish"},
            {"symbol": "NQ=F", "name": "Nasdaq Futures", "price": 18000, "change_pct": 1.0, "signal": "bullish"},
            {"symbol": "^VIX", "name": "VIX", "price": 25.0, "change_pct": 0.0, "signal": "flat"},
        ]
        assert assess_market_bias(futures) == "bullish"


# ---------------------------------------------------------------------------
# Req 9.6 — Per-ticker scoring: bias +/-0.5, gaps up to +/-2.0
# ---------------------------------------------------------------------------

class TestScoreTicker:
    """Validates per-ticker pre-market scoring."""

    def test_bullish_bias_adds_half_point(self):
        data = {"market_bias": "bullish", "market_regime": "neutral", "premarket_movers": []}
        result = score_ticker("AAPL", data)
        assert result["score"] == 5.5
        assert result["direction"] == "HOLD"

    def test_bearish_bias_subtracts_half_point(self):
        data = {"market_bias": "bearish", "market_regime": "neutral", "premarket_movers": []}
        result = score_ticker("AAPL", data)
        assert result["score"] == 4.5
        assert result["direction"] == "HOLD"

    def test_neutral_bias_no_change(self):
        data = {"market_bias": "neutral", "market_regime": "neutral", "premarket_movers": []}
        result = score_ticker("AAPL", data)
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"

    def test_large_gap_up_adds_2_5(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [
                {"ticker": "NVDA", "gap_pct": 3.5, "signal": "gap_up"},
            ],
        }
        result = score_ticker("NVDA", data)
        assert result["score"] == 7.5
        assert result["direction"] == "CALL"

    def test_small_gap_up_adds_1_5(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [
                {"ticker": "NVDA", "gap_pct": 1.5, "signal": "gap_up"},
            ],
        }
        result = score_ticker("NVDA", data)
        assert result["score"] == 6.5
        assert result["direction"] == "CALL"

    def test_large_gap_down_subtracts_2_5(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [
                {"ticker": "INTC", "gap_pct": -3.5, "signal": "gap_down"},
            ],
        }
        result = score_ticker("INTC", data)
        assert result["score"] == 2.5
        assert result["direction"] == "PUT"

    def test_small_gap_down_subtracts_1_5(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [
                {"ticker": "INTC", "gap_pct": -1.2, "signal": "gap_down"},
            ],
        }
        result = score_ticker("INTC", data)
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"

    def test_bias_plus_gap_combined(self):
        """Bullish bias (+0.5) + large gap up (+2.5) = 8.0."""
        data = {
            "market_bias": "bullish",
            "market_regime": "neutral",
            "premarket_movers": [
                {"ticker": "TSLA", "gap_pct": 4.0, "signal": "gap_up"},
            ],
        }
        result = score_ticker("TSLA", data)
        assert result["score"] == 8.0
        assert result["direction"] == "CALL"

    def test_score_clamped_to_0_10(self):
        """Score must never go below 0 or above 10."""
        data = {
            "market_bias": "bearish",
            "market_regime": "risk_off",
            "premarket_movers": [
                {"ticker": "X", "gap_pct": -5.0, "signal": "gap_down"},
            ],
        }
        result = score_ticker("X", data)
        assert 0.0 <= result["score"] <= 10.0

    def test_ticker_not_in_movers_gets_only_bias(self):
        data = {
            "market_bias": "bullish",
            "market_regime": "neutral",
            "premarket_movers": [
                {"ticker": "OTHER", "gap_pct": 5.0, "signal": "gap_up"},
            ],
        }
        result = score_ticker("AAPL", data)
        assert result["score"] == 5.5


# ---------------------------------------------------------------------------
# Req 9.3 — Pre-market gaps > 1%
# ---------------------------------------------------------------------------

class TestPremarketMovers:
    """Validates pre-market gap detection."""

    def test_only_gaps_above_1pct_included(self):
        infos = {
            "AAPL": {"preMarketPrice": 102.0, "previousClose": 100.0},  # +2%
            "MSFT": {"preMarketPrice": 100.5, "previousClose": 100.0},  # +0.5%
            "NVDA": {"preMarketPrice": 95.0, "previousClose": 100.0},   # -5%
        }

        def mock_info(ticker):
            return infos.get(ticker, {})

        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            side_effect=mock_info,
        ):
            movers = get_premarket_movers(["AAPL", "MSFT", "NVDA"])

        tickers = [m["ticker"] for m in movers]
        assert "AAPL" in tickers
        assert "NVDA" in tickers
        assert "MSFT" not in tickers  # 0.5% < 1% threshold

    def test_empty_info_skipped(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            return_value={},
        ):
            movers = get_premarket_movers(["AAPL"])
        assert movers == []


# ---------------------------------------------------------------------------
# Req 9.1 — Futures snapshot
# ---------------------------------------------------------------------------

class TestFuturesSnapshot:
    """Validates futures data retrieval."""

    def test_returns_futures_with_change_pct(self):
        hist = _make_futures_history(5000.0, 5050.0)  # +1%

        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=hist,
        ):
            results = get_futures_snapshot()

        assert len(results) > 0
        for r in results:
            assert "symbol" in r
            assert "change_pct" in r
            assert "signal" in r

    def test_handles_fetch_failure_gracefully(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ):
            results = get_futures_snapshot()
        assert results == []


# ---------------------------------------------------------------------------
# Req 9.2 — Global markets
# ---------------------------------------------------------------------------

class TestGlobalMarkets:
    """Validates global index retrieval."""

    def test_returns_global_indices(self):
        hist = _make_futures_history(30000.0, 30300.0)  # +1%

        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=hist,
        ):
            results = get_global_markets()

        assert len(results) > 0
        for r in results:
            assert "name" in r
            assert "change_pct" in r

    def test_handles_fetch_failure_gracefully(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ):
            results = get_global_markets()
        assert results == []


# ---------------------------------------------------------------------------
# Req 21.1 — yfinance failure returns neutral 5.0
# ---------------------------------------------------------------------------

class TestYfinanceFailure:
    """Validates graceful degradation on yfinance errors."""

    def test_run_with_all_failures_returns_neutral_scores(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ), patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            return_value={},
        ):
            results = run(["AAPL", "MSFT"])

        # Filter out the _premarket_summary entry
        scored = [r for r in results if "ticker" in r]
        assert len(scored) == 2
        for r in scored:
            assert r["score"] == 5.0
            assert r["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, returns sorted list
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_returns_results_for_all_tickers(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ), patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            return_value={},
        ):
            results = run(["AAPL", "NVDA", "TSLA"])

        scored = [r for r in results if "ticker" in r]
        assert len(scored) == 3

    def test_includes_premarket_summary(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ), patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            return_value={},
        ):
            results = run(["AAPL"])

        summaries = [r for r in results if "_premarket_summary" in r]
        assert len(summaries) == 1
        summary = summaries[0]["_premarket_summary"]
        assert "market_bias" in summary
        assert "market_regime" in summary
        assert "futures" in summary
        assert "global_markets" in summary
        assert "premarket_movers" in summary

    def test_accepts_config_parameter(self):
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ), patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            return_value={},
        ):
            results = run(["AAPL"], config={"some_key": "some_value"})
        assert len(results) >= 1

    def test_results_sorted_by_score_descending(self):
        """When one ticker has a gap, it should sort higher."""
        infos = {
            "BEAR": {"preMarketPrice": 90.0, "previousClose": 100.0},  # -10%
            "BULL": {"preMarketPrice": 110.0, "previousClose": 100.0},  # +10%
        }

        def mock_info(ticker):
            return infos.get(ticker, {})

        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ), patch(
            "agents.premarket.skills.premarket_analysis._fetch_ticker_info",
            side_effect=mock_info,
        ):
            results = run(["BEAR", "BULL"])

        scored = [r for r in results if "ticker" in r]
        assert scored[0]["score"] >= scored[1]["score"]


# ---------------------------------------------------------------------------
# Return schema
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_result_has_required_keys(self):
        data = {"market_bias": "neutral", "market_regime": "neutral", "premarket_movers": []}
        result = score_ticker("AAPL", data)
        required_keys = {"ticker", "score", "direction", "premarket_reasons", "market_regime"}
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Market regime detection
# ---------------------------------------------------------------------------

class TestMarketRegime:
    """Validates market regime detection logic."""

    def test_risk_on_when_spy_up_and_vix_low(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 0.8, "signal": "bullish"},
            {"symbol": "^VIX", "name": "VIX", "price": 15.0, "change_pct": -1.0, "signal": "flat"},
        ]
        assert detect_market_regime(futures) == "risk_on"

    def test_risk_off_when_spy_down(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": -0.8, "signal": "bearish"},
            {"symbol": "^VIX", "name": "VIX", "price": 18.0, "change_pct": 1.0, "signal": "flat"},
        ]
        assert detect_market_regime(futures) == "risk_off"

    def test_risk_off_when_vix_above_25(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 0.3, "signal": "flat"},
            {"symbol": "^VIX", "name": "VIX", "price": 28.0, "change_pct": 5.0, "signal": "bearish"},
        ]
        assert detect_market_regime(futures) == "risk_off"

    def test_neutral_when_moderate(self):
        futures = [
            {"symbol": "ES=F", "name": "S&P 500 Futures", "price": 5000, "change_pct": 0.3, "signal": "flat"},
            {"symbol": "^VIX", "name": "VIX", "price": 20.0, "change_pct": 0.0, "signal": "flat"},
        ]
        assert detect_market_regime(futures) == "neutral"

    def test_risk_off_applies_minus_1_to_score(self):
        data = {"market_bias": "neutral", "market_regime": "risk_off", "premarket_movers": []}
        result = score_ticker("AAPL", data)
        assert result["score"] == 4.0
        assert result["direction"] == "PUT"

    def test_risk_on_applies_plus_half_to_score(self):
        data = {"market_bias": "neutral", "market_regime": "risk_on", "premarket_movers": []}
        result = score_ticker("AAPL", data)
        assert result["score"] == 5.5
        assert result["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

class TestTrendAnalysis:
    """Validates weekly/monthly trend scoring."""

    def test_strong_up_trend_adds_1_5(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [],
            "_ticker_trends": {
                "AAPL": {
                    "week_change_pct": 6.0,
                    "month_change_pct": 10.0,
                    "trend": "strong_up",
                    "trend_score_adj": 1.5,
                },
            },
        }
        result = score_ticker("AAPL", data)
        assert result["score"] == 6.5
        assert result["direction"] == "CALL"
        assert result["trend"] == "strong_up"

    def test_strong_down_trend_subtracts_1_5(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [],
            "_ticker_trends": {
                "AAPL": {
                    "week_change_pct": -7.0,
                    "month_change_pct": -12.0,
                    "trend": "strong_down",
                    "trend_score_adj": -1.5,
                },
            },
        }
        result = score_ticker("AAPL", data)
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"
        assert result["trend"] == "strong_down"

    def test_flat_trend_no_adjustment(self):
        data = {
            "market_bias": "neutral",
            "market_regime": "neutral",
            "premarket_movers": [],
            "_ticker_trends": {
                "AAPL": {
                    "week_change_pct": 0.5,
                    "month_change_pct": 1.0,
                    "trend": "flat",
                    "trend_score_adj": 0.0,
                },
            },
        }
        result = score_ticker("AAPL", data)
        assert result["score"] == 5.0

    def test_get_ticker_trend_returns_dict_on_failure(self):
        """When yfinance fails, get_ticker_trend returns flat defaults."""
        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=None,
        ):
            trend = get_ticker_trend("AAPL")
        assert trend["trend"] == "flat"
        assert trend["trend_score_adj"] == 0.0

    def test_get_ticker_trend_strong_up(self):
        """A 6% weekly gain should produce strong_up trend."""
        # Build 21-day history with a 6% gain in last 5 days
        dates = pd.date_range(end=pd.Timestamp.now(), periods=21, freq="B")
        prices = [100.0] * 16 + [101.0, 102.0, 103.0, 104.0, 106.0]
        hist = pd.DataFrame({"Close": prices}, index=dates)

        with patch(
            "agents.premarket.skills.premarket_analysis._fetch_history",
            return_value=hist,
        ):
            trend = get_ticker_trend("AAPL")
        assert trend["trend"] == "strong_up"
        assert trend["trend_score_adj"] == 1.5
        assert trend["week_change_pct"] > 5.0


# ---------------------------------------------------------------------------
# write_to_shared_memory — delegates to shared_memory_io
# ---------------------------------------------------------------------------

class TestWriteToSharedMemory:
    """Validates shared memory integration."""

    def test_writes_and_reads_back(self, tmp_path):
        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

            sample = [
                {"ticker": "AAPL", "score": 5.5, "direction": "HOLD", "premarket_reasons": ["Futures bullish"]},
                {"ticker": "NVDA", "score": 7.0, "direction": "CALL", "premarket_reasons": ["Pre-market gap up 3.5%"]},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("premarket", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "premarket"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "AAPL"
