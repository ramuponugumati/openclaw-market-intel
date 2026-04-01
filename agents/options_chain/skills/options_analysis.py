from __future__ import annotations

"""
Options Chain Analysis Skill

Retrieves option chains from yfinance for each ticker/direction pair,
filters by affordability (≤$300 per contract), and ranks by a composite
score of moneyness, open interest, volume, and bid-ask spread tightness.

Adapted from market-intel/agents/options_chain.py for the OpenClaw framework.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 21.1, 21.4
"""

import logging
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime
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
MAX_PREMIUM_PER_CONTRACT = 300  # $300 max per contract (fits 3 trades in $1K)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_option_chain(ticker: str, expiry: str) -> Any:
    """Fetch yfinance option chain for *ticker* at *expiry* with a hard timeout."""
    def _get():
        return yf.Ticker(ticker).option_chain(expiry)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get)
        try:
            return future.result(timeout=YFINANCE_TIMEOUT_S)
        except (FuturesTimeoutError, Exception) as exc:
            logger.warning("yfinance option_chain timeout/error for %s: %s", ticker, exc)
            return None


def _fetch_ticker_data(ticker: str) -> dict[str, Any]:
    """Fetch current price and available expirations with a hard timeout."""
    def _get():
        t = yf.Ticker(ticker)
        info = t.info or {}
        current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
        expirations = list(t.options) if t.options else []
        return {"current_price": current_price, "expirations": expirations}

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get)
        try:
            return future.result(timeout=YFINANCE_TIMEOUT_S)
        except (FuturesTimeoutError, Exception) as exc:
            logger.warning("yfinance ticker data timeout/error for %s: %s", ticker, exc)
            return {"current_price": 0, "expirations": []}


def _find_target_expiry(expirations: list[str]) -> str | None:
    """Pick the nearest expiry within 1-7 days; fall back to nearest available."""
    today = datetime.now().date()
    for exp_str in expirations:
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        days_out = (exp_date - today).days
        if 1 <= days_out <= 7:
            return exp_str

    # Fallback to nearest available
    if expirations:
        return expirations[0]
    return None


def _rank_contracts(options_df, current_price: float) -> Any:
    """
    Filter and rank option contracts by composite score.

    Composite: moneyness 30%, open interest 25%, volume 25%, bid-ask spread 20%.
    Filter: contract_cost ≤ $300.
    Fallback: 5 cheapest if none affordable.
    """
    if options_df.empty:
        return options_df

    df = options_df.copy()
    df["midPrice"] = (df["bid"] + df["ask"]) / 2
    df["contractCost"] = df["midPrice"] * 100  # per contract

    # Filter affordable contracts
    affordable = df[df["contractCost"] <= MAX_PREMIUM_PER_CONTRACT]
    if affordable.empty:
        affordable = df.nsmallest(5, "contractCost")
        affordable = affordable.copy()
        affordable["over_budget"] = True
    else:
        affordable = affordable.copy()
        affordable["over_budget"] = False

    # Scoring components
    affordable["moneyness"] = abs(affordable["strike"] - current_price) / max(current_price, 0.01)
    affordable["spread_pct"] = (
        (affordable["ask"] - affordable["bid"]) / affordable["ask"].clip(lower=0.01)
    )
    affordable["oi_score"] = affordable["openInterest"].fillna(0)
    affordable["vol_score"] = affordable["volume"].fillna(0)

    # Composite: low moneyness + high OI + high volume + tight spread
    affordable["rank_score"] = (
        (1 - affordable["moneyness"]) * 30
        + affordable["oi_score"].clip(upper=10000) / 10000 * 25
        + affordable["vol_score"].clip(upper=5000) / 5000 * 25
        + (1 - affordable["spread_pct"].clip(upper=1)) * 20
    )

    return affordable


def get_best_option(ticker: str, direction: str) -> dict:
    """
    Find the best option contract for a given ticker and direction.

    Args:
        ticker: Stock ticker symbol.
        direction: "CALL" or "PUT".

    Returns:
        Dict with contract details, or empty dict on failure.
    """
    try:
        data = _fetch_ticker_data(ticker)
        current_price = data["current_price"]
        expirations = data["expirations"]

        if not current_price:
            return {}
        if not expirations:
            return {}

        target_expiry = _find_target_expiry(expirations)
        if not target_expiry:
            return {}

        chain = _fetch_option_chain(ticker, target_expiry)
        if chain is None:
            return {}

        options = chain.calls if direction == "CALL" else chain.puts
        if options.empty:
            return {}

        ranked = _rank_contracts(options, current_price)
        if ranked.empty:
            return {}

        best = ranked.nlargest(1, "rank_score").iloc[0]

        return {
            "ticker": ticker,
            "direction": direction,
            "strike": float(best["strike"]),
            "expiry": target_expiry,
            "bid": float(best["bid"]),
            "ask": float(best["ask"]),
            "mid_price": round(float(best["midPrice"]), 2),
            "contract_cost": round(float(best["contractCost"]), 2),
            "volume": int(best["volume"]) if best["volume"] == best["volume"] else 0,
            "open_interest": int(best["openInterest"]) if best["openInterest"] == best["openInterest"] else 0,
            "implied_vol": round(float(best["impliedVolatility"]), 2) if "impliedVolatility" in best.index else 0,
            "current_price": round(current_price, 2),
            "over_budget": bool(best.get("over_budget", False)),
        }
    except Exception as e:
        logger.warning("Options chain failed for %s: %s", ticker, e)
        return {}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[dict], config: dict | None = None) -> list[dict]:
    """
    Run options chain analysis on a list of picks.

    Args:
        watchlist: List of dicts, each with at minimum 'ticker' and 'direction'
                   (CALL or PUT). Typically the top picks from the orchestrator.
        config: Optional agent configuration dict (reserved for future use).

    Returns:
        A list of per-pick result dicts with option contract details.
    """
    logger.info("Running Options Chain Agent on %d picks…", len(watchlist))
    results = []
    for pick in watchlist:
        ticker = pick.get("ticker", "")
        direction = pick.get("direction", "")
        if direction not in ("CALL", "PUT"):
            continue
        option = get_best_option(ticker, direction)
        if option:
            results.append(option)
        else:
            results.append({
                "ticker": ticker,
                "direction": direction,
                "error": "No suitable contract found",
            })
    logger.info("Options chain complete: %d picks processed", len(results))
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
        agent_id="options_chain",
        run_id=run_id,
        results=results,
    )
