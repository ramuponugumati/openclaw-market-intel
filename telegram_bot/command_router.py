"""
Command Router

Routes Telegram commands to the appropriate handler functions.
Core commands: /start, /help, /picks, /analyze, /congress
Trade commands: /buy, /sell, /positions, /account, /close_all
Watchlist commands: /add, /remove

Requirements: 12.2, 12.4, 12.7, 12.8
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Help / welcome text
# ---------------------------------------------------------------------------

WELCOME_TEXT = (
    "🦀 *OpenClaw Market Intel Bot*\n\n"
    "Welcome! I'm your AI-powered market intelligence assistant.\n"
    "I analyze 35 tickers across 8 dimensions and deliver actionable picks.\n\n"
    "Use /help to see all available commands."
)

HELP_TEXT = (
    "📋 *Available Commands*\n\n"
    "🔍 *Analysis*\n"
    "/picks — Trigger morning analysis\n"
    "/analyze TICKER — Deep analysis for a single ticker\n"
    "/congress — Recent congressional trade disclosures\n\n"
    "💰 *Trading*\n"
    "/buy TICKER QTY — Buy stock\n"
    "/buy N — Buy pick #N from morning picks\n"
    "/sell TICKER QTY — Sell stock\n"
    "/positions — Show open positions with P&L\n"
    "/account — Account balance and buying power\n"
    "/close\\_all — Close all open positions\n"
    "/pnl — Today's P&L summary\n\n"
    "📝 *Watchlist*\n"
    "/add TICKER — Add ticker to watchlist\n"
    "/remove TICKER — Remove ticker from watchlist\n\n"
    "ℹ️ /start — Welcome message\n"
    "/help — This command list"
)


# ---------------------------------------------------------------------------
# Broker stubs — broker/ will be implemented in task 9
# ---------------------------------------------------------------------------

def _get_broker():
    """Lazy import of broker client. Returns None if credentials are missing."""
    try:
        from broker.alpaca_client import AlpacaClient
        client = AlpacaClient()
        # Only return a usable client when credentials are actually configured
        if not client.api_key or not client.secret_key:
            logger.debug("Broker credentials not configured.")
            return None
        return client
    except (ImportError, Exception) as exc:
        logger.debug("Broker not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Stub broker functions used until task 9 is complete
# ---------------------------------------------------------------------------

def _stub_buy(ticker: str, qty: int) -> dict:
    return {
        "status": "stub",
        "message": f"🔧 Broker not yet implemented. Would buy {qty} shares of {ticker}.",
    }


def _stub_sell(ticker: str, qty: int) -> dict:
    return {
        "status": "stub",
        "message": f"🔧 Broker not yet implemented. Would sell {qty} shares of {ticker}.",
    }


def _stub_positions() -> list[dict]:
    return []


def _stub_account() -> dict:
    return {
        "cash": "N/A",
        "buying_power": "N/A",
        "portfolio_value": "N/A",
        "equity": "N/A",
        "daily_pnl": "N/A",
    }


def _stub_close_all() -> dict:
    return {"status": "stub", "message": "🔧 Broker not yet implemented."}


# ---------------------------------------------------------------------------
# Morning picks cache (populated by /picks, used by /buy N)
# ---------------------------------------------------------------------------

_last_picks: dict[str, Any] = {
    "options": [],
    "stocks": [],
    "timestamp": None,
}


# ---------------------------------------------------------------------------
# Command Router
# ---------------------------------------------------------------------------

class CommandRouter:
    """Routes Telegram commands to handler methods."""

    async def handle(
        self,
        command: str,
        args: list[str],
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> str:
        """
        Dispatch *command* to the appropriate handler.

        Returns the response text to send back to the user.
        """
        handler = getattr(self, f"_handle_{command}", None)
        if handler is None:
            return HELP_TEXT
        try:
            return await handler(args, update, context)
        except Exception as exc:
            logger.exception("Error handling /%s: %s", command, exc)
            return f"❌ Error processing /{command}: {exc}"

    # ------------------------------------------------------------------
    # Core commands (Task 7.2)
    # ------------------------------------------------------------------

    async def _handle_start(self, args, update, context) -> str:
        return WELCOME_TEXT

    async def _handle_help(self, args, update, context) -> str:
        return HELP_TEXT

    async def _handle_picks(self, args, update, context) -> str:
        """Trigger morning analysis and return formatted picks."""
        await update.effective_message.reply_text("⏳ Running morning analysis… this may take a few minutes.")

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _run_morning_analysis)
        except Exception as exc:
            logger.exception("Morning analysis failed: %s", exc)
            return f"❌ Morning analysis failed: {exc}"

        # Cache picks for /buy N
        _last_picks["options"] = result.get("options_picks", [])
        _last_picks["stocks"] = result.get("stock_picks", [])
        _last_picks["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Format via message_formatter
        try:
            from agents.orchestrator.skills.message_formatter import format_morning_analysis
            return format_morning_analysis(result)
        except ImportError:
            return _fallback_format_picks(result)

    async def _handle_analyze(self, args, update, context) -> str:
        """Run all agents for a single ticker."""
        if not args:
            return "Usage: /analyze TICKER\nExample: /analyze NVDA"

        ticker = args[0].upper().strip()
        await update.effective_message.reply_text(f"⏳ Analyzing {ticker}…")

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _run_single_analysis, ticker)
        except Exception as exc:
            logger.exception("Analysis failed for %s: %s", ticker, exc)
            return f"❌ Analysis failed for {ticker}: {exc}"

        return _format_single_analysis(ticker, result)

    async def _handle_congress(self, args, update, context) -> str:
        """Run congressional trades agent."""
        await update.effective_message.reply_text("⏳ Fetching congressional trades…")

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _run_congress_analysis)
        except Exception as exc:
            logger.exception("Congress analysis failed: %s", exc)
            return f"❌ Congress analysis failed: {exc}"

        return _format_congress_results(result)

    # ------------------------------------------------------------------
    # Trade commands (Task 7.3)
    # ------------------------------------------------------------------

    async def _handle_buy(self, args, update, context) -> str:
        if not args:
            return "Usage: /buy TICKER QTY  or  /buy N (pick number from morning)"

        # Check if buying by pick number
        if len(args) == 1 and args[0].isdigit():
            return await self._buy_by_pick_number(int(args[0]), update, context)

        if len(args) < 2:
            return "Usage: /buy TICKER QTY\nExample: /buy NVDA 10"

        ticker = args[0].upper().strip()
        try:
            qty = int(args[1])
        except ValueError:
            return "❌ Quantity must be a number. Example: /buy NVDA 10"

        if qty <= 0:
            return "❌ Quantity must be positive."

        # Confirmation prompt
        confirm_text = (
            f"📝 *Order Confirmation*\n\n"
            f"Action: BUY\n"
            f"Ticker: {ticker}\n"
            f"Quantity: {qty}\n\n"
            f"Reply 'yes' to confirm or 'no' to cancel."
        )
        await update.effective_message.reply_text(confirm_text, parse_mode="Markdown")

        # Store pending order in context for confirmation
        context.user_data["pending_order"] = {
            "action": "buy",
            "ticker": ticker,
            "qty": qty,
        }
        return await self._execute_buy(ticker, qty)

    async def _buy_by_pick_number(self, pick_num, update, context) -> str:
        """Buy pick #N from the morning analysis."""
        all_picks = _last_picks.get("stocks", []) + _last_picks.get("options", [])
        if not all_picks:
            return "❌ No morning picks available. Run /picks first."

        if pick_num < 1 or pick_num > len(all_picks):
            return f"❌ Pick #{pick_num} not found. Available: 1-{len(all_picks)}"

        pick = all_picks[pick_num - 1]
        ticker = pick.get("ticker", "???")
        return await self._execute_buy(ticker, 1)

    async def _execute_buy(self, ticker: str, qty: int) -> str:
        broker = _get_broker()
        if broker:
            try:
                result = broker.buy_stock(ticker, qty)
                if result.get("error"):
                    return f"❌ Order rejected: {result['error']}"
                return f"✅ BUY order placed: {qty} shares of {ticker}"
            except Exception as exc:
                return f"❌ Broker error: {exc}"
        else:
            stub = _stub_buy(ticker, qty)
            return stub["message"]

    async def _handle_sell(self, args, update, context) -> str:
        if len(args) < 2:
            return "Usage: /sell TICKER QTY\nExample: /sell NVDA 10"

        ticker = args[0].upper().strip()
        try:
            qty = int(args[1])
        except ValueError:
            return "❌ Quantity must be a number."

        if qty <= 0:
            return "❌ Quantity must be positive."

        confirm_text = (
            f"📝 *Order Confirmation*\n\n"
            f"Action: SELL\n"
            f"Ticker: {ticker}\n"
            f"Quantity: {qty}\n\n"
            f"Reply 'yes' to confirm or 'no' to cancel."
        )
        await update.effective_message.reply_text(confirm_text, parse_mode="Markdown")

        broker = _get_broker()
        if broker:
            try:
                result = broker.sell_stock(ticker, qty)
                if result.get("error"):
                    return f"❌ Order rejected: {result['error']}"
                return f"✅ SELL order placed: {qty} shares of {ticker}"
            except Exception as exc:
                return f"❌ Broker error: {exc}"
        else:
            stub = _stub_sell(ticker, qty)
            return stub["message"]

    async def _handle_positions(self, args, update, context) -> str:
        broker = _get_broker()
        if broker:
            try:
                positions = broker.get_positions()
                return _format_positions(positions)
            except Exception as exc:
                return f"❌ Error fetching positions: {exc}"
        else:
            return "📊 *Open Positions*\n\nNo broker connected. Broker integration coming in task 9."

    async def _handle_account(self, args, update, context) -> str:
        broker = _get_broker()
        if broker:
            try:
                acct = broker.get_account()
                return _format_account(acct)
            except Exception as exc:
                return f"❌ Error fetching account: {exc}"
        else:
            acct = _stub_account()
            return _format_account(acct)

    async def _handle_close_all(self, args, update, context) -> str:
        confirm_text = (
            "⚠️ *Close All Positions*\n\n"
            "This will liquidate ALL open positions.\n"
            "Are you sure? Reply 'yes' to confirm."
        )
        await update.effective_message.reply_text(confirm_text, parse_mode="Markdown")

        broker = _get_broker()
        if broker:
            try:
                result = broker.close_all()
                if result.get("error"):
                    return f"❌ Error: {result['error']}"
                return "✅ All positions closed."
            except Exception as exc:
                return f"❌ Broker error: {exc}"
        else:
            stub = _stub_close_all()
            return stub["message"]

    # ------------------------------------------------------------------
    # Watchlist commands (Task 7.4)
    # ------------------------------------------------------------------

    async def _handle_add(self, args, update, context) -> str:
        if not args:
            return "Usage: /add TICKER\nExample: /add PLTR"

        ticker = args[0].upper().strip()
        try:
            import shared_memory_io
            watchlist = shared_memory_io.load_watchlist()
            all_tickers = watchlist.get("all_tickers", [])

            if ticker in all_tickers:
                return f"ℹ️ {ticker} is already in the watchlist."

            all_tickers.append(ticker)
            watchlist["all_tickers"] = all_tickers

            # Add to 'custom' sector if not in any sector
            sectors = watchlist.get("sectors", {})
            in_sector = any(ticker in tickers for tickers in sectors.values())
            if not in_sector:
                custom = sectors.get("custom", [])
                custom.append(ticker)
                sectors["custom"] = custom
                watchlist["sectors"] = sectors

            shared_memory_io.save_watchlist(watchlist)
            return f"✅ Added {ticker} to watchlist."
        except Exception as exc:
            logger.exception("Failed to add %s: %s", ticker, exc)
            return f"❌ Failed to add {ticker}: {exc}"

    async def _handle_remove(self, args, update, context) -> str:
        if not args:
            return "Usage: /remove TICKER\nExample: /remove PLTR"

        ticker = args[0].upper().strip()
        try:
            import shared_memory_io
            watchlist = shared_memory_io.load_watchlist()
            all_tickers = watchlist.get("all_tickers", [])

            if ticker not in all_tickers:
                return f"ℹ️ {ticker} is not in the watchlist."

            all_tickers.remove(ticker)
            watchlist["all_tickers"] = all_tickers

            # Remove from sectors too
            sectors = watchlist.get("sectors", {})
            for sector_name, tickers in sectors.items():
                if ticker in tickers:
                    tickers.remove(ticker)
            watchlist["sectors"] = sectors

            shared_memory_io.save_watchlist(watchlist)
            return f"✅ Removed {ticker} from watchlist."
        except Exception as exc:
            logger.exception("Failed to remove %s: %s", ticker, exc)
            return f"❌ Failed to remove {ticker}: {exc}"

    async def _handle_pnl(self, args, update, context) -> str:
        broker = _get_broker()
        if broker:
            try:
                acct = broker.get_account()
                pnl = acct.get("daily_pnl", "N/A")
                return f"📈 *Today's P&L*: {pnl}"
            except Exception as exc:
                return f"❌ Error fetching P&L: {exc}"
        return "📈 *Today's P&L*: Broker not connected."


# ---------------------------------------------------------------------------
# Analysis execution helpers
# ---------------------------------------------------------------------------

def _run_morning_analysis() -> dict:
    """Run the full morning analysis pipeline synchronously."""
    from agents.orchestrator.skills.fleet_launcher import launch_fleet, poll_completion
    from agents.orchestrator.skills.score_combiner import combine
    from agents.orchestrator.skills.pick_selector import (
        select_options,
        select_stocks,
        enrich_options_picks,
    )
    import shared_memory_io

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # Launch fleet and poll
    launch_fleet(run_id)
    poll_result = poll_completion(run_id)
    agent_results = poll_result.get("results", {})

    # Combine scores
    combined = combine(agent_results)

    # Select picks
    options_picks = select_options(combined)
    stock_picks = select_stocks(combined)

    # Enrich options with contracts
    options_picks = enrich_options_picks(options_picks)

    # Load premarket data for summary
    premarket_data = agent_results.get("premarket", {}).get("results", [])

    return {
        "run_id": run_id,
        "options_picks": options_picks,
        "stock_picks": stock_picks,
        "combined": combined,
        "premarket_data": premarket_data,
        "timed_out": poll_result.get("timed_out", []),
    }


def _run_single_analysis(ticker: str) -> dict:
    """Run all agents for a single ticker."""
    import importlib

    agent_modules = {
        "fundamentals": "agents.fundamentals.skills.fundamentals_analysis",
        "sentiment": "agents.sentiment.skills.sentiment_analysis",
        "macro": "agents.macro.skills.macro_analysis",
        "news": "agents.news.skills.news_analysis",
        "technical": "agents.technical.skills.technical_analysis",
        "premarket": "agents.premarket.skills.premarket_analysis",
        "congress": "agents.congress.skills.congress_analysis",
        "options_chain": "agents.options_chain.skills.options_analysis",
    }

    results = {}
    for agent_id, module_path in agent_modules.items():
        try:
            mod = importlib.import_module(module_path)
            if agent_id == "options_chain":
                # Options chain has a different interface
                if hasattr(mod, "get_best_option"):
                    contract = mod.get_best_option(ticker, "CALL")
                    results[agent_id] = {"results": [contract] if contract else []}
                else:
                    results[agent_id] = {"results": []}
            else:
                agent_results = mod.run([ticker], None)
                results[agent_id] = {"results": agent_results}
        except Exception as exc:
            logger.warning("Agent %s failed for %s: %s", agent_id, ticker, exc)
            results[agent_id] = {
                "results": [{"ticker": ticker, "score": 5.0, "direction": "HOLD"}],
                "error": str(exc),
            }

    # Compute composite
    from agents.orchestrator.skills.score_combiner import combine
    combined = combine(results)

    return {"agent_results": results, "combined": combined}


def _run_congress_analysis() -> list[dict]:
    """Run the congressional trades agent."""
    try:
        from agents.congress.skills.congress_analysis import run
        import shared_memory_io
        watchlist = shared_memory_io.load_watchlist()
        tickers = watchlist.get("all_tickers", [])
        return run(tickers, None)
    except Exception as exc:
        logger.exception("Congress analysis error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_single_analysis(ticker: str, result: dict) -> str:
    """Format single-ticker analysis results."""
    lines = [f"🔍 *Analysis: {ticker}*\n"]

    agent_results = result.get("agent_results", {})
    for agent_id, data in agent_results.items():
        entries = data.get("results", [])
        if entries:
            entry = entries[0] if isinstance(entries, list) and entries else {}
            score = entry.get("score", "N/A")
            direction = entry.get("direction", "N/A")
            emoji = "🟢" if direction == "CALL" else "🔴" if direction == "PUT" else "🟡"
            lines.append(f"{emoji} {agent_id}: {score} ({direction})")
        else:
            lines.append(f"🟡 {agent_id}: N/A")

    combined = result.get("combined", [])
    if combined:
        c = combined[0]
        score = c.get("composite_score", "N/A")
        direction = c.get("direction", "N/A")
        confidence = c.get("confidence", "N/A")
        emoji = "🟢" if direction == "CALL" else "🔴" if direction == "PUT" else "🟡"
        lines.append(f"\n{emoji} *Composite: {score} ({direction}, {confidence})*")

    return "\n".join(lines)


def _format_congress_results(results: list[dict]) -> str:
    """Format congressional trade results."""
    if not results:
        return "🏛️ *Congressional Trades*\n\nNo recent disclosures found."

    lines = ["🏛️ *Congressional Trades*\n"]
    for r in results[:15]:
        ticker = r.get("ticker", "???")
        score = r.get("score", 5.0)
        direction = r.get("direction", "HOLD")
        signal = r.get("congress_signal", "")
        emoji = "🟢" if direction == "CALL" else "🔴" if direction == "PUT" else "🟡"

        line = f"{emoji} {ticker}: {score}"
        if signal:
            line += f" — {signal}"
        lines.append(line)

    return "\n".join(lines)


def _format_positions(positions: list[dict]) -> str:
    """Format open positions for display."""
    if not positions:
        return "📊 *Open Positions*\n\nNo open positions."

    lines = ["📊 *Open Positions*\n"]
    for p in positions:
        symbol = p.get("symbol", "???")
        qty = p.get("qty", 0)
        entry = p.get("avg_entry_price", 0)
        current = p.get("current_price", 0)
        unrealized_pnl = p.get("unrealized_pl", 0)
        pnl_pct = p.get("unrealized_plpc", 0)

        emoji = "🟢" if float(unrealized_pnl) >= 0 else "🔴"
        lines.append(
            f"{emoji} {symbol}: {qty} @ ${entry} → ${current} "
            f"(P&L: ${unrealized_pnl}, {pnl_pct}%)"
        )

    return "\n".join(lines)


def _format_account(acct: dict) -> str:
    """Format account info for display."""
    return (
        "💰 *Account Summary*\n\n"
        f"Cash: ${acct.get('cash', 'N/A')}\n"
        f"Buying Power: ${acct.get('buying_power', 'N/A')}\n"
        f"Portfolio Value: ${acct.get('portfolio_value', 'N/A')}\n"
        f"Equity: ${acct.get('equity', 'N/A')}\n"
        f"Daily P&L: ${acct.get('daily_pnl', 'N/A')}"
    )


def _fallback_format_picks(result: dict) -> str:
    """Simple fallback formatter if message_formatter is not available."""
    lines = ["🦀 *Morning Analysis*\n"]

    options = result.get("options_picks", [])
    if options:
        lines.append("*Top Options:*")
        for i, p in enumerate(options, 1):
            emoji = "🟢" if p.get("direction") == "CALL" else "🔴"
            lines.append(
                f"{emoji} #{i} {p.get('ticker')} {p.get('direction')} "
                f"Score: {p.get('composite_score', 'N/A')}"
            )

    stocks = result.get("stock_picks", [])
    if stocks:
        lines.append("\n*Top Stocks:*")
        for i, p in enumerate(stocks, 1):
            action = p.get("action", "WATCH")
            emoji = "🟢" if action == "BUY" else "🔴" if action in ("SELL", "SELL/SHORT") else "🟡"
            lines.append(
                f"{emoji} #{i} {p.get('ticker')} {action} "
                f"Score: {p.get('composite_score', 'N/A')}"
            )

    return "\n".join(lines)


# Module-level singleton
router = CommandRouter()
