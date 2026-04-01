from __future__ import annotations

"""
Congressional Trades Analysis Skill

Tracks politician stock disclosures via STOCK Act filings.
Primary source: Quiver Quantitative API. Fallback: Capitol Trades scrape.
Prioritises Trump inner circle and known active congressional traders.

Adapted from market-intel/agents/congress.py for the OpenClaw framework.

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 21.1, 21.4
"""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach shared_memory_io
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUIVER_BASE = "https://api.quiverquant.com/beta"
WEB_SCRAPE_TIMEOUT_S = 15
DAYS_BACK = 14
MAX_EXTRA_TICKERS = 5

# Priority politicians — Trump administration allies and known active traders
PRIORITY_POLITICIANS = [
    # Trump administration / close allies
    "Nancy Mace", "Marjorie Taylor Greene", "Matt Gaetz", "Jim Jordan",
    "Kevin McCarthy", "Steve Scalise", "Elise Stefanik", "Mike Johnson",
    "Tommy Tuberville", "Dan Crenshaw", "Michael McCaul",
    # Known active traders in Congress
    "Nancy Pelosi", "Dan Meuser", "Josh Gottheimer", "Ro Khanna",
    "Mark Green", "John Curtis", "French Hill", "Pat Fallon",
    "Brian Higgins", "Virginia Foxx",
]


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------

def _fetch_quiver_trades(days_back: int, api_key: str) -> list[dict]:
    """Fetch recent congressional trades from Quiver Quantitative API."""
    try:
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        resp = requests.get(
            f"{QUIVER_BASE}/live/congresstrading",
            headers=headers,
            timeout=WEB_SCRAPE_TIMEOUT_S,
        )
        if not resp.ok:
            logger.warning("Quiver API returned %s", resp.status_code)
            return []

        data = resp.json()
        cutoff = datetime.now() - timedelta(days=days_back)
        trades: list[dict] = []
        for trade in data:
            trade_date = trade.get("Date", "")
            if not trade_date:
                continue
            try:
                dt = datetime.strptime(trade_date, "%Y-%m-%d")
                if dt >= cutoff:
                    trades.append({
                        "politician": trade.get("Representative", ""),
                        "ticker": trade.get("Ticker", ""),
                        "transaction": trade.get("Transaction", ""),
                        "amount": trade.get("Amount", ""),
                        "date": trade_date,
                        "party": trade.get("Party", ""),
                        "chamber": trade.get("House", ""),
                    })
            except ValueError:
                continue
        return trades
    except Exception as exc:
        logger.warning("Quiver API failed: %s", exc)
        return []


def _extract_ticker_from_issuer(issuer_text: str) -> str:
    """Extract ticker symbol from Capitol Trades issuer column.

    The issuer column contains text like "Roper Technologies IncROP:US"
    or "NVIDIA CorpNVDA:US". We extract the ticker before the ":US" suffix.
    Returns empty string for non-public securities (e.g. "N/A").
    """
    import re
    # Match TICKER:US or TICKER:exchange pattern at end of string
    match = re.search(r"([A-Z]{1,5}):[A-Z]{2}\s*$", issuer_text)
    if match:
        return match.group(1)
    return ""


def _extract_politician_name(col_text: str) -> str:
    """Extract just the politician name from the mangled column text.

    Capitol Trades column 0 contains "Jared MoskowitzDemocratHouseFL".
    We grab the name from the first <a> tag instead.
    """
    return col_text  # Will be overridden with link text below


def _fetch_capitol_trades(days_back: int) -> list[dict]:
    """Fallback: scrape Capitol Trades for recent disclosures.

    Capitol Trades table columns (as of 2026):
      [0] Politician (name + party + chamber + state)
      [1] Issuer + ticker (e.g. "Roper Technologies IncROP:US")
      [2] Published date/time
      [3] Trade date
      [4] Reporting gap
      [5] Owner (Self/Spouse/Child)
      [6] Transaction type (buy/sell)
      [7] Amount range
      [8] Price
      [9] Detail link
    """
    try:
        resp = requests.get(
            "https://www.capitoltrades.com/trades?per_page=50&sort=-pubDate",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=WEB_SCRAPE_TIMEOUT_S,
        )
        if not resp.ok:
            logger.warning("Capitol Trades returned %s", resp.status_code)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        trades: list[dict] = []
        rows = soup.select("table tbody tr")
        for row in rows[:50]:
            cols = row.select("td")
            if len(cols) < 7:
                continue

            # Extract politician name from the <a> tag in col 0
            politician_link = cols[0].select_one("a")
            politician = politician_link.get_text(strip=True) if politician_link else cols[0].get_text(strip=True)

            # Extract ticker from issuer column (col 1)
            issuer_text = cols[1].get_text(strip=True)
            ticker = _extract_ticker_from_issuer(issuer_text)

            # Transaction type is in col 6
            transaction = cols[6].get_text(strip=True).lower()

            # Amount in col 7
            amount = cols[7].get_text(strip=True) if len(cols) > 7 else ""

            # Trade date in col 3
            trade_date = cols[3].get_text(strip=True)

            if not ticker:
                logger.debug("Skipping non-public security: %s", issuer_text[:40])
                continue

            trades.append({
                "politician": politician,
                "ticker": ticker,
                "transaction": transaction,
                "amount": amount,
                "date": trade_date,
                "party": "",
                "chamber": "",
            })

        logger.info("Capitol Trades scraped %d public stock trades", len(trades))
        return trades
    except Exception as exc:
        logger.warning("Capitol Trades scrape failed: %s", exc)
        return []


def fetch_recent_congress_trades(days_back: int, api_key: str = "") -> list[dict]:
    """
    Fetch recent congressional stock trades.

    Primary: Quiver Quantitative API.
    Fallback: Capitol Trades web scrape.
    """
    trades = _fetch_quiver_trades(days_back, api_key)
    if not trades:
        trades = _fetch_capitol_trades(days_back)
    return trades


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_congress_signal(ticker: str, trades: list[dict]) -> dict:
    """Score a ticker based on congressional trading activity."""
    score = 5.0
    relevant_trades = [
        t for t in trades
        if t.get("ticker", "").upper() == ticker.upper()
    ]

    if not relevant_trades:
        return {
            "ticker": ticker,
            "score": 5.0,
            "direction": "HOLD",
            "congress_buys": 0,
            "congress_sells": 0,
            "priority_signal": None,
            "congress_trades": [],
        }

    buy_count = 0
    sell_count = 0
    priority_signal = None

    for trade in relevant_trades:
        politician = trade.get("politician", "")
        tx = trade.get("transaction", "").lower()
        is_priority = any(
            p.lower() in politician.lower() for p in PRIORITY_POLITICIANS
        )

        if "purchase" in tx or "buy" in tx:
            buy_count += 1
            if is_priority:
                score += 2.0
                priority_signal = f"🏛️ {politician} BOUGHT"
            else:
                score += 0.5
        elif "sale" in tx or "sell" in tx:
            sell_count += 1
            if is_priority:
                score -= 2.0
                priority_signal = f"🏛️ {politician} SOLD"
            else:
                score -= 0.5

    score = max(0.0, min(10.0, score))
    direction = "CALL" if score >= 6 else "PUT" if score <= 4 else "HOLD"

    return {
        "ticker": ticker,
        "score": round(score, 1),
        "direction": direction,
        "congress_buys": buy_count,
        "congress_sells": sell_count,
        "priority_signal": priority_signal,
        "congress_trades": relevant_trades[:3],
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run(watchlist: list[str], config: dict | None = None) -> list[dict]:
    """
    Run congressional trades analysis on every ticker in *watchlist*.

    Args:
        watchlist: List of ticker symbols to analyse.
        config: Optional agent configuration dict. Recognised keys:
                - quiver_api_key (str): Quiver Quantitative API key.

    Returns:
        A list of per-ticker result dicts sorted by signal strength
        (distance from neutral 5.0, descending).
    """
    config = config or {}
    api_key = config.get("quiver_api_key", "")

    logger.info("Running Congressional Trades Agent on %d tickers…", len(watchlist))
    trades = fetch_recent_congress_trades(days_back=DAYS_BACK, api_key=api_key)
    logger.info("Found %d recent congressional trades", len(trades))

    # Score watchlist tickers
    results = [score_congress_signal(t, trades) for t in watchlist]

    # Flag extra tickers outside watchlist (up to MAX_EXTRA_TICKERS)
    watchlist_set = {t.upper() for t in watchlist}
    extra_tickers = {
        t["ticker"].upper()
        for t in trades
        if t.get("ticker")
    } - watchlist_set

    for ticker in list(extra_tickers)[:MAX_EXTRA_TICKERS]:
        result = score_congress_signal(ticker, trades)
        if result["score"] != 5.0:
            result["outside_watchlist"] = True
            results.append(result)

    # Sort by signal strength (distance from neutral 5.0)
    results.sort(key=lambda x: abs(x["score"] - 5.0), reverse=True)
    logger.info("Congress agent complete: %d tickers scored", len(results))
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
        agent_id="congress",
        run_id=run_id,
        results=results,
    )
