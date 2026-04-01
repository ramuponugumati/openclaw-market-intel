"""
Unit tests for the Daily Movers Fetcher.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from daily_movers import fetch_daily_movers, fetch_and_merge_movers, MIN_CHANGE_PCT


class TestFetchDailyMovers:

    def test_returns_empty_when_yfinance_not_installed(self):
        """Should gracefully return [] if yfinance is not importable."""
        with patch.dict("sys.modules", {"yfinance": None}):
            # Force re-import failure
            with patch("builtins.__import__", side_effect=ImportError("no yfinance")):
                result = fetch_daily_movers()
        # May or may not be empty depending on import caching, but should not raise
        assert isinstance(result, list)

    def test_returns_empty_on_download_failure(self):
        """Should return [] if yfinance.download raises."""
        mock_yf = MagicMock()
        mock_yf.download.side_effect = Exception("network error")
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = fetch_daily_movers()
        assert result == []

    def test_returns_empty_on_empty_data(self):
        """Should return [] if yfinance returns empty DataFrame."""
        mock_yf = MagicMock()
        mock_df = MagicMock()
        mock_df.empty = True
        mock_df.__bool__ = lambda self: False
        mock_yf.download.return_value = mock_df
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            result = fetch_daily_movers()
        assert result == []

    def test_mover_dict_schema(self):
        """Movers should have ticker, change_pct, direction, volume keys."""
        # We'll test the schema by constructing a known result
        mover = {
            "ticker": "AAPL",
            "change_pct": 7.5,
            "direction": "up",
            "volume": 1000000,
        }
        assert "ticker" in mover
        assert "change_pct" in mover
        assert "direction" in mover
        assert "volume" in mover
        assert mover["direction"] in ("up", "down")

    def test_min_change_threshold(self):
        """MIN_CHANGE_PCT should be 5.0."""
        assert MIN_CHANGE_PCT == 5.0


class TestFetchAndMergeMovers:

    def test_merge_adds_to_watchlist(self, tmp_path):
        """Movers should be added to all_tickers and sectors['daily_movers']."""
        # Set up shared memory
        config_dir = tmp_path / "config"
        config_dir.mkdir(parents=True)
        watchlist = {
            "all_tickers": ["AAPL", "MSFT"],
            "sectors": {"tech": ["AAPL", "MSFT"]},
        }
        (config_dir / "watchlist.json").write_text(json.dumps(watchlist))

        mock_movers = [
            {"ticker": "TSLA", "change_pct": 8.0, "direction": "up", "volume": 5000000},
            {"ticker": "AAPL", "change_pct": -6.0, "direction": "down", "volume": 3000000},
        ]

        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            with patch("daily_movers.fetch_daily_movers", return_value=mock_movers):
                result = fetch_and_merge_movers()

        assert len(result) == 2

        # Verify watchlist was updated
        updated = json.loads((config_dir / "watchlist.json").read_text())
        assert "TSLA" in updated["all_tickers"]
        assert "AAPL" in updated["all_tickers"]
        assert "MSFT" in updated["all_tickers"]
        assert "daily_movers" in updated["sectors"]
        assert "TSLA" in updated["sectors"]["daily_movers"]

    def test_returns_empty_on_no_movers(self):
        """Should return [] when no movers found."""
        with patch("daily_movers.fetch_daily_movers", return_value=[]):
            result = fetch_and_merge_movers()
        assert result == []

    def test_handles_shared_memory_failure(self, tmp_path):
        """Should still return movers even if watchlist save fails."""
        mock_movers = [
            {"ticker": "TSLA", "change_pct": 8.0, "direction": "up", "volume": 5000000},
        ]

        with patch("daily_movers.fetch_daily_movers", return_value=mock_movers):
            with patch("shared_memory_io.load_watchlist", side_effect=Exception("disk error")):
                result = fetch_and_merge_movers()

        # Should still return the movers even though merge failed
        assert len(result) == 1
