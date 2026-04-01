"""
Daily Movers Fetcher

Scans the S&P 500 universe via yfinance for the top 100 biggest movers
by absolute % change (minimum 5% threshold).  Merges discovered movers
into the shared watchlist under a "daily_movers" sector.

This module is optional — if yfinance is unavailable or the scan fails,
the system continues with the static watchlist.

Requirements: Dynamic watchlist expansion
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)

MIN_CHANGE_PCT = 5.0
MAX_MOVERS = 100

# ---------------------------------------------------------------------------
# S&P 500 universe (representative subset — full list would come from
# Wikipedia scrape or a maintained CSV; hardcoded here for reliability)
# ---------------------------------------------------------------------------

SP500_TICKERS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEE",
    "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM", "ALB", "ALGN", "ALK",
    "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP", "AMT", "AMZN",
    "ANET", "ANSS", "AON", "AOS", "APA", "APD", "APH", "APTV", "ARE", "ATO",
    "ATVI", "AVB", "AVGO", "AVY", "AWK", "AXP", "AZO", "BA", "BAC", "BAX",
    "BBWI", "BBY", "BDX", "BEN", "BF-B", "BIIB", "BIO", "BK", "BKNG", "BKR",
    "BLK", "BMY", "BR", "BRK-B", "BRO", "BSX", "BWA", "BXP", "C", "CAG",
    "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE", "CCI", "CCL", "CDAY", "CDNS",
    "CDW", "CE", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CINF",
    "CL", "CLX", "CMA", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP",
    "COF", "COO", "COP", "COST", "CPB", "CPRT", "CPT", "CRL", "CRM", "CSCO",
    "CSGP", "CSX", "CTAS", "CTLT", "CTRA", "CTSH", "CTVA", "CVS", "CVX", "CZR",
    "D", "DAL", "DD", "DE", "DFS", "DG", "DGX", "DHI", "DHR", "DIS",
    "DISH", "DLTR", "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN",
    "DXC", "DXCM", "EA", "EBAY", "ECL", "ED", "EFX", "EIX", "EL", "EMN",
    "EMR", "ENPH", "EOG", "EPAM", "EQIX", "EQR", "EQT", "ES", "ESS", "ETN",
    "ETR", "ETSY", "EVRG", "EW", "EXC", "EXPD", "EXPE", "EXR", "F", "FANG",
    "FAST", "FBHS", "FCX", "FDS", "FDX", "FE", "FFIV", "FIS", "FISV", "FITB",
    "FLT", "FMC", "FOX", "FOXA", "FRC", "FRT", "FSLR", "FTNT", "FTV", "GD",
    "GE", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC",
    "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HOLX",
    "HON", "HPE", "HPQ", "HRL", "HSIC", "HST", "HSY", "HUM", "HWM", "IBM",
    "ICE", "IDXX", "IEX", "IFF", "ILMN", "INCY", "INTC", "INTU", "INVH", "IP",
    "IPG", "IQV", "IR", "IRM", "ISRG", "IT", "ITW", "IVZ", "J", "JBHT",
    "JCI", "JKHY", "JNJ", "JNPR", "JPM", "K", "KDP", "KEY", "KEYS", "KHC",
    "KIM", "KLAC", "KMB", "KMI", "KMX", "KO", "KR", "L", "LDOS", "LEN",
    "LH", "LHX", "LIN", "LKQ", "LLY", "LMT", "LNC", "LNT", "LOW", "LRCX",
    "LUMN", "LUV", "LVS", "LW", "LYB", "LYV", "MA", "MAA", "MAR", "MAS",
    "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MET", "META", "MGM", "MHK",
    "MKC", "MKTX", "MLM", "MMC", "MMM", "MNST", "MO", "MOH", "MOS", "MPC",
    "MPWR", "MRK", "MRNA", "MRVL", "MS", "MSCI", "MSFT", "MSI", "MTB", "MTCH",
    "MTD", "MU", "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX", "NI", "NKE",
    "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVDA", "NVR", "NWL",
    "NWS", "NWSA", "NXPI", "O", "ODFL", "OGN", "OKE", "OMC", "ON", "ORCL",
    "ORLY", "OTIS", "OXY", "PARA", "PAYC", "PAYX", "PCAR", "PCG", "PEAK", "PEG",
    "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PKI", "PLD",
    "PLTR", "PM", "PNC", "PNR", "PNW", "POOL", "PPG", "PPL", "PRU", "PSA",
    "PSX", "PTC", "PVH", "PWR", "PXD", "PYPL", "QCOM", "QRVO", "RCL", "RE",
    "REG", "REGN", "RF", "RHI", "RJF", "RL", "RMD", "ROK", "ROL", "ROP",
    "ROST", "RSG", "RTX", "SBAC", "SBNY", "SBUX", "SCHW", "SEE", "SHW", "SIVB",
    "SJM", "SLB", "SNA", "SNPS", "SO", "SPG", "SPGI", "SRE", "STE", "STT",
    "STX", "STZ", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP", "TDG",
    "TDY", "TECH", "TEL", "TER", "TFC", "TFX", "TGT", "TMO", "TMUS", "TPR",
    "TRGP", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSN", "TT", "TTWO", "TXN",
    "TXT", "TYL", "UAL", "UDR", "UHS", "ULTA", "UNH", "UNP", "UPS", "URI",
    "USB", "V", "VFC", "VICI", "VLO", "VMC", "VNO", "VRSK", "VRSN", "VRTX",
    "VTR", "VTRS", "VZ", "WAB", "WAT", "WBA", "WBD", "WDC", "WEC", "WELL",
    "WFC", "WHR", "WM", "WMB", "WMT", "WRB", "WRK", "WST", "WTW", "WY",
    "WYNN", "XEL", "XOM", "XRAY", "XYL", "YUM", "ZBH", "ZBRA", "ZION", "ZTS",
]


# ---------------------------------------------------------------------------
# Core fetcher
# ---------------------------------------------------------------------------

def fetch_daily_movers() -> list[dict]:
    """
    Scan S&P 500 tickers for those with ≥5% absolute change from previous close.

    Returns a list of dicts sorted by absolute change descending:
        [{"ticker": "XYZ", "change_pct": 7.2, "direction": "up", "volume": 12345678}, ...]

    Returns an empty list on any failure (yfinance not installed, network error, etc.).
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not installed — skipping daily movers scan")
        return []

    try:
        tickers_str = " ".join(SP500_TICKERS)
        data = yf.download(
            tickers_str,
            period="2d",
            group_by="ticker",
            threads=True,
            progress=False,
        )

        if data is None or data.empty:
            logger.warning("yfinance returned no data for daily movers scan")
            return []

        movers: list[dict] = []

        for ticker in SP500_TICKERS:
            try:
                if len(SP500_TICKERS) == 1:
                    ticker_data = data
                else:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    ticker_data = data[ticker]

                if len(ticker_data) < 2:
                    continue

                prev_close = ticker_data["Close"].iloc[-2]
                current_close = ticker_data["Close"].iloc[-1]
                volume = ticker_data["Volume"].iloc[-1]

                if prev_close is None or current_close is None or prev_close == 0:
                    continue

                # Handle pandas scalar types
                prev_close = float(prev_close)
                current_close = float(current_close)
                volume = int(volume) if volume is not None else 0

                change_pct = ((current_close - prev_close) / prev_close) * 100

                if abs(change_pct) >= MIN_CHANGE_PCT:
                    movers.append({
                        "ticker": ticker,
                        "change_pct": round(change_pct, 2),
                        "direction": "up" if change_pct > 0 else "down",
                        "volume": volume,
                    })
            except Exception as exc:
                logger.debug("Skipping %s in movers scan: %s", ticker, exc)
                continue

        # Sort by absolute change descending, cap at MAX_MOVERS
        movers.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
        movers = movers[:MAX_MOVERS]

        logger.info(
            "Daily movers scan: %d tickers with ≥%.0f%% change",
            len(movers), MIN_CHANGE_PCT,
        )
        return movers

    except Exception as exc:
        logger.error("Daily movers scan failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Merge into watchlist
# ---------------------------------------------------------------------------

def fetch_and_merge_movers() -> list[dict]:
    """
    Fetch daily movers and merge them into the shared watchlist.

    Steps:
    1. Fetch movers via yfinance
    2. Load current watchlist from shared_memory_io
    3. Add new movers to all_tickers and sectors["daily_movers"]
    4. Save updated watchlist
    5. Return the movers list

    Returns an empty list if the scan fails (system continues with static watchlist).
    """
    import shared_memory_io

    movers = fetch_daily_movers()
    if not movers:
        return []

    try:
        watchlist = shared_memory_io.load_watchlist()
        all_tickers = set(watchlist.get("all_tickers", []))
        sectors = watchlist.get("sectors", {})

        mover_tickers = [m["ticker"] for m in movers]

        # Add to daily_movers sector
        sectors["daily_movers"] = mover_tickers

        # Add new tickers to all_tickers (dedup)
        for t in mover_tickers:
            all_tickers.add(t)

        watchlist["all_tickers"] = sorted(all_tickers)
        watchlist["sectors"] = sectors

        shared_memory_io.save_watchlist(watchlist)
        logger.info(
            "Merged %d daily movers into watchlist (%d total tickers)",
            len(mover_tickers), len(watchlist["all_tickers"]),
        )
    except Exception as exc:
        logger.error("Failed to merge movers into watchlist: %s", exc)

    return movers
