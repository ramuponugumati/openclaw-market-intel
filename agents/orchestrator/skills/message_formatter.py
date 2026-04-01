"""
Message Formatter Skill

Formats Telegram messages for morning analysis and EOD recap.
Handles emoji conventions, section layout, and Telegram's 4096-char limit.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096

# Emoji conventions (Requirement 19.2)
EMOJI_CALL = "🟢"
EMOJI_PUT = "🔴"
EMOJI_HOLD = "🟡"
EMOJI_CONGRESS = "🏛️"


def _direction_emoji(direction: str) -> str:
    """Return the emoji for a given direction string."""
    d = direction.upper()
    if d in ("CALL", "BUY"):
        return EMOJI_CALL
    if d in ("PUT", "SELL", "SELL/SHORT"):
        return EMOJI_PUT
    return EMOJI_HOLD


def _confidence_label(confidence: str) -> str:
    c = confidence.upper()
    if c == "HIGH":
        return "🔥 HIGH"
    if c == "MEDIUM":
        return "⚡ MED"
    return "💤 LOW"


# ---------------------------------------------------------------------------
# Message splitting (Requirement 19.5)
# ---------------------------------------------------------------------------

def split_message(text: str, max_len: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """
    Split *text* into chunks of at most *max_len* characters.

    Tries to split at newline boundaries for readability.
    """
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def truncate_message(text: str, max_len: int = TELEGRAM_MAX_LENGTH) -> str:
    """Truncate a single message to *max_len*, appending '…' if cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Pre-market summary section
# ---------------------------------------------------------------------------

def _format_premarket_section(premarket_data: list[dict]) -> str:
    """Format the pre-market summary section."""
    if not premarket_data:
        return ""

    lines = ["📊 *Pre-Market Summary*\n"]

    # Extract futures, global indices, and movers from premarket data
    futures = []
    global_indices = []
    movers = []

    futures_symbols = {"ES=F", "NQ=F", "YM=F", "RTY=F", "CL=F", "GC=F", "^VIX", "DX-Y.NYB", "^TNX"}
    global_symbols = {"^N225", "^HSI", "^FTSE", "^GDAXI", "000001.SS"}

    for item in premarket_data:
        ticker = item.get("ticker", "")
        change = item.get("change_pct", item.get("gap_pct", 0))
        if isinstance(change, str):
            try:
                change = float(change.replace("%", ""))
            except ValueError:
                change = 0

        emoji = "🟢" if change > 0 else "🔴" if change < 0 else "🟡"
        label = item.get("name", ticker)

        if ticker in futures_symbols:
            futures.append(f"  {emoji} {label}: {change:+.2f}%")
        elif ticker in global_symbols:
            global_indices.append(f"  {emoji} {label}: {change:+.2f}%")
        elif abs(change) > 1.0:
            movers.append(f"  {emoji} {ticker}: {change:+.2f}%")

    if futures:
        lines.append("*Futures:*")
        lines.extend(futures[:6])
    if global_indices:
        lines.append("\n*Global:*")
        lines.extend(global_indices[:5])
    if movers:
        lines.append("\n*Pre-Market Movers (>1%):*")
        lines.extend(movers[:5])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Morning Analysis (Requirement 19.1)
# ---------------------------------------------------------------------------

def format_morning_analysis(result: dict) -> str:
    """
    Format the complete morning analysis message.

    Sections:
    1. Pre-market summary (futures, global, movers)
    2. Top 5 options (strike, expiry, premium, volume, OI, IV)
    3. Top 10 stocks (action, score, confidence, strongest agent)
    4. Footer (budget, trading mode, disclaimer)

    Args:
        result: Dict with keys: options_picks, stock_picks, premarket_data,
                run_id, combined, timed_out.

    Returns:
        Formatted message string (may need splitting for Telegram).
    """
    sections: list[str] = []

    # Header
    sections.append("🦀 *OpenClaw Morning Analysis*\n")

    # Pre-market summary
    premarket_data = result.get("premarket_data", [])
    premarket_section = _format_premarket_section(premarket_data)
    if premarket_section:
        sections.append(premarket_section)

    # Top 5 Options
    options = result.get("options_picks", [])
    sections.append(_format_options_section(options))

    # Top 10 Stocks
    stocks = result.get("stock_picks", [])
    sections.append(_format_stocks_section(stocks))

    # Congress signals
    congress_section = _format_congress_signals(result)
    if congress_section:
        sections.append(congress_section)

    # Footer (Requirement 19.3)
    sections.append(_format_footer())

    return "\n\n".join(sections)


def _format_options_section(options: list[dict]) -> str:
    """Format Top 5 options picks with contract details."""
    lines = ["🎯 *Top 5 Options Plays*\n"]

    if not options:
        lines.append("  No options picks available.")
        return "\n".join(lines)

    for i, pick in enumerate(options, 1):
        ticker = pick.get("ticker", "???")
        direction = pick.get("direction", "HOLD")
        score = pick.get("composite_score", 5.0)
        confidence = pick.get("confidence", "LOW")
        emoji = _direction_emoji(direction)

        line = f"{emoji} *#{i} {ticker} {direction}* — Score: {score:.1f} ({_confidence_label(confidence)})"
        lines.append(line)

        # Option contract details if enriched
        contract = pick.get("option_contract", {})
        if contract and not contract.get("error"):
            strike = contract.get("strike", "N/A")
            expiry = contract.get("expiry", "N/A")
            mid = contract.get("mid_price", "N/A")
            volume = contract.get("volume", "N/A")
            oi = contract.get("open_interest", contract.get("oi", "N/A"))
            iv = contract.get("implied_volatility", contract.get("iv", "N/A"))

            if isinstance(iv, (int, float)):
                iv = f"{iv:.0%}" if iv < 1 else f"{iv:.0f}%"

            lines.append(
                f"  Strike: ${strike} | Exp: {expiry} | Mid: ${mid}"
            )
            lines.append(
                f"  Vol: {volume} | OI: {oi} | IV: {iv}"
            )

    return "\n".join(lines)


def _format_stocks_section(stocks: list[dict]) -> str:
    """Format Top 10 stock picks."""
    lines = ["📈 *Top 10 Stock Trades*\n"]

    if not stocks:
        lines.append("  No stock picks available.")
        return "\n".join(lines)

    for i, pick in enumerate(stocks, 1):
        ticker = pick.get("ticker", "???")
        action = pick.get("action", "WATCH")
        score = pick.get("composite_score", 5.0)
        confidence = pick.get("confidence", "LOW")
        emoji = _direction_emoji(action)

        # Find strongest agent
        agent_scores = pick.get("agent_scores", {})
        strongest = _find_strongest_agent(agent_scores)

        line = (
            f"{emoji} *#{i} {ticker}* {action} — "
            f"Score: {score:.1f} ({_confidence_label(confidence)})"
        )
        if strongest:
            line += f"\n  Strongest: {strongest}"
        lines.append(line)

    return "\n".join(lines)


def _find_strongest_agent(agent_scores: dict) -> str:
    """Find the agent with the highest absolute deviation from 5.0."""
    if not agent_scores:
        return ""
    best_agent = ""
    best_distance = 0.0
    for agent_id, info in agent_scores.items():
        score = info.get("score", 5.0) if isinstance(info, dict) else 5.0
        distance = abs(score - 5.0)
        if distance > best_distance:
            best_distance = distance
            best_agent = agent_id
            best_score = score
            best_dir = info.get("direction", "HOLD") if isinstance(info, dict) else "HOLD"

    if best_agent:
        return f"{best_agent} ({best_score:.1f} {best_dir})"
    return ""


def _format_congress_signals(result: dict) -> str:
    """Extract and format any congressional trade signals."""
    combined = result.get("combined", [])
    signals = []
    for item in combined:
        agent_scores = item.get("agent_scores", {})
        congress_data = agent_scores.get("congress", {})
        if isinstance(congress_data, dict):
            congress_signal = congress_data.get("congress_signal", "")
            if congress_signal and "BOUGHT" in congress_signal.upper():
                ticker = item.get("ticker", "???")
                signals.append(f"  {EMOJI_CONGRESS} {ticker}: {congress_signal}")

    if not signals:
        return ""

    lines = [f"{EMOJI_CONGRESS} *Congressional Signals*\n"]
    lines.extend(signals[:5])
    return "\n".join(lines)


def _format_footer() -> str:
    """Format the message footer with budget, mode, and disclaimer."""
    # Load current trading mode
    try:
        import shared_memory_io
        horizon = shared_memory_io.load_horizon_state()
        mode = horizon.get("current_mode", "day_trade")
    except Exception:
        mode = "day_trade"

    mode_labels = {
        "day_trade": "📅 Day Trade",
        "swing_trade": "📆 Swing Trade (2-7 days)",
        "long_term": "📈 Long Term (up to 1 year)",
    }
    mode_label = mode_labels.get(mode, f"📅 {mode}")

    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Budget: $1,000 | Mode: {mode_label}\n"
        "⚠️ _Not financial advice. Do your own research._"
    )


# ---------------------------------------------------------------------------
# EOD Recap (Requirement 19.4)
# ---------------------------------------------------------------------------

def format_eod_recap(recap_data: dict) -> str:
    """
    Format the end-of-day recap message.

    Sections:
    - Broker P&L
    - Trade results
    - Options accuracy
    - Stock accuracy
    - Overall accuracy %
    - Learning status

    Args:
        recap_data: Dict with keys: broker_pnl, trade_results,
                    options_accuracy, stock_accuracy, overall_accuracy,
                    weight_update, horizon_status.

    Returns:
        Formatted message string.
    """
    sections: list[str] = []

    sections.append("🌙 *OpenClaw EOD Recap*\n")

    # Broker P&L
    broker_pnl = recap_data.get("broker_pnl", {})
    daily_pnl = broker_pnl.get("daily_pnl", "N/A")
    equity = broker_pnl.get("equity", "N/A")
    pnl_emoji = "🟢" if _is_positive(daily_pnl) else "🔴"
    sections.append(
        f"💰 *Broker P&L*\n"
        f"  {pnl_emoji} Daily: ${daily_pnl}\n"
        f"  Equity: ${equity}"
    )

    # Trade results
    trades = recap_data.get("trade_results", [])
    if trades:
        trade_lines = ["📋 *Trade Results*\n"]
        for t in trades[:10]:
            ticker = t.get("ticker", "???")
            action = t.get("action", "???")
            pnl = t.get("realized_pnl", 0)
            emoji = "🟢" if float(pnl) >= 0 else "🔴"
            trade_lines.append(f"  {emoji} {ticker} {action}: ${pnl}")
        sections.append("\n".join(trade_lines))

    # Accuracy
    options_acc = recap_data.get("options_accuracy", "N/A")
    stock_acc = recap_data.get("stock_accuracy", "N/A")
    overall_acc = recap_data.get("overall_accuracy", "N/A")

    acc_section = (
        "🎯 *Pick Accuracy*\n"
        f"  Options: {_format_pct(options_acc)}\n"
        f"  Stocks: {_format_pct(stock_acc)}\n"
        f"  Overall: {_format_pct(overall_acc)}"
    )
    sections.append(acc_section)

    # Learning status
    weight_update = recap_data.get("weight_update", {})
    horizon = recap_data.get("horizon_status", {})
    learning_lines = ["🧠 *Learning Status*\n"]

    days_eval = weight_update.get("days_evaluated", 0)
    learning_lines.append(f"  Days evaluated: {days_eval}")

    if weight_update.get("weights_updated"):
        learning_lines.append("  ✅ Weights updated this session")
    else:
        learning_lines.append("  ⏳ Weights unchanged (need ≥5 days)")

    current_mode = horizon.get("current_mode", "day_trade")
    mode_labels = {
        "day_trade": "Day Trade",
        "swing_trade": "Swing Trade",
        "long_term": "Long Term",
    }
    learning_lines.append(f"  Mode: {mode_labels.get(current_mode, current_mode)}")

    transition = horizon.get("transition")
    if transition:
        learning_lines.append(f"  🔄 Mode changed: {transition}")

    sections.append("\n".join(learning_lines))

    # Footer
    sections.append("⚠️ _Not financial advice. Do your own research._")

    return "\n\n".join(sections)


def _is_positive(value: Any) -> bool:
    """Check if a value represents a positive number."""
    if isinstance(value, (int, float)):
        return value >= 0
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("$", "")) >= 0
        except ValueError:
            return True
    return True


def _format_pct(value: Any) -> str:
    """Format a value as a percentage string."""
    if isinstance(value, (int, float)):
        return f"{value:.1f}%"
    return str(value)
