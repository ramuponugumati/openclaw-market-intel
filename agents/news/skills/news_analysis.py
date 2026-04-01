"""
News Analysis Skill

Fetches recent news articles from Finnhub's company-news endpoint and scores
each ticker's headlines using keyword-based sentiment matching.  Produces a
0-10 score per ticker with CALL / PUT / HOLD direction.

Adapted from market-intel/agents/news.py for the OpenClaw framework.

Requirements: 6.1, 6.2, 6.3, 6.4, 21.1, 21.4
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach shared_memory_io
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io  # noqa: E402
from rate_limiter import get_finnhub_limiter  # noqa: E402

logger = logging.getLogger(__name__)

FINNHUB_TIMEOUT_S = 10
_limiter = get_finnhub_limiter()

POSITIVE_KEYWORDS = [
    "beat", "surge", "rally", "upgrade", "record", "growth",
]
NEGATIVE_KEYWORDS = [
    "miss", "crash", "downgrade", "layoff", "lawsuit", "investigation",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_news(ticker: str, api_key: str) -> list[dict]:
    """Fetch up to 10 recent articles from Finnhub company-news (trailing 3 days)."""
    try:
        _limiter.wait()
        today = datetime.now().strftime("%Y-%m-%d")
        three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from": three_days_ago,
                "to": today,
                "token": api_key,
            },
            timeout=FINNHUB_TIMEOUT_S,
        )
        if resp.ok:
            return resp.json()[:10]
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", ticker, exc)
    return []


def _score_headline(headline: str) -> float:
    """Keyword-based sentiment scoring: +1 per positive keyword, -1 per negative."""
    h = headline.lower()
    pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in h)
    neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in h)
    return pos - neg


def analyze_ticker(ticker: str, api_key: str) -> dict:
    """Score a single ticker based on recent news sentiment."""
    articles = _fetch_news(ticker, api_key)

    if not articles:
        return {
            "ticker": ticker,
            "score": 5.0,
            "direction": "HOLD",
            "headlines": [],
            "news_count": 0,
            "avg_sentiment": 0.0,
        }

    total_sentiment = 0.0
    headlines = []
    for article in articles:
        headline = article.get("headline", "")
        sent = _score_headline(headline)
        total_sentiment += sent
        if sent != 0:
            headlines.append({
                "headline": headline[:100],
                "sentiment": "+" if sent > 0 else "-",
            })

    avg_sentiment = total_sentiment / len(articles)
    score = 5.0 + (avg_sentiment * 1.5)
    score = max(0.0, min(10.0, score))
    direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

    return {
        "ticker": ticker,
        "score": round(score, 1),
        "direction": direction,
        "headlines": headlines[:3],
        "news_count": len(articles),
        "avg_sentiment": round(avg_sentiment, 2),
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[str], config: dict | None = None) -> list[dict]:
    """
    Run news analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Agent configuration dict; must contain 'finnhub_api_key'.

    Returns:
        A list of per-ticker result dicts sorted by score descending.
    """
    config = config or {}
    api_key = config.get("finnhub_api_key", "")
    if not api_key:
        logger.error("No finnhub_api_key in config — all tickers will get neutral scores")

    logger.info("Running News Agent on %d tickers…", len(watchlist))
    results = [analyze_ticker(t, api_key) for t in watchlist]
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("News complete: %d tickers analysed", len(results))
    return results


def write_to_shared_memory(run_id: str, results: list[dict]) -> str:
    """
    Persist *results* to shared memory as a markdown file.

    Args:
        run_id: The current run identifier (e.g. '20260115_053000').
        results: The list returned by :func:`run`.

    Returns:
        The file path of the written result file.
    """
    return shared_memory_io.write_agent_result(
        agent_id="news",
        run_id=run_id,
        results=results,
    )
