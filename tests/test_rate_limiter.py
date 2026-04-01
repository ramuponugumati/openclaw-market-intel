"""
Unit tests for the Finnhub Rate Limiter.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from rate_limiter import RateLimiter, finnhub_rate_limit, get_finnhub_limiter


class TestRateLimiter:

    def test_allows_calls_under_limit(self):
        """Should not block when under the rate limit."""
        limiter = RateLimiter(max_calls=5, period=1.0)
        start = time.monotonic()
        for _ in range(5):
            limiter.wait()
        elapsed = time.monotonic() - start
        # 5 calls should complete nearly instantly
        assert elapsed < 0.5

    def test_blocks_when_limit_exceeded(self):
        """Should sleep when rate limit is hit."""
        limiter = RateLimiter(max_calls=2, period=0.5)
        limiter.wait()
        limiter.wait()
        start = time.monotonic()
        limiter.wait()  # This should block ~0.5s
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3  # Allow some tolerance

    def test_default_finnhub_limiter_is_60_per_minute(self):
        """Global limiter should be configured for 60 calls/60s."""
        limiter = get_finnhub_limiter()
        assert limiter.max_calls == 60
        assert limiter.period == 60.0


class TestFinnhubRateLimitDecorator:

    def test_decorator_wraps_function(self):
        """Decorated function should still return its result."""
        @finnhub_rate_limit
        def my_func(x):
            return x * 2

        assert my_func(5) == 10

    def test_decorator_preserves_function_name(self):
        """Decorated function should keep its original name."""
        @finnhub_rate_limit
        def my_special_func():
            pass

        assert my_special_func.__name__ == "my_special_func"
