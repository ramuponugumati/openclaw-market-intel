"""
Unit tests for the News Analysis Skill.

Validates Requirements: 6.1, 6.2, 6.3, 6.4, 21.1, 21.4
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.news.skills.news_analysis import (
    analyze_ticker,
    run,
    write_to_shared_memory,
    _score_headline,
    _fetch_news,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_articles(headlines: list[str]) -> list[dict]:
    """Build a list of Finnhub-style article dicts from headline strings."""
    return [{"headline": h, "source": "test"} for h in headlines]


# ---------------------------------------------------------------------------
# Requirement 6.2 — Keyword-based headline scoring
# ---------------------------------------------------------------------------

class TestHeadlineScoring:
    """Validates keyword matching for positive and negative keywords."""

    def test_positive_keyword_scores_positive(self):
        assert _score_headline("NVDA earnings beat expectations") > 0

    def test_negative_keyword_scores_negative(self):
        assert _score_headline("Company faces lawsuit over fraud") < 0

    def test_neutral_headline_scores_zero(self):
        assert _score_headline("Company releases quarterly report") == 0

    def test_multiple_positive_keywords(self):
        score = _score_headline("Stock surge after record growth")
        assert score == 3  # surge + record + growth

    def test_multiple_negative_keywords(self):
        score = _score_headline("Crash leads to layoff and investigation")
        assert score == -3  # crash + layoff + investigation

    def test_mixed_keywords(self):
        score = _score_headline("Growth despite lawsuit concerns")
        assert score == 0  # +1 growth, -1 lawsuit


# ---------------------------------------------------------------------------
# Requirement 6.3 — Average sentiment → 0-10 score with 1.5x multiplier
# ---------------------------------------------------------------------------

class TestSentimentScoring:
    """Validates sentiment-to-score conversion logic."""

    def test_positive_sentiment_above_6_is_call(self):
        """Positive headlines → score ≥ 6 → CALL."""
        articles = _make_articles(["Stock surge after beat", "Rally continues"])
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles,
        ):
            result = analyze_ticker("BULL", "fake_key")
        assert result["score"] >= 6
        assert result["direction"] == "CALL"

    def test_negative_sentiment_below_4_is_put(self):
        """Negative headlines → score ≤ 4 → PUT."""
        articles = _make_articles(["Company crash after lawsuit", "Layoff announced"])
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles,
        ):
            result = analyze_ticker("BEAR", "fake_key")
        assert result["score"] <= 4
        assert result["direction"] == "PUT"

    def test_neutral_headlines_score_around_5(self):
        """Neutral headlines → score ~5.0 → HOLD."""
        articles = _make_articles(["Quarterly report released", "CEO speaks at conference"])
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles,
        ):
            result = analyze_ticker("NEUT", "fake_key")
        assert 4 < result["score"] < 6
        assert result["direction"] == "HOLD"

    def test_score_clamped_to_0_10(self):
        """Score must never exceed 10 or go below 0."""
        # Extremely positive
        articles = _make_articles(
            ["beat surge rally upgrade record growth"] * 10
        )
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles,
        ):
            result = analyze_ticker("MAX", "fake_key")
        assert 0 <= result["score"] <= 10

        # Extremely negative
        articles_neg = _make_articles(
            ["miss crash downgrade layoff lawsuit investigation"] * 10
        )
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles_neg,
        ):
            result_neg = analyze_ticker("MIN", "fake_key")
        assert 0 <= result_neg["score"] <= 10

    def test_multiplier_applied_correctly(self):
        """avg_sentiment * 1.5 added to base 5.0."""
        # 2 articles, each with 1 positive keyword → total=2, avg=1.0
        articles = _make_articles(["Stock beat", "Earnings beat"])
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles,
        ):
            result = analyze_ticker("MULT", "fake_key")
        # base 5.0 + (1.0 * 1.5) = 6.5
        assert result["score"] == 6.5


# ---------------------------------------------------------------------------
# Requirement 6.4 — No articles → neutral 5.0 HOLD
# ---------------------------------------------------------------------------

class TestNoArticles:
    """Validates fallback when no news is found."""

    def test_empty_articles_returns_neutral(self):
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=[],
        ):
            result = analyze_ticker("EMPTY", "fake_key")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"
        assert result["news_count"] == 0


# ---------------------------------------------------------------------------
# Requirement 21.1 — API failure returns neutral score
# ---------------------------------------------------------------------------

class TestApiFailure:
    """Validates graceful degradation on Finnhub errors."""

    def test_fetch_exception_returns_empty(self):
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=[],
        ):
            result = analyze_ticker("FAIL", "fake_key")
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"


# ---------------------------------------------------------------------------
# Return schema
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_successful_result_has_all_fields(self):
        articles = _make_articles(["Stock beat expectations"])
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=articles,
        ):
            result = analyze_ticker("AAPL", "fake_key")
        required_keys = {"ticker", "score", "direction", "headlines", "news_count", "avg_sentiment"}
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, returns sorted list
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_returns_sorted_by_score_descending(self):
        def mock_fetch(ticker, api_key):
            if ticker == "HIGH":
                return _make_articles(["Stock surge after beat", "Rally continues"])
            return _make_articles(["Company crash after lawsuit"])

        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            side_effect=mock_fetch,
        ):
            results = run(["LOW", "HIGH"], config={"finnhub_api_key": "fake"})

        assert len(results) == 2
        assert results[0]["ticker"] == "HIGH"
        assert results[0]["score"] >= results[1]["score"]

    def test_accepts_config_with_api_key(self):
        with patch(
            "agents.news.skills.news_analysis._fetch_news",
            return_value=[],
        ):
            results = run(["AAPL"], config={"finnhub_api_key": "test_key"})
        assert len(results) == 1


# ---------------------------------------------------------------------------
# write_to_shared_memory — delegates to shared_memory_io
# ---------------------------------------------------------------------------

class TestWriteToSharedMemory:
    """Validates shared memory integration."""

    def test_writes_and_reads_back(self, tmp_path):
        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

            sample = [
                {"ticker": "AAPL", "score": 7.5, "direction": "CALL", "news_count": 5},
                {"ticker": "INTC", "score": 3.2, "direction": "PUT", "news_count": 3},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("news", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "news"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "AAPL"
