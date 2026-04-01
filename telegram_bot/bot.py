"""
Telegram Bot Listener

Long-polling Telegram bot using python-telegram-bot library.
Authenticates every incoming message against the user ID allowlist
before routing to the command handler.

Requirements: 12.1, 22.5
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from telegram_bot.auth import UNAUTHORIZED_MESSAGE, is_authorized  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth wrapper — applied to every handler
# ---------------------------------------------------------------------------

def auth_required(handler):
    """Decorator that checks user authorization before executing the handler."""

    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if user is None or not is_authorized(user.id):
            uid = user.id if user else "unknown"
            logger.warning("Unauthorized access attempt from user %s", uid)
            if update.effective_message:
                await update.effective_message.reply_text(UNAUTHORIZED_MESSAGE)
            return
        return await handler(update, context)

    return wrapper


# ---------------------------------------------------------------------------
# Import command router (lazy to avoid circular imports at module level)
# ---------------------------------------------------------------------------

def _get_router():
    """Lazy import of command_router to avoid circular dependency."""
    from telegram_bot.command_router import router
    return router


# ---------------------------------------------------------------------------
# Command handlers — thin wrappers that delegate to command_router
# ---------------------------------------------------------------------------

@auth_required
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("start", [], update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("help", [], update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_picks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("picks", [], update, context)
    await _send_long_message(update, response)


@auth_required
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    args = context.args or []
    response = await router.handle("analyze", args, update, context)
    await _send_long_message(update, response)


@auth_required
async def cmd_congress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("congress", [], update, context)
    await _send_long_message(update, response)


@auth_required
async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    args = context.args or []
    response = await router.handle("buy", args, update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    args = context.args or []
    response = await router.handle("sell", args, update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("positions", [], update, context)
    await _send_long_message(update, response)


@auth_required
async def cmd_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("account", [], update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_close_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("close_all", [], update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    args = context.args or []
    response = await router.handle("add", args, update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    args = context.args or []
    response = await router.handle("remove", args, update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    router = _get_router()
    response = await router.handle("pnl", [], update, context)
    await update.effective_message.reply_text(response, parse_mode="Markdown")


@auth_required
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unrecognized text messages with a help prompt."""
    router = _get_router()
    response = await router.handle("help", [], update, context)
    text = "❓ Unrecognized command.\n\n" + response
    await update.effective_message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Message splitting for Telegram's 4096-char limit
# ---------------------------------------------------------------------------

TELEGRAM_MAX_LENGTH = 4096


async def _send_long_message(update: Update, text: str) -> None:
    """Split and send a message that may exceed Telegram's 4096-char limit."""
    chunks = split_message(text, TELEGRAM_MAX_LENGTH)
    for chunk in chunks:
        await update.effective_message.reply_text(chunk, parse_mode="Markdown")


def split_message(text: str, max_len: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split *text* into chunks of at most *max_len* characters."""
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at last newline within limit
        split_at = text.rfind("\n", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ---------------------------------------------------------------------------
# Bot builder
# ---------------------------------------------------------------------------

def build_application(token: str | None = None) -> Application:
    """
    Build and return a configured Telegram Application instance.

    Args:
        token: Bot token. If None, reads from TELEGRAM_BOT_TOKEN env var.
    """
    if token is None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    app = Application.builder().token(token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("picks", cmd_picks))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("congress", cmd_congress))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("account", cmd_account))
    app.add_handler(CommandHandler("close_all", cmd_close_all))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("remove", cmd_remove))
    app.add_handler(CommandHandler("pnl", cmd_pnl))

    # Catch-all for unrecognized text
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    return app


def run_bot(token: str | None = None) -> None:
    """Build the bot and start long-polling. Blocks until stopped."""
    app = build_application(token)
    logger.info("Starting Telegram bot (long-polling)…")
    app.run_polling(drop_pending_updates=True)
