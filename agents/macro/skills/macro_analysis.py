from __future__ import annotations

"""
Macro/Fed Analysis Skill

Retrieves macroeconomic indicators (10Y yield, 2Y yield, CPI, unemployment,
Fed funds rate, VIX) from the FRED API and applies sector-specific scoring
adjustments.  Produces a 0-10 score per ticker with CALL / PUT / HOLD direction.

Adapted from market-intel/agents/macro.py for the OpenClaw framework.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 21.1, 21.4
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

logger = logging.getLogger(__name__)

FRED_TIMEOUT_S = 10

# FRED series IDs for each macro indicator
INDICATORS: dict[str, str] = {
    "10Y_YIELD": "DGS10",
    "2Y_YIELD": "DGS2",
    "CPI_YOY": "CPIAUCSL",
    "UNEMPLOYMENT": "UNRATE",
    "FED_FUNDS": "FEDFUNDS",
    "VIX": "VIXCLS",
}

# Sector-to-ticker mapping for macro adjustments
SECTOR_MAP: dict[str, list[str]] = {
    "tech": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD", "CRM",
        "ORCL", "PLTR", "AVGO",
    ],
    "consumer": ["AMZN", "TSLA", "NFLX"],
    "fintech": ["COIN", "SOFI"],
    "etf": ["SPY", "QQQ", "IWM", "DIA", "ARKK"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_fred_api_key(config: dict | None) -> str:
    """Extract the FRED API key from *config* or the environment."""
    if config and config.get("fred_api_key"):
        return config["fred_api_key"]
    import os
    return os.environ.get("FRED_API_KEY", "")



def fetch_fred_series(
    series_id: str, api_key: str, limit: int = 5
) -> list[dict[str, Any]]:
    """
    Fetch recent observations from FRED for *series_id*.

    Handles stale data (value == ".") by skipping to the last valid
    observation.  Returns an empty list on any network/API failure.
    """
    try:
        resp = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series_id,
                "api_key": api_key,
                "sort_order": "desc",
                "limit": limit,
                "file_type": "json",
            },
            timeout=FRED_TIMEOUT_S,
        )
        if resp.ok:
            return resp.json().get("observations", [])
    except Exception as exc:
        logger.warning("FRED fetch failed for %s: %s", series_id, exc)
    return []


def _parse_valid_value(observations: list[dict], index: int = 0) -> float | None:
    """
    Return the first valid numeric value starting at *index*.

    FRED marks stale/missing data with ``"."``.  This helper walks forward
    through the list until it finds a usable number.  Returns ``None`` if
    no valid value is found.
    """
    for obs in observations[index:]:
        raw = obs.get("value", ".")
        if raw != ".":
            try:
                return float(raw)
            except (ValueError, TypeError):
                continue
    return None


def assess_environment(api_key: str) -> dict[str, Any]:
    """
    Assess the current macro environment by fetching all FRED indicators
    and deriving sector-level signals.

    Returns a dict with keys ``indicators`` and ``sector_signals``.
    """
    data: dict[str, dict[str, float]] = {}

    for name, series_id in INDICATORS.items():
        obs = fetch_fred_series(series_id, api_key, limit=5)
        if obs:
            current = _parse_valid_value(obs, 0)
            previous = _parse_valid_value(obs, 1)

            if current is None:
                # All observations stale — log and skip
                logger.warning(
                    "FRED series %s (%s): all observations stale, skipping",
                    name, series_id,
                )
                continue

            if previous is None:
                previous = current  # no prior valid value available

            # Log if we had to skip stale entries
            if obs[0].get("value", ".") == ".":
                logger.warning(
                    "FRED series %s (%s): latest observation stale, "
                    "using last valid value %.4f",
                    name, series_id, current,
                )

            data[name] = {
                "current": current,
                "previous": previous,
                "change": current - previous,
            }

    # --- Derive sector signals ---
    sector_signals: dict[str, dict[str, str]] = {}
    yield_10y = data.get("10Y_YIELD", {})
    vix = data.get("VIX", {})

    # Rising yields → bearish tech & fintech
    yield_change = yield_10y.get("change", 0)
    if yield_change > 0.05:
        sector_signals["tech"] = {
            "bias": "bearish",
            "reason": "Rising 10Y yields pressure growth stocks",
        }
        sector_signals["fintech"] = {
            "bias": "bearish",
            "reason": "Higher rates hurt fintech valuations",
        }
    elif yield_change < -0.05:
        sector_signals["tech"] = {
            "bias": "bullish",
            "reason": "Falling yields support growth stocks",
        }
        sector_signals["fintech"] = {
            "bias": "bullish",
            "reason": "Lower rates boost fintech",
        }

    # High VIX → bearish ETFs
    vix_current = vix.get("current", 0)
    if vix_current > 25:
        sector_signals["etf"] = {
            "bias": "bearish",
            "reason": f"VIX elevated at {vix_current:.1f} — fear in market",
        }
    elif vix_current < 15:
        sector_signals["etf"] = {
            "bias": "bullish",
            "reason": f"VIX low at {vix_current:.1f} — complacency/calm",
        }

    return {"indicators": data, "sector_signals": sector_signals}


def score_ticker(ticker: str, env: dict[str, Any]) -> dict:
    """
    Score a single ticker based on the macro environment.

    Applies sector-specific adjustments of ±1.5 when the ticker belongs
    to a sector with an active signal.
    """
    score = 5.0
    reasons: list[str] = []
    sector_signals = env.get("sector_signals", {})

    for sector, tickers in SECTOR_MAP.items():
        if ticker in tickers and sector in sector_signals:
            signal = sector_signals[sector]
            if signal["bias"] == "bullish":
                score += 1.5
            elif signal["bias"] == "bearish":
                score -= 1.5
            reasons.append(signal["reason"])

    score = max(0.0, min(10.0, score))
    direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

    # Summarise indicator snapshot for the result
    indicators = env.get("indicators", {})
    return {
        "ticker": ticker,
        "score": round(score, 1),
        "direction": direction,
        "macro_reasons": reasons,
        "yield_10y": indicators.get("10Y_YIELD", {}).get("current"),
        "yield_2y": indicators.get("2Y_YIELD", {}).get("current"),
        "vix": indicators.get("VIX", {}).get("current"),
        "fed_funds": indicators.get("FED_FUNDS", {}).get("current"),
        "cpi": indicators.get("CPI_YOY", {}).get("current"),
        "unemployment": indicators.get("UNEMPLOYMENT", {}).get("current"),
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[str], config: dict | None = None) -> list[dict]:
    """
    Run macro/Fed analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Optional agent configuration dict.  May contain
                ``fred_api_key`` for FRED API authentication.

    Returns:
        A list of per-ticker result dicts sorted by score descending.
    """
    api_key = _get_fred_api_key(config)
    if not api_key:
        logger.error("No FRED API key available — returning neutral scores")
        return [
            {
                "ticker": t,
                "score": 5.0,
                "direction": "HOLD",
                "macro_reasons": [],
                "error": "missing_api_key",
            }
            for t in watchlist
        ]

    logger.info("Running Macro Agent on %d tickers…", len(watchlist))
    env = assess_environment(api_key)
    results = [score_ticker(t, env) for t in watchlist]
    results.sort(key=lambda x: x["score"], reverse=True)
    logger.info("Macro complete: %d tickers scored", len(results))
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
        agent_id="macro",
        run_id=run_id,
        results=results,
    )
