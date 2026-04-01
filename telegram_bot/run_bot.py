"""
Telegram Bot Runner

Entry point for starting the Telegram bot polling loop.
Used by the Fargate container entrypoint.

Requirements: 12.1, 20.1
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from telegram_bot.bot import run_bot  # noqa: E402

if __name__ == "__main__":
    run_bot()
else:
    # Also run when invoked via `python -m telegram_bot.run_bot`
    run_bot()
