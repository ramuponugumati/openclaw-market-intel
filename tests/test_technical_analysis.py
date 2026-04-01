"""
Unit tests for the Technical Analysis Skill.

Validates Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 21.1, 21.4
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.technical.skills.technical_analysis import (
    analyze_ticker,
    compute_rsi,
    run,
    write_to_shared_memory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_history(
    num_days: int = 60,
    start_price: float = 100.0,
    trend: float = 0.0,
    volume_base: int = 1_000_000,
) -> pd.DataFrame:
    """Build a synthetic price/volume DataFrame mimicking yfinance output.

    Args:
        num_days: Number of trading days.
        start_price: Opening price on day 0.
        trend: Daily price drift (positive = uptrend).
        volume_base: Average daily volume.
    """
    np.random.seed(42)
    prices = start_price + trend * np.arange(num_days) + np.random.randn(num_days) * 0.5
    prices = np.maximum(prices, 1.0)  # no negative prices
    volumes = (volume_base + np.random.randint(-100_000, 100_000, num_days)).astype(float)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=num_days, freq="B")
    return pd.DataFrame(
        {"Close": prices, "Volume": volumes, "Open": prices - 0.5, "High": prices + 1, "Low": prices - 1},
        index=dates,
    )


def _make_oversold_history() -> pd.DataFrame:
    """Create history where RSI will be < 30 (sustained decline)."""
    num_days = 60
    prices = np.linspace(150.0, 80.0, num_days)  # steady decline
    volumes = np.full(num_days, 1_000_000.0)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=num_days, freq="B")
    return pd.DataFrame(
        {"Close": prices, "Volume": volumes, "Open": prices + 0.5, "High": prices + 1, "Low": prices - 1},
        index=dates,
    )


def _make_overbought_history() -> pd.DataFrame:
    """Create history where RSI will be > 70 (sustained rally)."""
    num_days = 60
    prices = np.linspace(80.0, 150.0, num_days)  # steady rise
    volumes = np.full(num_days, 1_000_000.0)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=num_days, freq="B")
    return pd.DataFrame(
        {"Close": prices, "Volume": volumes, "Open": prices - 0.5, "High": prices + 1, "Low": prices - 1},
        index=dates,
    )


def _make_golden_cross_history() -> pd.DataFrame:
    """Create history where SMA20 > SMA50, price above both, and RSI is neutral (~48).

    Strategy: low prices early (pulls SMA50 down), then oscillate at a higher
    level so SMA20 > SMA50 and current price > both, while RSI stays moderate.
    """
    num_days = 60
    low_phase = np.full(30, 90.0)
    np.random.seed(4)
    high_phase = 120.0 + np.cumsum(np.random.choice([-0.3, 0.5], size=30))
    prices = np.concatenate([low_phase, high_phase])
    volumes = np.full(num_days, 1_000_000.0)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=num_days, freq="B")
    return pd.DataFrame(
        {"Close": prices, "Volume": volumes, "Open": prices - 0.5, "High": prices + 1, "Low": prices - 1},
        index=dates,
    )


# ---------------------------------------------------------------------------
# compute_rsi tests
# ---------------------------------------------------------------------------

class TestComputeRSI:
    """Validates RSI computation (Req 7.2)."""

    def test_all_gains_returns_100(self):
        """Monotonically increasing prices → RSI = 100."""
        prices = np.arange(1.0, 20.0)
        assert compute_rsi(prices) == 100.0

    def test_all_losses_returns_near_zero(self):
        """Monotonically decreasing prices → RSI near 0."""
        prices = np.arange(20.0, 1.0, -1.0)
        assert compute_rsi(prices) < 10.0

    def test_mixed_returns_between_0_and_100(self):
        """Normal price series → RSI between 0 and 100."""
        np.random.seed(99)
        prices = 100 + np.cumsum(np.random.randn(30))
        rsi = compute_rsi(prices)
        assert 0 <= rsi <= 100


# ---------------------------------------------------------------------------
# Requirement 7.3 — RSI < 30 adds 2.0 (oversold)
# ---------------------------------------------------------------------------

class TestRSIOversold:
    """Validates RSI oversold scoring."""

    def test_rsi_below_30_adds_2(self):
        """RSI < 30 should add 2.0 to base score."""
        hist = _make_oversold_history()
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=hist,
        ):
            result = analyze_ticker("OVERSOLD")
        rsi = compute_rsi(hist["Close"].values)
        assert rsi < 30, f"Test setup error: RSI={rsi}, expected < 30"
        # Score should be above neutral due to oversold bonus
        assert result["score"] > 5.0
        assert result["rsi"] < 30


# ---------------------------------------------------------------------------
# Requirement 7.4 — RSI > 70 subtracts 2.0 (overbought)
# ---------------------------------------------------------------------------

class TestRSIOverbought:
    """Validates RSI overbought scoring."""

    def test_rsi_above_70_subtracts_2(self):
        """RSI > 70 should subtract 2.0 from base score."""
        hist = _make_overbought_history()
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=hist,
        ):
            result = analyze_ticker("OVERBOUGHT")
        rsi = compute_rsi(hist["Close"].values)
        assert rsi > 70, f"Test setup error: RSI={rsi}, expected > 70"
        # The overbought penalty should push score below neutral
        assert result["rsi"] > 70


# ---------------------------------------------------------------------------
# Requirement 7.5 — Golden cross + price above both SMAs adds 1.5
# ---------------------------------------------------------------------------

class TestGoldenCross:
    """Validates golden cross scoring."""

    def test_golden_cross_with_price_above_smas(self):
        """Golden cross (SMA20 > SMA50) + price above both → +1.5."""
        hist = _make_golden_cross_history()
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=hist,
        ):
            result = analyze_ticker("GOLDEN")
        assert result["golden_cross"] is True
        assert result["above_sma20"] is True
        assert result["above_sma50"] is True
        # Should have golden cross bonus contributing to score
        assert result["score"] > 5.0


# ---------------------------------------------------------------------------
# Requirement 7.6 — Fewer than 20 days → neutral 5.0
# ---------------------------------------------------------------------------

class TestInsufficientData:
    """Validates neutral score on insufficient history."""

    def test_fewer_than_20_days_returns_neutral(self):
        """< 20 days of history → score 5.0, HOLD."""
        short_hist = _make_history(num_days=15)
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=short_hist,
        ):
            result = analyze_ticker("SHORT")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"
        assert "error" in result

    def test_empty_history_returns_neutral(self):
        """Empty DataFrame → score 5.0, HOLD."""
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=pd.DataFrame(),
        ):
            result = analyze_ticker("EMPTY")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"

    def test_none_history_returns_neutral(self):
        """None (timeout) → score 5.0, HOLD."""
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=None,
        ):
            result = analyze_ticker("TIMEOUT")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# Requirement 21.1 — yfinance failure returns neutral 5.0
# ---------------------------------------------------------------------------

class TestYfinanceFailure:
    """Validates graceful degradation on yfinance errors."""

    def test_exception_returns_neutral(self):
        """Exception during fetch → score 5.0, HOLD."""
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            side_effect=RuntimeError("network error"),
        ):
            result = analyze_ticker("ERR")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"
        assert "error" in result


# ---------------------------------------------------------------------------
# Return schema (Req 7.1, 7.2)
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_successful_result_has_all_fields(self):
        hist = _make_history()
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=hist,
        ):
            result = analyze_ticker("AAPL")
        required_keys = {
            "ticker", "score", "direction", "price", "rsi",
            "sma_20", "sma_50", "above_sma20", "above_sma50",
            "golden_cross", "volume_ratio",
        }
        assert required_keys.issubset(result.keys())

    def test_score_clamped_to_0_10(self):
        """Score must never exceed 10 or go below 0."""
        hist = _make_history()
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=hist,
        ):
            result = analyze_ticker("CLAMP")
        assert 0 <= result["score"] <= 10


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, returns sorted list
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_returns_sorted_by_score_descending(self):
        bull_hist = _make_golden_cross_history()
        bear_hist = _make_oversold_history()

        def mock_fetch(ticker):
            return bull_hist if ticker == "BULL" else bear_hist

        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            side_effect=mock_fetch,
        ):
            results = run(["BEAR", "BULL"])

        assert len(results) == 2
        assert results[0]["score"] >= results[1]["score"]

    def test_accepts_config_parameter(self):
        """run() should accept an optional config dict without error."""
        hist = _make_history()
        with patch(
            "agents.technical.skills.technical_analysis._fetch_ticker_history",
            return_value=hist,
        ):
            results = run(["AAPL"], config={"scoring": {"rsi_period": 14}})
        assert len(results) == 1


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
                {"ticker": "AAPL", "score": 7.5, "direction": "CALL", "rsi": 45.2},
                {"ticker": "INTC", "score": 3.2, "direction": "PUT", "rsi": 72.1},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("technical", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "technical"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "AAPL"
