from __future__ import annotations

"""
Sentiment Analysis Skill

Retrieves social sentiment (Reddit, Twitter) and analyst recommendation
trends for each ticker using the Finnhub API.  Produces a 0-10 score
per ticker with CALL / PUT / HOLD direction.

Adapted from market-intel/agents/sentiment.py for the OpenClaw framework.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 21.1, 21.4
"""

import logging
import sys
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_finnhub_api_key(config: dict | None) -> str:
    """Extract the Finnhub API key from config or environment."""
    if config and config.get("finnhub_api_key"):
        return config["finnhub_api_key"]
    import os
    return os.environ.get("FINNHUB_API_KEY", "")


def get_finnhub_sentiment(ticker: str, api_key: str) -> dict[str, Any]:
    """
    Get social sentiment from Finnhub.

    Returns dict with 'positive_pct' (0.0-1.0) and 'mentions' (int).
    Defaults to neutral 50% positive with 0 mentions on any failure.
    """
    try:
        _limiter.wait()
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/social-sentiment",
            params={"symbol": ticker, "from": "2024-01-01", "token": api_key},
            timeout=FINNHUB_TIMEOUT_S,
        )
        if resp.ok:
            data = resp.json()
            reddit = data.get("reddit", [])
            twitter = data.get("twitter", [])
            pos = sum(1 for p in reddit + twitter if p.get("score", 0) > 0)
            neg = sum(1 for p in reddit + twitter if p.get("score", 0) < 0)
            total = pos + neg
            if total > 0:
                return {"positive_pct": pos / total, "mentions": total}
        return {"positive_pct": 0.5, "mentions": 0}
    except Exception as exc:
        logger.warning("Finnhub social sentiment failed for %s: %s", ticker, exc)
        return {"positive_pct": 0.5, "mentions": 0}


def get_analyst_recommendations(ticker: str, api_key: str) -> dict[str, int]:
    """
    Get latest analyst recommendation trends from Finnhub.

    Returns dict with 'buy', 'sell', 'hold' counts.
    Defaults to all zeros on any failure.
    """
    try:
        _limiter.wait()
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/recommendation",
            params={"symbol": ticker, "token": api_key},
            timeout=FINNHUB_TIMEOUT_S,
        )
        if resp.ok:
            recs = resp.json()
            if recs:
                latest = recs[0]
                buy = latest.get("buy", 0) + latest.get("strongBuy", 0)
                sell = latest.get("sell", 0) + latest.get("strongSell", 0)
                hold = latest.get("hold", 0)
                return {"buy": buy, "sell": sell, "hold": hold}
        return {"buy": 0, "sell": 0, "hold": 0}
    except Exception as exc:
        logger.warning("Finnhub analyst recs failed for %s: %s", ticker, exc)
        return {"buy": 0, "sell": 0, "hold": 0}


def analyze_ticker(ticker: str, api_key: str) -> dict:
    """
    Score sentiment for a single ticker.

    Scoring logic (base 5.0):
      - Social: +2.0 if >70% positive AND >10 mentions
      - Social: +1.0 if >60% positive (lower tier)
      - Social: -2.0 if <30% positive AND >10 mentions
      - Social: -1.0 if <40% positive (lower tier)
      - Analyst: +1.5 if buy% >70%
      - Analyst: +0.5 if buy% >50%
      - Analyst: -1.5 if sell% >30%

    Returns a dict with ticker, score, direction, and sentiment details.
    """
    sentiment = get_finnhub_sentiment(ticker, api_key)
    analysts = get_analyst_recommendations(ticker, api_key)

    score = 5.0

    # --- Social sentiment scoring ---
    pos_pct = sentiment["positive_pct"]
    mentions = sentiment["mentions"]

    if pos_pct > 0.7 and mentions > 10:
        score += 2.0
    elif pos_pct > 0.6:
        score += 1.0
    elif pos_pct < 0.3 and mentions > 10:
        score -= 2.0
    elif pos_pct < 0.4:
        score -= 1.0

    # --- Analyst recommendation scoring ---
    total_analysts = analysts["buy"] + analysts["sell"] + analysts["hold"]
    if total_analysts > 0:
        buy_pct = analysts["buy"] / total_analysts
        if buy_pct > 0.7:
            score += 1.5
        elif buy_pct > 0.5:
            score += 0.5

        sell_pct = analysts["sell"] / total_analysts
        if sell_pct > 0.3:
            score -= 1.5

    score = max(0.0, min(10.0, score))
    direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

    return {
        "ticker": ticker,
        "score": round(score, 1),
        "direction": direction,
        "social_positive_pct": f"{pos_pct:.0%}",
        "social_mentions": mentions,
        "analyst_buy": analysts["buy"],
        "analyst_sell": analysts["sell"],
        "analyst_hold": analysts["hold"],
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[str], config: dict | None = None) -> list[dict]:
    """
    Run sentiment analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Optional agent configuration dict. May contain
                'finnhub_api_key' for API authentication.

    Returns:
        A list of per-ticker result dicts sorted by score descending.
    """
    api_key = _get_finnhub_api_key(config)
    if not api_key:
        logger.error("No Finnhub API key available — returning neutral scores")
        return [
            {
                "ticker": t,
                "score": 5.0,
                "direction": "HOLD",
                "social_positive_pct": "50%",
                "social_mentions": 0,
                "analyst_buy": 0,
                "analyst_sell": 0,
                "analyst_hold": 0,
                "error": "missing_api_key",
            }
            for t in watchlist
        ]

    logger.info("Running Sentiment Agent on %d tickers…", len(watchlist))
    results = [analyze_ticker(t, api_key) for t in watchlist]
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Sentiment complete: %d tickers analysed", len(results))
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
        agent_id="sentiment",
        run_id=run_id,
        results=results,
    )
