"""
Pick Selector Skill

Selects the Top 5 options plays (3 CALL + 2 PUT) and Top 10 stock trades
(excluding ETFs) from the combined composite scores.  After selection,
invokes the options_chain agent to enrich top options picks with specific
contracts.

Requirements: 11.5, 11.6, 17.4
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach the options agent
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ETF tickers excluded from stock picks (Requirement 17.4)
ETF_TICKERS = frozenset({"SPY", "QQQ", "IWM", "DIA", "ARKK"})


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def select_options(combined: list[dict]) -> list[dict]:
    """
    Select the Top 5 options plays: 3 strongest CALL + 2 strongest PUT.

    Picks are ranked by composite score distance from neutral 5.0
    (strongest signals first).  (Requirement 11.5)

    Args:
        combined: The sorted list returned by
            :func:`score_combiner.combine`.

    Returns:
        A list of up to 5 dicts, each containing the combined ticker data
        plus a ``pick_rank`` key (1-based).
    """
    calls = [
        t for t in combined if t.get("direction") == "CALL"
    ]
    puts = [
        t for t in combined if t.get("direction") == "PUT"
    ]

    # Already sorted by distance from 5.0 (strongest first) from combine()
    top_calls = calls[:3]
    top_puts = puts[:2]

    picks = top_calls + top_puts
    # Re-sort the final 5 by distance from 5.0
    picks.sort(key=lambda x: abs(x["composite_score"] - 5.0), reverse=True)

    for i, pick in enumerate(picks, start=1):
        pick["pick_rank"] = i

    logger.info(
        "Selected %d options picks (%d CALL, %d PUT)",
        len(picks),
        len(top_calls),
        len(top_puts),
    )
    return picks


def select_stocks(combined: list[dict]) -> list[dict]:
    """
    Select the Top 10 stock trades, excluding ETFs.

    Ranked by composite score distance from neutral 5.0.  Each pick is
    assigned a trade action:
    - BUY   if composite_score ≥ 6
    - SELL/SHORT if composite_score ≤ 4
    - WATCH if 4 < composite_score < 6

    (Requirements 11.6, 17.4)

    Args:
        combined: The sorted list returned by
            :func:`score_combiner.combine`.

    Returns:
        A list of up to 10 dicts, each containing the combined ticker data
        plus ``action`` and ``pick_rank`` keys.
    """
    non_etf = [
        t for t in combined if t.get("ticker", "") not in ETF_TICKERS
    ]

    # Already sorted by distance from 5.0 from combine()
    top_10 = non_etf[:10]

    for i, pick in enumerate(top_10, start=1):
        score = pick.get("composite_score", 5.0)
        if score >= 6:
            pick["action"] = "BUY"
        elif score <= 4:
            pick["action"] = "SELL/SHORT"
        else:
            pick["action"] = "WATCH"
        pick["pick_rank"] = i

    logger.info("Selected %d stock picks (ETFs excluded)", len(top_10))
    return top_10


def enrich_options_picks(picks: list[dict]) -> list[dict]:
    """
    Invoke the options_chain agent to attach specific contract details
    to each options pick.

    Args:
        picks: The list returned by :func:`select_options`.

    Returns:
        The same list with an ``option_contract`` key added to each pick
        containing the best contract details (or an error dict).
    """
    try:
        from agents.options_chain.skills.options_analysis import get_best_option
    except ImportError:
        logger.error("Could not import options_analysis — skipping enrichment")
        return picks

    for pick in picks:
        ticker = pick.get("ticker", "")
        direction = pick.get("direction", "")
        if not ticker or direction not in ("CALL", "PUT"):
            continue

        contract = get_best_option(ticker, direction)
        pick["option_contract"] = contract
        if contract and not contract.get("error"):
            logger.info(
                "Enriched %s %s: strike=%s expiry=%s mid=$%s",
                ticker,
                direction,
                contract.get("strike"),
                contract.get("expiry"),
                contract.get("mid_price"),
            )
        else:
            logger.warning("No contract found for %s %s", ticker, direction)

    return picks
