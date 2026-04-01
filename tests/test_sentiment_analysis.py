"""
Unit tests for the Sentiment Analysis Skill.

Validates Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 21.1, 21.4
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

from agents.sentiment.skills.sentiment_analysis import (
    analyze_ticker,
    get_finnhub_sentiment,
    get_analyst_recommendations,
    run,
    write_to_shared_memory,
)

FAKE_API_KEY = "test_key_123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_sentiment_response(positive: int, negative: int):
    """Build a mock Finnhub social-sentiment JSON response."""
    reddit = [{"score": 1}] * positive + [{"score": -1}] * negative
    return {"reddit": reddit, "twitter": []}


def _mock_analyst_response(buy: int, strong_buy: int, sell: int,
                           strong_sell: int, hold: int):
    """Build a mock Finnhub recommendation JSON response."""
    return [{"buy": buy, "strongBuy": strong_buy, "sell": sell,
             "strongSell": strong_sell, "hold": hold}]


# ---------------------------------------------------------------------------
# Requirement 4.2 — >70% positive with >10 mentions adds 2.0
# ---------------------------------------------------------------------------

class TestSocialSentimentScoring:
    """Validates social sentiment scoring thresholds."""

    def test_high_positive_high_mentions_adds_2(self):
        """>70% positive AND >10 mentions → +2.0."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.80, "mentions": 15},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 0, "sell": 0, "hold": 0},
        ):
            result = analyze_ticker("BULL", FAKE_API_KEY)
        # base 5.0 + 2.0 social = 7.0
        assert result["score"] == 7.0
        assert result["direction"] == "CALL"

    def test_moderate_positive_adds_1(self):
        """>60% positive (but ≤70% or ≤10 mentions) → +1.0."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.65, "mentions": 5},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 0, "sell": 0, "hold": 0},
        ):
            result = analyze_ticker("MID", FAKE_API_KEY)
        # base 5.0 + 1.0 = 6.0
        assert result["score"] == 6.0

    def test_very_negative_high_mentions_subtracts_2(self):
        """<30% positive AND >10 mentions → -2.0."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.20, "mentions": 20},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 0, "sell": 0, "hold": 0},
        ):
            result = analyze_ticker("BEAR", FAKE_API_KEY)
        # base 5.0 - 2.0 = 3.0
        assert result["score"] == 3.0
        assert result["direction"] == "PUT"

    def test_moderate_negative_subtracts_1(self):
        """<40% positive (but ≥30% or ≤10 mentions) → -1.0."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.35, "mentions": 5},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 0, "sell": 0, "hold": 0},
        ):
            result = analyze_ticker("WEAK", FAKE_API_KEY)
        # base 5.0 - 1.0 = 4.0
        assert result["score"] == 4.0


# ---------------------------------------------------------------------------
# Requirement 4.3 — Analyst buy >70% adds 1.5
# ---------------------------------------------------------------------------

class TestAnalystBuyScoring:
    """Validates analyst buy percentage scoring."""

    def test_buy_above_70pct_adds_1_5(self):
        """Analyst buy% > 70% → +1.5."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.5, "mentions": 0},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 8, "sell": 0, "hold": 2},
        ):
            result = analyze_ticker("ABUY", FAKE_API_KEY)
        # base 5.0 + 1.5 analyst buy = 6.5
        assert result["score"] == 6.5

    def test_buy_above_50pct_adds_0_5(self):
        """Analyst buy% > 50% but ≤ 70% → +0.5."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.5, "mentions": 0},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 6, "sell": 0, "hold": 4},
        ):
            result = analyze_ticker("MBUY", FAKE_API_KEY)
        # base 5.0 + 0.5 = 5.5
        assert result["score"] == 5.5


# ---------------------------------------------------------------------------
# Requirement 4.4 — Analyst sell >30% subtracts 1.5
# ---------------------------------------------------------------------------

class TestAnalystSellScoring:
    """Validates analyst sell percentage scoring."""

    def test_sell_above_30pct_subtracts_1_5(self):
        """Analyst sell% > 30% → -1.5."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.5, "mentions": 0},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 2, "sell": 5, "hold": 3},
        ):
            result = analyze_ticker("ASEL", FAKE_API_KEY)
        # base 5.0 - 1.5 sell = 3.5
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"


# ---------------------------------------------------------------------------
# Requirement 4.5 — Finnhub failure returns neutral 5.0
# ---------------------------------------------------------------------------

class TestFinnhubFailure:
    """Validates graceful degradation on Finnhub API errors."""

    def test_sentiment_api_failure_returns_neutral(self):
        """Finnhub social sentiment failure → 50% positive, 0 mentions."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        with patch("agents.sentiment.skills.sentiment_analysis.requests.get",
                    return_value=mock_resp):
            result = get_finnhub_sentiment("FAIL", FAKE_API_KEY)
        assert result["positive_pct"] == 0.5
        assert result["mentions"] == 0

    def test_analyst_api_failure_returns_zeros(self):
        """Finnhub analyst recs failure → all zeros."""
        with patch("agents.sentiment.skills.sentiment_analysis.requests.get",
                    side_effect=Exception("network error")):
            result = get_analyst_recommendations("FAIL", FAKE_API_KEY)
        assert result == {"buy": 0, "sell": 0, "hold": 0}

    def test_analyze_ticker_with_all_failures_returns_neutral(self):
        """Both APIs fail → score 5.0, HOLD."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.5, "mentions": 0},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 0, "sell": 0, "hold": 0},
        ):
            result = analyze_ticker("FAIL", FAKE_API_KEY)
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"

    def test_run_without_api_key_returns_neutral(self):
        """Missing API key → all tickers get neutral 5.0."""
        results = run(["AAPL", "MSFT"], config={})
        assert len(results) == 2
        for r in results:
            assert r["score"] == 5.0
            assert r["direction"] == "HOLD"
            assert r["error"] == "missing_api_key"


# ---------------------------------------------------------------------------
# Score clamping and direction
# ---------------------------------------------------------------------------

class TestScoreClampingAndDirection:
    """Validates score stays in 0-10 range and direction mapping."""

    def test_score_clamped_to_0_10(self):
        """Extreme bullish stacking should not exceed 10."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.90, "mentions": 50},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 10, "sell": 0, "hold": 0},
        ):
            result = analyze_ticker("MAX", FAKE_API_KEY)
        assert 0 <= result["score"] <= 10

    def test_score_not_below_zero(self):
        """Extreme bearish stacking should not go below 0."""
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.10, "mentions": 50},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 0, "sell": 10, "hold": 0},
        ):
            result = analyze_ticker("MIN", FAKE_API_KEY)
        assert 0 <= result["score"] <= 10


# ---------------------------------------------------------------------------
# Return schema
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_result_has_all_fields(self):
        with patch(
            "agents.sentiment.skills.sentiment_analysis.get_finnhub_sentiment",
            return_value={"positive_pct": 0.6, "mentions": 5},
        ), patch(
            "agents.sentiment.skills.sentiment_analysis.get_analyst_recommendations",
            return_value={"buy": 3, "sell": 1, "hold": 2},
        ):
            result = analyze_ticker("AAPL", FAKE_API_KEY)
        required_keys = {
            "ticker", "score", "direction", "social_positive_pct",
            "social_mentions", "analyst_buy", "analyst_sell", "analyst_hold",
        }
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, returns sorted list
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_returns_sorted_by_score_descending(self):
        def mock_analyze(ticker, api_key):
            scores = {"LOW": 3.0, "HIGH": 8.0}
            s = scores.get(ticker, 5.0)
            d = "CALL" if s >= 6 else "PUT" if s <= 4 else "HOLD"
            return {"ticker": ticker, "score": s, "direction": d,
                    "social_positive_pct": "50%", "social_mentions": 0,
                    "analyst_buy": 0, "analyst_sell": 0, "analyst_hold": 0}

        with patch(
            "agents.sentiment.skills.sentiment_analysis.analyze_ticker",
            side_effect=mock_analyze,
        ):
            results = run(["LOW", "HIGH"], config={"finnhub_api_key": "key"})
        assert len(results) == 2
        assert results[0]["ticker"] == "HIGH"
        assert results[0]["score"] >= results[1]["score"]

    def test_accepts_config_parameter(self):
        with patch(
            "agents.sentiment.skills.sentiment_analysis.analyze_ticker",
            return_value={"ticker": "AAPL", "score": 5.0, "direction": "HOLD",
                          "social_positive_pct": "50%", "social_mentions": 0,
                          "analyst_buy": 0, "analyst_sell": 0, "analyst_hold": 0},
        ):
            results = run(["AAPL"], config={"finnhub_api_key": "key"})
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
                {"ticker": "AAPL", "score": 7.0, "direction": "CALL",
                 "social_positive_pct": "80%", "social_mentions": 15,
                 "analyst_buy": 8, "analyst_sell": 0, "analyst_hold": 2},
                {"ticker": "INTC", "score": 3.5, "direction": "PUT",
                 "social_positive_pct": "25%", "social_mentions": 20,
                 "analyst_buy": 1, "analyst_sell": 5, "analyst_hold": 4},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("sentiment", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "sentiment"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "AAPL"
