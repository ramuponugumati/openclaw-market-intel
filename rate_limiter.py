"""
Finnhub Rate Limiter

Provides a simple rate limiter for the Finnhub free tier (60 calls/minute).
Uses a token-bucket approach with a decorator for easy integration.

Usage:
    from rate_limiter import RateLimiter, finnhub_rate_limit

    # As a decorator
    @finnhub_rate_limit
    def call_finnhub(ticker):
        ...

    # As a class instance
    limiter = RateLimiter(max_calls=60, period=60)
    limiter.wait()
    make_api_call()
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter.

    Tracks timestamps of recent calls and sleeps when the limit is reached.

    Args:
        max_calls: Maximum number of calls allowed in the time window.
        period: Time window in seconds.
    """

    def __init__(self, max_calls: int = 60, period: float = 60.0):
        self.max_calls = max_calls
        self.period = period
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until a call is allowed under the rate limit."""
        with self._lock:
            now = time.monotonic()

            # Purge timestamps outside the current window
            while self._timestamps and self._timestamps[0] <= now - self.period:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.max_calls:
                # Sleep until the oldest timestamp exits the window
                sleep_time = self._timestamps[0] - (now - self.period)
                if sleep_time > 0:
                    logger.debug("Rate limiter: sleeping %.2fs", sleep_time)
                    time.sleep(sleep_time)

                # Re-purge after sleeping
                now = time.monotonic()
                while self._timestamps and self._timestamps[0] <= now - self.period:
                    self._timestamps.popleft()

            self._timestamps.append(time.monotonic())


# Global Finnhub rate limiter instance (60 calls/min)
_finnhub_limiter = RateLimiter(max_calls=60, period=60.0)


def finnhub_rate_limit(func):
    """
    Decorator that enforces Finnhub's 60 calls/minute rate limit.

    Wraps any function so that it waits for rate-limit clearance before executing.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        _finnhub_limiter.wait()
        return func(*args, **kwargs)
    return wrapper


def get_finnhub_limiter() -> RateLimiter:
    """Return the global Finnhub rate limiter instance."""
    return _finnhub_limiter
