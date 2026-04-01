from __future__ import annotations

"""
Pre-Market Analysis Skill

Retrieves futures (ES, NQ, YM, RTY, crude, gold, VIX, DXY, 10Y),
global indices (Nikkei, Hang Seng, FTSE, DAX, Shanghai), and pre-market
gaps >1% for watchlist tickers.  Produces a 0-10 score per ticker with
CALL / PUT / HOLD direction based on market bias and individual gaps.

Adapted from market-intel/agents/premarket.py for the OpenClaw framework.

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 21.1, 21.4
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
# Futures tickers (Yahoo Finance)  — Req 9.1
# ---------------------------------------------------------------------------
FUTURES: dict[str, str] = {
    "ES=F": "S&P 500 Futures",
    "NQ=F": "Nasdaq Futures",
    "YM=F": "Dow Futures",
    "RTY=F": "Russell 2000 Futures",
    "CL=F": "Crude Oil",
    "GC=F": "Gold",
    "^VIX": "VIX",
    "DX-Y.NYB": "US Dollar Index",
    "^TNX": "10Y Treasury Yield",
}

# Global market indices — Req 9.2
GLOBAL_INDICES: dict[str, str] = {
    "^N225": "Nikkei 225 (Japan)",
    "^HSI": "Hang Seng (Hong Kong)",
    "^FTSE": "FTSE 100 (UK)",
    "^GDAXI": "DAX (Germany)",
    "^SSEC": "Shanghai Composite",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_history(symbol: str, period: str = "2d") -> Any:
    """Fetch yfinance history for *symbol* with a hard timeout."""
    def _get():
        return yf.Ticker(symbol).history(period=period)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get)
        try:
            return future.result(timeout=YFINANCE_TIMEOUT_S)
        except (FuturesTimeoutError, Exception) as exc:
            logger.warning("yfinance timeout/error for %s: %s", symbol, exc)
            return None


def _fetch_ticker_info(ticker: str) -> dict[str, Any]:
    """Fetch yfinance .info for *ticker* with a hard timeout."""
    def _get():
        return yf.Ticker(ticker).info or {}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get)
        try:
            return future.result(timeout=YFINANCE_TIMEOUT_S)
        except (FuturesTimeoutError, Exception) as exc:
            logger.warning("yfinance timeout/error for %s: %s", ticker, exc)
            return {}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def get_futures_snapshot() -> list[dict]:
    """Get current futures prices and overnight change.  (Req 9.1)"""
    results = []
    for symbol, name in FUTURES.items():
        try:
            hist = _fetch_history(symbol)
            if hist is None or len(hist) < 2:
                continue
            prev_close = hist["Close"].iloc[-2]
            current = hist["Close"].iloc[-1]
            change_pct = (current - prev_close) / prev_close * 100
            results.append({
                "symbol": symbol,
                "name": name,
                "price": round(float(current), 2),
                "change_pct": round(float(change_pct), 2),
                "signal": (
                    "bullish" if change_pct > 0.3
                    else "bearish" if change_pct < -0.3
                    else "flat"
                ),
            })
        except Exception as exc:
            logger.warning("Futures fetch failed for %s: %s", symbol, exc)
    return results


def get_global_markets() -> list[dict]:
    """Get overnight global market performance.  (Req 9.2)"""
    results = []
    for symbol, name in GLOBAL_INDICES.items():
        try:
            hist = _fetch_history(symbol)
            if hist is None or len(hist) < 2:
                continue
            prev = hist["Close"].iloc[-2]
            current = hist["Close"].iloc[-1]
            change_pct = (current - prev) / prev * 100
            results.append({
                "name": name,
                "change_pct": round(float(change_pct), 2),
                "signal": (
                    "bullish" if change_pct > 0.5
                    else "bearish" if change_pct < -0.5
                    else "flat"
                ),
            })
        except Exception as exc:
            logger.warning("Global index fetch failed for %s: %s", symbol, exc)
    return results


def get_premarket_movers(watchlist: list[str]) -> list[dict]:
    """Get pre-market price changes for watchlist stocks.  (Req 9.3)

    Returns tickers with pre-market gaps exceeding 1% from previous close.
    """
    movers = []
    for ticker_sym in watchlist:
        try:
            info = _fetch_ticker_info(ticker_sym)
            if not info:
                continue
            pre_price = info.get("preMarketPrice", 0)
            prev_close = (
                info.get("previousClose", 0)
                or info.get("regularMarketPreviousClose", 0)
            )
            if pre_price and prev_close and prev_close > 0:
                gap_pct = (pre_price - prev_close) / prev_close * 100
                if abs(gap_pct) > 1.0:  # only significant movers
                    movers.append({
                        "ticker": ticker_sym,
                        "prev_close": round(float(prev_close), 2),
                        "pre_market": round(float(pre_price), 2),
                        "gap_pct": round(float(gap_pct), 2),
                        "signal": "gap_up" if gap_pct > 0 else "gap_down",
                    })
        except Exception as exc:
            logger.warning("Pre-market info failed for %s: %s", ticker_sym, exc)
    movers.sort(key=lambda x: abs(x.get("gap_pct", 0)), reverse=True)
    return movers[:10]


# ---------------------------------------------------------------------------
# Market bias assessment  — Req 9.4, 9.5
# ---------------------------------------------------------------------------

def assess_market_bias(futures: list[dict]) -> str:
    """Determine overall market bias from futures data.

    - Bullish if avg S&P + Nasdaq futures change > +0.5%  (Req 9.4)
    - Bearish if VIX price > 25 (overrides)               (Req 9.5)
    - Otherwise neutral
    """
    sp_futures = next((f for f in futures if f["symbol"] == "ES=F"), None)
    nq_futures = next((f for f in futures if f["symbol"] == "NQ=F"), None)
    vix = next((f for f in futures if f["symbol"] == "^VIX"), None)

    bias = "neutral"
    if sp_futures and nq_futures:
        avg_change = (sp_futures["change_pct"] + nq_futures["change_pct"]) / 2
        if avg_change > 0.5:
            bias = "bullish"
        elif avg_change < -0.5:
            bias = "bearish"

    # VIX > 25 overrides to bearish (Req 9.5)
    if vix and vix["price"] > 25:
        bias = "bearish"

    return bias


def assess_premarket(watchlist: list[str]) -> dict:
    """Full pre-market assessment combining futures, global markets, and movers."""
    futures = get_futures_snapshot()
    global_mkts = get_global_markets()
    movers = get_premarket_movers(watchlist)
    bias = assess_market_bias(futures)

    return {
        "market_bias": bias,
        "futures": futures,
        "global_markets": global_mkts,
        "premarket_movers": movers,
    }


# ---------------------------------------------------------------------------
# Per-ticker scoring  — Req 9.6
# ---------------------------------------------------------------------------

def score_ticker(ticker: str, premarket_data: dict) -> dict:
    """Score a single ticker based on pre-market conditions.

    - +/-0.5 for market bias                          (Req 9.6)
    - Up to +/-2.0 for individual pre-market gaps     (Req 9.6)
    """
    score = 5.0
    reasons: list[str] = []

    # Market bias adjustment
    bias = premarket_data.get("market_bias", "neutral")
    if bias == "bullish":
        score += 0.5
        reasons.append("Futures bullish")
    elif bias == "bearish":
        score -= 0.5
        reasons.append("Futures bearish")

    # Individual pre-market gap adjustment
    for mover in premarket_data.get("premarket_movers", []):
        if mover["ticker"] == ticker:
            gap = mover["gap_pct"]
            if gap > 2:
                score += 2.0
                reasons.append(f"Pre-market gap up {gap:.1f}%")
            elif gap > 0:
                score += 1.0
                reasons.append(f"Pre-market up {gap:.1f}%")
            elif gap < -2:
                score -= 2.0
                reasons.append(f"Pre-market gap down {gap:.1f}%")
            elif gap < 0:
                score -= 1.0
                reasons.append(f"Pre-market down {gap:.1f}%")
            break

    score = max(0.0, min(10.0, score))
    direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

    return {
        "ticker": ticker,
        "score": round(score, 1),
        "direction": direction,
        "premarket_reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[str], config: dict | None = None) -> list[dict]:
    """
    Run pre-market analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Optional agent configuration dict (reserved for future use).

    Returns:
        A list of per-ticker result dicts sorted by score descending,
        with a trailing ``_premarket_summary`` entry containing the full
        pre-market assessment (futures, global markets, movers, bias).
    """
    logger.info("Running Pre-Market Agent on %d tickers…", len(watchlist))
    premarket_data = assess_premarket(watchlist)

    results = [score_ticker(t, premarket_data) for t in watchlist]

    # Attach summary for orchestrator consumption
    results.append({"_premarket_summary": premarket_data})

    results.sort(key=lambda x: x.get("score", 5), reverse=True)
    logger.info(
        "Pre-market complete: bias=%s, movers=%d",
        premarket_data["market_bias"],
        len(premarket_data["premarket_movers"]),
    )
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
        agent_id="premarket",
        run_id=run_id,
        results=results,
    )
