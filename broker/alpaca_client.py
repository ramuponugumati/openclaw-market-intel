"""
Alpaca Broker Client

Provides stock and options trading via the Alpaca API.
Supports paper (paper-api.alpaca.markets) and live (api.alpaca.markets) modes
controlled by the ALPACA_MODE environment variable (default: paper).

Adapted from market-intel/broker.py for the OpenClaw multi-agent system.

Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 21.1, 21.2, 21.4
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
REQUEST_TIMEOUT = 10  # seconds


class AlpacaClient:
    """Alpaca API client for stock and options trading."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self.mode = (mode or os.environ.get("ALPACA_MODE", "paper")).strip().lower()

        if self.mode not in ("paper", "live"):
            logger.warning("Invalid ALPACA_MODE '%s' — defaulting to paper.", self.mode)
            self.mode = "paper"

        self.base_url = LIVE_URL if self.mode == "live" else PAPER_URL
        self._headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Stock orders
    # ------------------------------------------------------------------

    def buy_stock(
        self, ticker: str, qty: int, limit_price: Optional[float] = None
    ) -> dict:
        """Place a buy order for stock shares.

        Uses a limit order when *limit_price* is provided, otherwise market.
        """
        order: dict = {
            "symbol": ticker.upper(),
            "qty": str(qty),
            "side": "buy",
            "type": "limit" if limit_price else "market",
            "time_in_force": "day",
        }
        if limit_price is not None:
            order["limit_price"] = str(round(limit_price, 2))
        return self._place_order(order)

    def sell_stock(
        self, ticker: str, qty: int, limit_price: Optional[float] = None
    ) -> dict:
        """Place a sell order for stock shares."""
        order: dict = {
            "symbol": ticker.upper(),
            "qty": str(qty),
            "side": "sell",
            "type": "limit" if limit_price else "market",
            "time_in_force": "day",
        }
        if limit_price is not None:
            order["limit_price"] = str(round(limit_price, 2))
        return self._place_order(order)

    # ------------------------------------------------------------------
    # Options orders
    # ------------------------------------------------------------------

    def buy_option(
        self,
        ticker: str,
        strike: float,
        expiry: str,
        direction: str,
        contracts: int = 1,
    ) -> dict:
        """Buy an option contract via Alpaca.

        Args:
            ticker: Underlying ticker symbol (e.g. "NVDA").
            strike: Strike price (e.g. 128.0).
            expiry: Expiry date as "YYYY-MM-DD" (e.g. "2026-04-04").
            direction: "call" or "put" (case-insensitive).
            contracts: Number of contracts to buy.

        The Alpaca options symbol is constructed as:
            TICKER + YYMMDD + C/P + 8-digit strike (strike × 1000, zero-padded)
        Example: NVDA260404C00128000
        """
        option_symbol = self._build_option_symbol(ticker, strike, expiry, direction)
        order: dict = {
            "symbol": option_symbol,
            "qty": str(contracts),
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
        }
        return self._place_order(order)

    # ------------------------------------------------------------------
    # Positions & account
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict]:
        """Retrieve all open positions from Alpaca."""
        try:
            resp = requests.get(
                f"{self.base_url}/v2/positions",
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.ok:
                positions = []
                for p in resp.json():
                    positions.append({
                        "symbol": p.get("symbol"),
                        "qty": int(p.get("qty", 0)),
                        "side": p.get("side"),
                        "avg_entry_price": float(p.get("avg_entry_price", 0)),
                        "current_price": float(p.get("current_price", 0)),
                        "market_value": float(p.get("market_value", 0)),
                        "unrealized_pl": float(p.get("unrealized_pl", 0)),
                        "unrealized_plpc": round(
                            float(p.get("unrealized_plpc", 0)) * 100, 2
                        ),
                    })
                return positions
            return self._error_response(resp)
        except Exception as exc:
            logger.error("Positions error: %s", exc)
            return {"success": False, "error": str(exc)}

    def get_account(self) -> dict:
        """Retrieve account info — cash, buying power, equity, daily P&L."""
        try:
            resp = requests.get(
                f"{self.base_url}/v2/account",
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.ok:
                acct = resp.json()
                equity = float(acct.get("equity", 0))
                last_equity = float(acct.get("last_equity", 0))
                return {
                    "cash": float(acct.get("cash", 0)),
                    "buying_power": float(acct.get("buying_power", 0)),
                    "portfolio_value": float(acct.get("portfolio_value", 0)),
                    "equity": equity,
                    "daily_pnl": round(equity - last_equity, 2),
                    "mode": self.mode,
                }
            return self._error_response(resp)
        except Exception as exc:
            logger.error("Account error: %s", exc)
            return {"success": False, "error": str(exc)}

    def close_all(self) -> dict:
        """Liquidate all open positions."""
        try:
            resp = requests.delete(
                f"{self.base_url}/v2/positions",
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.ok:
                logger.info("All positions closed.")
                return {"success": True, "message": "All positions closed."}
            return self._error_response(resp)
        except Exception as exc:
            logger.error("Close-all error: %s", exc)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _place_order(self, order: dict) -> dict:
        """Submit an order to the Alpaca Orders API."""
        try:
            resp = requests.post(
                f"{self.base_url}/v2/orders",
                headers=self._headers,
                json=order,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.ok:
                result = resp.json()
                logger.info(
                    "Order placed: %s %sx %s — %s",
                    result.get("side"),
                    result.get("qty"),
                    result.get("symbol"),
                    result.get("status"),
                )
                return {
                    "success": True,
                    "order_id": result.get("id"),
                    "status": result.get("status"),
                    "symbol": result.get("symbol"),
                    "side": result.get("side"),
                    "qty": result.get("qty"),
                    "type": result.get("type"),
                    "filled_avg_price": result.get("filled_avg_price"),
                }
            return self._error_response(resp)
        except Exception as exc:
            logger.error("Order error: %s", exc)
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _build_option_symbol(
        ticker: str, strike: float, expiry: str, direction: str
    ) -> str:
        """Construct the Alpaca options symbol.

        Format: TICKER + YYMMDD + C/P + 8-digit strike (strike × 1000).
        Example: NVDA260404C00128000
        """
        # YYMMDD from YYYY-MM-DD
        exp_fmt = expiry.replace("-", "")[2:]  # e.g. "20260404" → "260404"
        cp = "C" if direction.upper() in ("CALL", "C") else "P"
        strike_fmt = f"{int(strike * 1000):08d}"
        return f"{ticker.upper()}{exp_fmt}{cp}{strike_fmt}"

    @staticmethod
    def _error_response(resp: requests.Response) -> dict:
        """Build a structured error dict from a failed HTTP response."""
        try:
            body = resp.json()
            message = body.get("message", resp.text)
        except Exception:
            message = resp.text
        logger.error("Alpaca API error %s: %s", resp.status_code, message)
        return {
            "success": False,
            "status_code": resp.status_code,
            "error": message,
        }
