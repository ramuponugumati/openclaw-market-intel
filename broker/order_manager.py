"""
Order Manager — Confirmation Flow and Trade History

Provides a confirmation-based order flow for Telegram trade commands:
1. Display order details (ticker, qty, direction, estimated cost)
2. Wait for user confirmation
3. Execute via AlpacaClient
4. Log trade to shared_memory/picks/trades_history.json
5. Relay rejections with reason and suggested corrective action

Requirements: 14.2, 14.7, 16.3, 16.4, 21.2
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _get_shared_memory_base() -> Path:
    """Return the shared memory base path."""
    import os
    env_path = os.environ.get("SHARED_MEMORY_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parents[1] / "shared_memory"


def _trades_history_path() -> Path:
    """Return the path to trades_history.json."""
    return _get_shared_memory_base() / "picks" / "trades_history.json"


# ------------------------------------------------------------------
# Trade history I/O
# ------------------------------------------------------------------

def _load_trades_history() -> list[dict]:
    """Load the trades history list from JSON. Returns [] if missing."""
    path = _trades_history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_trades_history(trades: list[dict]) -> None:
    """Persist the trades history list to JSON."""
    path = _trades_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(trades, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------------
# Confirmation message builders
# ------------------------------------------------------------------

def format_buy_confirmation(
    ticker: str,
    qty: int,
    estimated_price: Optional[float] = None,
    limit_price: Optional[float] = None,
) -> str:
    """Build a confirmation prompt for a stock buy order."""
    price_str = f"${estimated_price:.2f}" if estimated_price else "market"
    cost_str = (
        f"${estimated_price * qty:.2f}" if estimated_price else "at market price"
    )
    order_type = "Limit" if limit_price else "Market"
    return (
        "📝 *Order Confirmation*\n\n"
        f"Action: BUY\n"
        f"Ticker: {ticker}\n"
        f"Quantity: {qty}\n"
        f"Order Type: {order_type}\n"
        f"Est. Price: {price_str}\n"
        f"Est. Cost: {cost_str}\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    )


def format_sell_confirmation(
    ticker: str,
    qty: int,
    estimated_price: Optional[float] = None,
    limit_price: Optional[float] = None,
) -> str:
    """Build a confirmation prompt for a stock sell order."""
    price_str = f"${estimated_price:.2f}" if estimated_price else "market"
    proceeds_str = (
        f"${estimated_price * qty:.2f}" if estimated_price else "at market price"
    )
    order_type = "Limit" if limit_price else "Market"
    return (
        "📝 *Order Confirmation*\n\n"
        f"Action: SELL\n"
        f"Ticker: {ticker}\n"
        f"Quantity: {qty}\n"
        f"Order Type: {order_type}\n"
        f"Est. Price: {price_str}\n"
        f"Est. Proceeds: {proceeds_str}\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    )


def format_option_confirmation(
    ticker: str,
    strike: float,
    expiry: str,
    direction: str,
    contracts: int = 1,
    premium: Optional[float] = None,
) -> str:
    """Build a confirmation prompt for an option buy order."""
    cost_str = (
        f"${premium * 100 * contracts:.2f}" if premium else "at market price"
    )
    return (
        "📝 *Option Order Confirmation*\n\n"
        f"Action: BUY {direction.upper()}\n"
        f"Ticker: {ticker}\n"
        f"Strike: ${strike:.2f}\n"
        f"Expiry: {expiry}\n"
        f"Contracts: {contracts}\n"
        f"Est. Cost: {cost_str}\n\n"
        "Reply *yes* to confirm or *no* to cancel."
    )


def format_close_all_confirmation() -> str:
    """Build a confirmation prompt for closing all positions."""
    return (
        "⚠️ *Close All Positions*\n\n"
        "This will liquidate ALL open positions immediately.\n"
        "Are you sure? Reply *yes* to confirm or *no* to cancel."
    )


# ------------------------------------------------------------------
# Order execution with logging
# ------------------------------------------------------------------

def execute_buy(
    client,  # AlpacaClient
    ticker: str,
    qty: int,
    limit_price: Optional[float] = None,
) -> dict:
    """Execute a stock buy and log the trade."""
    result = client.buy_stock(ticker, qty, limit_price)
    if result.get("success"):
        _log_trade(
            ticker=ticker,
            action="BUY",
            qty=qty,
            price=limit_price,
            order_result=result,
        )
        return result
    return _handle_rejection(result)


def execute_sell(
    client,  # AlpacaClient
    ticker: str,
    qty: int,
    limit_price: Optional[float] = None,
) -> dict:
    """Execute a stock sell and log the trade."""
    result = client.sell_stock(ticker, qty, limit_price)
    if result.get("success"):
        _log_trade(
            ticker=ticker,
            action="SELL",
            qty=qty,
            price=limit_price,
            order_result=result,
        )
        return result
    return _handle_rejection(result)


def execute_option_buy(
    client,  # AlpacaClient
    ticker: str,
    strike: float,
    expiry: str,
    direction: str,
    contracts: int = 1,
) -> dict:
    """Execute an option buy and log the trade."""
    result = client.buy_option(ticker, strike, expiry, direction, contracts)
    if result.get("success"):
        _log_trade(
            ticker=ticker,
            action=f"BUY_{direction.upper()}",
            qty=contracts,
            price=None,
            order_result=result,
            option_details={
                "strike": strike,
                "expiry": expiry,
                "direction": direction.upper(),
                "contracts": contracts,
            },
        )
        return result
    return _handle_rejection(result)


def execute_close_all(client) -> dict:
    """Close all positions and log the action."""
    result = client.close_all()
    if result.get("success"):
        _log_trade(
            ticker="ALL",
            action="CLOSE_ALL",
            qty=0,
            price=None,
            order_result=result,
        )
    return result


# ------------------------------------------------------------------
# Trade record updates (close / P&L)
# ------------------------------------------------------------------

def update_trade_close(
    order_id: str,
    close_price: float,
    realized_pnl: float,
) -> bool:
    """Update an existing trade record with close details.

    Finds the trade by order_id and appends close_price, close_timestamp,
    and realized_pnl.

    Returns True if the trade was found and updated.
    """
    trades = _load_trades_history()
    for trade in reversed(trades):
        if trade.get("order_id") == order_id:
            trade["close_price"] = close_price
            trade["close_timestamp"] = datetime.now(timezone.utc).isoformat()
            trade["realized_pnl"] = round(realized_pnl, 2)
            _save_trades_history(trades)
            logger.info(
                "Trade %s closed: price=%.2f pnl=%.2f",
                order_id, close_price, realized_pnl,
            )
            return True
    logger.warning("Trade %s not found in history for close update.", order_id)
    return False


# ------------------------------------------------------------------
# Rejection handling
# ------------------------------------------------------------------

def _handle_rejection(result: dict) -> dict:
    """Enrich a failed order result with a user-friendly message and suggestion."""
    error = result.get("error", "Unknown error")
    status_code = result.get("status_code", 0)
    suggestion = _suggest_corrective_action(error, status_code)
    result["user_message"] = f"❌ Order rejected: {error}"
    result["suggestion"] = suggestion
    logger.warning("Order rejected (%s): %s", status_code, error)
    return result


def _suggest_corrective_action(error: str, status_code: int) -> str:
    """Return a suggested corrective action based on the error."""
    error_lower = error.lower() if error else ""

    if "insufficient" in error_lower or "buying power" in error_lower:
        return "💡 Reduce quantity or add funds to your account."
    if "not found" in error_lower or "symbol" in error_lower:
        return "💡 Check the ticker symbol — it may be invalid or delisted."
    if status_code == 403:
        return "💡 Check your API keys and account permissions."
    if status_code == 429:
        return "💡 Rate limit hit — wait a moment and try again."
    if "market" in error_lower and "closed" in error_lower:
        return "💡 Market is closed. Try again during trading hours (9:30 AM – 4:00 PM ET)."
    if "duplicate" in error_lower:
        return "💡 A similar order may already be pending. Check /positions."
    return "💡 Review the error and try again, or check /account for details."


def format_rejection_message(result: dict) -> str:
    """Format a rejection result into a Telegram-friendly message."""
    msg = result.get("user_message", "❌ Order failed.")
    suggestion = result.get("suggestion", "")
    if suggestion:
        msg += f"\n{suggestion}"
    return msg


# ------------------------------------------------------------------
# Internal trade logging
# ------------------------------------------------------------------

def _log_trade(
    ticker: str,
    action: str,
    qty: int,
    price: Optional[float],
    order_result: dict,
    option_details: Optional[dict] = None,
) -> None:
    """Append a trade record to trades_history.json."""
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "date": now.strftime("%Y-%m-%d"),
        "timestamp": now.isoformat(),
        "ticker": ticker,
        "action": action,
        "qty": qty,
        "price": price,
        "total_cost": round(price * qty, 2) if price else None,
        "order_id": order_result.get("order_id"),
        "order_status": order_result.get("status"),
        "filled_avg_price": order_result.get("filled_avg_price"),
    }
    if option_details:
        record["option_details"] = option_details

    trades = _load_trades_history()
    trades.append(record)
    _save_trades_history(trades)
    logger.info("Trade logged: %s %s %s qty=%s", action, ticker, record["date"], qty)
