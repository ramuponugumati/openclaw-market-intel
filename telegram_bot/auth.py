"""
Telegram User Authentication

Validates incoming Telegram messages against an allowlist of user IDs
loaded from the ALLOWED_USER_IDS environment variable.

Requirements: 22.5
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def load_allowed_user_ids() -> set[int]:
    """
    Parse ALLOWED_USER_IDS env var (comma-separated ints) into a set.

    Returns an empty set if the variable is unset or empty.
    """
    raw = os.environ.get("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                logger.warning("Ignoring invalid ALLOWED_USER_IDS entry: %s", part)
    return ids


# Module-level cache — refreshed on first call or via reload()
_allowed_ids: set[int] | None = None


def _get_allowed_ids() -> set[int]:
    global _allowed_ids
    if _allowed_ids is None:
        _allowed_ids = load_allowed_user_ids()
    return _allowed_ids


def reload_allowed_ids() -> None:
    """Force re-read of ALLOWED_USER_IDS from environment."""
    global _allowed_ids
    _allowed_ids = load_allowed_user_ids()


def is_authorized(user_id: int) -> bool:
    """
    Check whether *user_id* is in the allowed list.

    If the allowlist is empty (no env var set), ALL users are rejected
    for safety — the bot should not operate without an explicit allowlist.
    """
    allowed = _get_allowed_ids()
    if not allowed:
        logger.warning(
            "ALLOWED_USER_IDS is empty — rejecting user %d by default", user_id
        )
        return False
    return user_id in allowed


UNAUTHORIZED_MESSAGE = (
    "⛔ You are not authorized to use this bot.\n"
    "Contact the administrator to get your Telegram user ID added."
)
