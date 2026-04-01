from __future__ import annotations

"""
Fundamentals Analysis Skill

Retrieves trailing PE, forward PE, revenue growth, earnings growth, analyst
recommendation, and target price for each ticker using yfinance.  Produces a
0-10 score per ticker with CALL / PUT / HOLD direction.

Adapted from market-intel/agents/fundamentals.py for the OpenClaw framework.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 21.1, 21.4
"""

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

import yfinance as yf

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach shared_memory_io
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io  # noqa: E402

logger = logging.getLogger(__name__)

YFINANCE_TIMEOUT_S = 10


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_ticker_info(ticker: str) -> dict[str, Any]:
    """Fetch yfinance .info for *ticker* with a hard timeout."""
    def _get() -> dict[str, Any]:
        return yf.Ticker(ticker).info or {}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get)
        try:
            return future.result(timeout=YFINANCE_TIMEOUT_S)
        except (FuturesTimeoutError, Exception) as exc:
            logger.warning("yfinance timeout/error for %s: %s", ticker, exc)
            return {}


def analyze_ticker(ticker: str) -> dict:
    """Analyse a single ticker's fundamentals and return a scored dict."""
    try:
        info = _fetch_ticker_info(ticker)
        if not info:
            raise ValueError("empty info dict")

        score = 5.0  # neutral baseline

        pe = info.get("trailingPE")
        fwd_pe = info.get("forwardPE")
        rev_growth = info.get("revenueGrowth", 0) or 0
        earn_growth = info.get("earningsGrowth", 0) or 0
        rec = info.get("recommendationKey", "none")
        target_price = info.get("targetMeanPrice", 0) or 0
        current_price = (
            info.get("currentPrice", 0)
            or info.get("regularMarketPrice", 0)
            or 0
        )

        # --- Scoring adjustments ---
        # Earnings growth
        if earn_growth > 0.20:
            score += 2.0
        elif earn_growth > 0.05:
            score += 1.0
        elif earn_growth < -0.10:
            score -= 2.0

        # Revenue growth
        if rev_growth > 0.15:
            score += 1.5
        elif rev_growth < -0.05:
            score -= 1.5

        # Forward PE improvement
        if fwd_pe and pe and fwd_pe < pe:
            score += 0.5

        # Analyst recommendation
        if rec in ("buy", "strongBuy"):
            score += 1.0
        elif rec in ("sell", "strongSell"):
            score -= 1.5

        # Upside to analyst target
        upside = 0.0
        if target_price and current_price and current_price > 0:
            upside = (target_price - current_price) / current_price
            if upside > 0.15:
                score += 1.0
            elif upside < -0.10:
                score -= 1.0

        score = max(0.0, min(10.0, score))
        direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

        return {
            "ticker": ticker,
            "score": round(score, 1),
            "direction": direction,
            "pe": pe,
            "fwd_pe": fwd_pe,
            "revenue_growth": f"{rev_growth:.1%}" if rev_growth else "N/A",
            "earnings_growth": f"{earn_growth:.1%}" if earn_growth else "N/A",
            "analyst_rec": rec,
            "upside_to_target": f"{upside:.1%}" if upside else "N/A",
            "price": current_price,
        }
    except Exception as exc:
        logger.warning("Fundamentals failed for %s: %s", ticker, exc)
        return {
            "ticker": ticker,
            "score": 5.0,
            "direction": "HOLD",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[str], config: dict | None = None) -> list[dict]:
    """
    Run fundamentals analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Optional agent configuration dict (reserved for future use,
                e.g. custom scoring thresholds).

    Returns:
        A list of per-ticker result dicts sorted by score descending.
    """
    logger.info("Running Fundamentals Agent on %d tickers…", len(watchlist))
    results = [analyze_ticker(t) for t in watchlist]
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Fundamentals complete: %d tickers analysed", len(results))
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
        agent_id="fundamentals",
        run_id=run_id,
        results=results,
    )
