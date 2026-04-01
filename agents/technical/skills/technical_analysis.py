from __future__ import annotations

"""
Technical Analysis Skill

Retrieves 3 months of daily price and volume history from yfinance, then
computes 14-period RSI, 20-day SMA, 50-day SMA, and 5d/20d volume ratio.
Produces a 0-10 score per ticker with CALL / PUT / HOLD direction.

Adapted from market-intel/agents/technical.py for the OpenClaw framework.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 21.1, 21.4
"""

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

import numpy as np
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

def _fetch_ticker_history(ticker: str) -> Any:
    """Fetch 3 months of daily history for *ticker* with a hard timeout."""
    def _get() -> Any:
        stock = yf.Ticker(ticker)
        return stock.history(period="3mo")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get)
        try:
            return future.result(timeout=YFINANCE_TIMEOUT_S)
        except (FuturesTimeoutError, Exception) as exc:
            logger.warning("yfinance timeout/error for %s: %s", ticker, exc)
            return None


def compute_rsi(prices: np.ndarray, period: int = 14) -> float:
    """Compute RSI from a price series."""
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def analyze_ticker(ticker: str) -> dict:
    """Technical analysis for a single ticker."""
    try:
        hist = _fetch_ticker_history(ticker)
        if hist is None or hist.empty or len(hist) < 20:
            return {
                "ticker": ticker,
                "score": 5.0,
                "direction": "HOLD",
                "error": "Insufficient data",
            }

        closes = hist["Close"].values
        volumes = hist["Volume"].values
        current = float(closes[-1])

        # Moving averages
        sma_20 = float(np.mean(closes[-20:]))
        sma_50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else sma_20

        # RSI
        rsi = compute_rsi(closes)

        # Volume trend (last 5 days vs 20-day avg)
        vol_recent = float(np.mean(volumes[-5:]))
        vol_avg = float(np.mean(volumes[-20:]))
        vol_ratio = vol_recent / vol_avg if vol_avg > 0 else 1.0

        # Price vs MAs
        above_sma20 = current > sma_20
        above_sma50 = current > sma_50
        golden_cross = sma_20 > sma_50

        # --- Scoring ---
        score = 5.0

        # RSI signals
        if rsi < 30:
            score += 2.0  # oversold = potential bounce (CALL)
        elif rsi < 40:
            score += 1.0
        elif rsi > 70:
            score -= 2.0  # overbought = potential pullback (PUT)
        elif rsi > 60:
            score -= 0.5

        # Moving average signals
        if above_sma20 and above_sma50 and golden_cross:
            score += 1.5  # strong uptrend
        elif not above_sma20 and not above_sma50:
            score -= 1.5  # strong downtrend
        if golden_cross:
            score += 0.5

        # Volume confirmation
        if vol_ratio > 1.5 and above_sma20:
            score += 1.0  # high volume + uptrend = conviction
        elif vol_ratio > 1.5 and not above_sma20:
            score -= 1.0  # high volume + downtrend = selling pressure

        score = max(0.0, min(10.0, score))
        direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

        return {
            "ticker": ticker,
            "score": round(score, 1),
            "direction": direction,
            "price": round(current, 2),
            "rsi": rsi,
            "sma_20": round(sma_20, 2),
            "sma_50": round(sma_50, 2),
            "above_sma20": above_sma20,
            "above_sma50": above_sma50,
            "golden_cross": golden_cross,
            "volume_ratio": round(vol_ratio, 2),
        }
    except Exception as exc:
        logger.warning("Technical failed for %s: %s", ticker, exc)
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
    Run technical analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Optional agent configuration dict (reserved for future use,
                e.g. custom RSI period, SMA windows).

    Returns:
        A list of per-ticker result dicts sorted by score descending.
    """
    logger.info("Running Technical Agent on %d tickers…", len(watchlist))
    results = [analyze_ticker(t) for t in watchlist]
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Technical complete: %d tickers analysed", len(results))
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
        agent_id="technical",
        run_id=run_id,
        results=results,
    )
