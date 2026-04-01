"""
Unit tests for the Macro/Fed Analysis Skill.

Validates Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 21.1, 21.4
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.macro.skills.macro_analysis import (
    fetch_fred_series,
    _parse_valid_value,
    assess_environment,
    score_ticker,
    run,
    write_to_shared_memory,
    SECTOR_MAP,
)

FAKE_API_KEY = "test_fred_key_123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_obs(value: str, date: str = "2026-01-15") -> dict:
    """Build a single FRED observation dict."""
    return {"date": date, "value": value}


def _build_fred_env(yield_change: float = 0.0, vix_current: float = 18.0,
                    yield_2y: float = 4.2, yield_10y: float = 4.5,
                    fed_funds_change: float = 0.0):
    """
    Build a macro environment dict with controllable yield change and VIX.
    Useful for testing score_ticker without hitting FRED.
    """
    yield_curve_inverted = yield_2y > yield_10y
    fed_funds_rising = fed_funds_change > 0
    return {
        "indicators": {
            "10Y_YIELD": {"current": yield_10y, "previous": yield_10y - yield_change, "change": yield_change},
            "2Y_YIELD": {"current": yield_2y, "previous": yield_2y, "change": 0.0},
            "VIX": {"current": vix_current, "previous": vix_current, "change": 0.0},
            "FED_FUNDS": {"current": 5.25, "previous": 5.25 - fed_funds_change, "change": fed_funds_change},
            "CPI_YOY": {"current": 3.2, "previous": 3.1, "change": 0.1},
            "UNEMPLOYMENT": {"current": 3.7, "previous": 3.8, "change": -0.1},
        },
        "sector_signals": {},
        "yield_curve_inverted": yield_curve_inverted,
        "fed_funds_rising": fed_funds_rising,
    }



# ---------------------------------------------------------------------------
# Requirement 5.5 — Stale FRED data handling
# ---------------------------------------------------------------------------

class TestStaleFredData:
    """Validates that stale FRED observations (value='.') are skipped."""

    def test_parse_valid_value_skips_dots(self):
        """_parse_valid_value skips '.' entries and returns first valid float."""
        obs = [_make_obs("."), _make_obs("."), _make_obs("4.25")]
        assert _parse_valid_value(obs, 0) == 4.25

    def test_parse_valid_value_returns_none_when_all_stale(self):
        """All observations stale → returns None."""
        obs = [_make_obs("."), _make_obs(".")]
        assert _parse_valid_value(obs, 0) is None

    def test_parse_valid_value_at_index(self):
        """Starting at index 1 skips the first entry."""
        obs = [_make_obs("4.50"), _make_obs("."), _make_obs("4.20")]
        assert _parse_valid_value(obs, 1) == 4.20

    def test_parse_valid_value_first_valid(self):
        """First observation is valid → returns it directly."""
        obs = [_make_obs("3.75"), _make_obs("3.70")]
        assert _parse_valid_value(obs, 0) == 3.75


# ---------------------------------------------------------------------------
# Requirement 5.1 — FRED API fetching
# ---------------------------------------------------------------------------

class TestFetchFredSeries:
    """Validates FRED API fetch and error handling."""

    def test_successful_fetch(self):
        """Successful FRED response returns observations list."""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "observations": [_make_obs("4.50"), _make_obs("4.45")]
        }
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    return_value=mock_resp):
            result = fetch_fred_series("DGS10", FAKE_API_KEY, limit=2)
        assert len(result) == 2
        assert result[0]["value"] == "4.50"

    def test_api_failure_returns_empty(self):
        """Network error → empty list (Req 21.1)."""
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    side_effect=Exception("network error")):
            result = fetch_fred_series("DGS10", FAKE_API_KEY)
        assert result == []

    def test_non_ok_response_returns_empty(self):
        """HTTP error status → empty list."""
        mock_resp = MagicMock()
        mock_resp.ok = False
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    return_value=mock_resp):
            result = fetch_fred_series("DGS10", FAKE_API_KEY)
        assert result == []


# ---------------------------------------------------------------------------
# Requirement 5.2 — Rising yields apply -1.5 to tech
# ---------------------------------------------------------------------------

class TestRisingYieldsBearishTech:
    """Validates that rising 10Y yields penalise tech tickers."""

    def test_tech_ticker_bearish_on_rising_yields(self):
        """10Y yield change > 0.05 → tech gets -1.5 (score 3.5, PUT)."""
        env = _build_fred_env(yield_change=0.10)
        env["sector_signals"]["tech"] = {
            "bias": "bearish",
            "reason": "Rising 10Y yields pressure growth stocks",
        }
        result = score_ticker("NVDA", env)
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"

    def test_non_tech_ticker_unaffected_by_rising_yields(self):
        """Non-tech ticker stays at 5.0 even with rising yields."""
        env = _build_fred_env(yield_change=0.10)
        env["sector_signals"]["tech"] = {
            "bias": "bearish",
            "reason": "Rising 10Y yields pressure growth stocks",
        }
        result = score_ticker("XOM", env)  # energy, not in SECTOR_MAP
        assert result["score"] == 5.0
        assert result["direction"] == "HOLD"

    def test_fintech_also_bearish_on_rising_yields(self):
        """Fintech tickers also get -1.5 on rising yields."""
        env = _build_fred_env(yield_change=0.10)
        env["sector_signals"]["fintech"] = {
            "bias": "bearish",
            "reason": "Higher rates hurt fintech valuations",
        }
        result = score_ticker("COIN", env)
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"


# ---------------------------------------------------------------------------
# Requirement 5.3 — VIX > 25 applies bearish bias to ETFs
# ---------------------------------------------------------------------------

class TestHighVixBearishEtf:
    """Validates that VIX > 25 penalises ETF tickers."""

    def test_etf_bearish_when_vix_above_25(self):
        """VIX > 25 → ETF gets -1.5 (score 3.5, PUT)."""
        env = _build_fred_env(vix_current=30.0)
        env["sector_signals"]["etf"] = {
            "bias": "bearish",
            "reason": "VIX elevated at 30.0 — fear in market",
        }
        result = score_ticker("SPY", env)
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"

    def test_etf_bullish_when_vix_low(self):
        """VIX < 15 → ETF gets +1.5 (score 6.5, CALL)."""
        env = _build_fred_env(vix_current=12.0)
        env["sector_signals"]["etf"] = {
            "bias": "bullish",
            "reason": "VIX low at 12.0 — complacency/calm",
        }
        result = score_ticker("QQQ", env)
        assert result["score"] == 6.5
        assert result["direction"] == "CALL"

    def test_non_etf_also_affected_by_high_vix(self):
        """VIX > 25 now applies bearish to ALL sectors, including tech."""
        env = _build_fred_env(vix_current=30.0)
        env["sector_signals"]["tech"] = {
            "bias": "bearish",
            "reason": "VIX elevated at 30.0 — fear in market",
        }
        result = score_ticker("AAPL", env)
        assert result["score"] == 3.5
        assert result["direction"] == "PUT"


# ---------------------------------------------------------------------------
# Requirement 5.4 — Sector mapping
# ---------------------------------------------------------------------------

class TestSectorMapping:
    """Validates that tickers are correctly mapped to sectors."""

    def test_all_tech_tickers_in_sector_map(self):
        """All expected tech tickers are present."""
        expected_tech = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD",
                         "CRM", "ORCL", "PLTR", "AVGO"]
        for t in expected_tech:
            assert t in SECTOR_MAP["tech"]

    def test_all_etf_tickers_in_sector_map(self):
        """All expected ETF tickers are present."""
        expected_etf = ["SPY", "QQQ", "IWM", "DIA", "ARKK"]
        for t in expected_etf:
            assert t in SECTOR_MAP["etf"]


# ---------------------------------------------------------------------------
# Yield curve inversion — 2Y > 10Y applies -1.0 to all tickers
# ---------------------------------------------------------------------------

class TestYieldCurveInversion:
    """Validates yield curve inversion penalty."""

    def test_inverted_curve_penalises_all_tickers(self):
        """When 2Y > 10Y, all tickers get -1.0."""
        env = _build_fred_env(yield_2y=4.8, yield_10y=4.5)
        assert env["yield_curve_inverted"] is True
        result = score_ticker("AAPL", env)
        assert result["score"] == 4.0
        assert result["direction"] == "PUT"
        assert result["yield_curve_inverted"] is True

    def test_normal_curve_no_penalty(self):
        """When 10Y > 2Y, no inversion penalty."""
        env = _build_fred_env(yield_2y=4.0, yield_10y=4.5)
        assert env["yield_curve_inverted"] is False
        result = score_ticker("AAPL", env)
        assert result["score"] == 5.0

    def test_inverted_curve_stacks_with_sector_signal(self):
        """Inversion -1.0 stacks with sector bearish -1.5."""
        env = _build_fred_env(yield_2y=4.8, yield_10y=4.5)
        env["sector_signals"]["tech"] = {
            "bias": "bearish",
            "reason": "Rising yields",
        }
        result = score_ticker("NVDA", env)
        # 5.0 - 1.5 (sector) - 1.0 (inversion) = 2.5
        assert result["score"] == 2.5
        assert result["direction"] == "PUT"


# ---------------------------------------------------------------------------
# Rising Fed funds rate — -0.5 to growth/tech stocks
# ---------------------------------------------------------------------------

class TestRisingFedFundsRate:
    """Validates rising Fed funds rate penalty for growth stocks."""

    def test_rising_rates_penalise_tech(self):
        """Rising Fed funds → tech gets -0.5."""
        env = _build_fred_env(fed_funds_change=0.25)
        assert env["fed_funds_rising"] is True
        result = score_ticker("NVDA", env)
        assert result["score"] == 4.5
        assert result["fed_funds_rising"] is True

    def test_rising_rates_penalise_fintech(self):
        """Rising Fed funds → fintech gets -0.5."""
        env = _build_fred_env(fed_funds_change=0.25)
        result = score_ticker("COIN", env)
        assert result["score"] == 4.5

    def test_rising_rates_no_effect_on_non_growth(self):
        """Rising Fed funds → non-growth ticker unaffected."""
        env = _build_fred_env(fed_funds_change=0.25)
        result = score_ticker("XOM", env)  # not in tech or fintech
        assert result["score"] == 5.0

    def test_flat_rates_no_penalty(self):
        """No rate change → no penalty."""
        env = _build_fred_env(fed_funds_change=0.0)
        assert env["fed_funds_rising"] is False
        result = score_ticker("NVDA", env)
        assert result["score"] == 5.0


# ---------------------------------------------------------------------------
# assess_environment — integration with FRED mocks
# ---------------------------------------------------------------------------

class TestAssessEnvironment:
    """Validates the full assess_environment logic with mocked FRED."""

    def _mock_fred(self, indicator_values: dict):
        """
        Return a side_effect function for requests.get that returns
        controlled FRED observations per series_id.
        """
        def side_effect(url, params=None, timeout=None):
            series_id = params.get("series_id", "") if params else ""
            values = indicator_values.get(series_id, [])
            mock_resp = MagicMock()
            mock_resp.ok = True
            mock_resp.json.return_value = {
                "observations": [_make_obs(v) for v in values]
            }
            return mock_resp
        return side_effect

    def test_rising_yields_produce_bearish_tech_signal(self):
        """10Y yield rising > 0.05 → tech sector signal is bearish."""
        vals = {
            "DGS10": ["4.60", "4.50"],  # +0.10 change
            "DGS2": ["4.20", "4.20"],
            "CPIAUCSL": ["3.2", "3.1"],
            "UNRATE": ["3.7", "3.8"],
            "FEDFUNDS": ["5.25", "5.25"],
            "VIXCLS": ["18.0", "17.5"],
        }
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    side_effect=self._mock_fred(vals)):
            env = assess_environment(FAKE_API_KEY)

        assert "tech" in env["sector_signals"]
        assert env["sector_signals"]["tech"]["bias"] == "bearish"
        assert "yield_curve_inverted" in env
        assert "fed_funds_rising" in env

    def test_high_vix_produces_bearish_signals_for_all_sectors(self):
        """VIX > 25 → bearish signal for all sectors (not just ETFs)."""
        vals = {
            "DGS10": ["4.50", "4.50"],
            "DGS2": ["4.20", "4.20"],
            "CPIAUCSL": ["3.2", "3.1"],
            "UNRATE": ["3.7", "3.8"],
            "FEDFUNDS": ["5.25", "5.25"],
            "VIXCLS": ["28.0", "22.0"],
        }
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    side_effect=self._mock_fred(vals)):
            env = assess_environment(FAKE_API_KEY)

        assert "etf" in env["sector_signals"]
        assert env["sector_signals"]["etf"]["bias"] == "bearish"
        assert "tech" in env["sector_signals"]
        assert env["sector_signals"]["tech"]["bias"] == "bearish"
        assert "consumer" in env["sector_signals"]
        assert env["sector_signals"]["consumer"]["bias"] == "bearish"

    def test_yield_curve_inversion_detected(self):
        """2Y > 10Y → yield_curve_inverted is True."""
        vals = {
            "DGS10": ["4.20", "4.20"],
            "DGS2": ["4.50", "4.50"],   # 2Y > 10Y
            "CPIAUCSL": ["3.2", "3.1"],
            "UNRATE": ["3.7", "3.8"],
            "FEDFUNDS": ["5.25", "5.25"],
            "VIXCLS": ["18.0", "17.5"],
        }
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    side_effect=self._mock_fred(vals)):
            env = assess_environment(FAKE_API_KEY)

        assert env["yield_curve_inverted"] is True

    def test_stale_data_handled_gracefully(self):
        """Stale '.' values are skipped; last valid observation used."""
        vals = {
            "DGS10": [".", "4.50", "4.45"],  # current=4.50, prev=4.45
            "DGS2": ["4.20", "4.20"],
            "CPIAUCSL": ["3.2", "3.1"],
            "UNRATE": ["3.7", "3.8"],
            "FEDFUNDS": ["5.25", "5.25"],
            "VIXCLS": ["18.0", "17.5"],
        }
        with patch("agents.macro.skills.macro_analysis.requests.get",
                    side_effect=self._mock_fred(vals)):
            env = assess_environment(FAKE_API_KEY)

        assert "10Y_YIELD" in env["indicators"]
        assert env["indicators"]["10Y_YIELD"]["current"] == 4.50


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, returns sorted list
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_missing_api_key_returns_neutral(self):
        """No FRED API key → all tickers get neutral 5.0."""
        results = run(["AAPL", "MSFT"], config={})
        assert len(results) == 2
        for r in results:
            assert r["score"] == 5.0
            assert r["direction"] == "HOLD"
            assert r["error"] == "missing_api_key"

    def test_returns_sorted_by_score_descending(self):
        """Results are sorted by score descending."""
        def mock_score(ticker, env):
            scores = {"NVDA": 3.5, "SPY": 6.5, "AAPL": 5.0}
            s = scores.get(ticker, 5.0)
            d = "CALL" if s >= 6 else "PUT" if s <= 4 else "HOLD"
            return {"ticker": ticker, "score": s, "direction": d,
                    "macro_reasons": []}

        with patch("agents.macro.skills.macro_analysis.assess_environment",
                    return_value=_build_fred_env()):
            with patch("agents.macro.skills.macro_analysis.score_ticker",
                        side_effect=mock_score):
                results = run(["NVDA", "SPY", "AAPL"],
                              config={"fred_api_key": "key"})

        assert results[0]["ticker"] == "SPY"
        assert results[0]["score"] >= results[1]["score"]
        assert results[1]["score"] >= results[2]["score"]

    def test_accepts_config_with_fred_key(self):
        """Config dict with fred_api_key is used for authentication."""
        with patch("agents.macro.skills.macro_analysis.assess_environment",
                    return_value=_build_fred_env()):
            with patch("agents.macro.skills.macro_analysis.score_ticker",
                        return_value={"ticker": "AAPL", "score": 5.0,
                                      "direction": "HOLD", "macro_reasons": []}):
                results = run(["AAPL"], config={"fred_api_key": "my_key"})
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

class TestScoreClamping:
    """Validates score stays in 0-10 range."""

    def test_score_clamped_at_10(self):
        """Multiple bullish signals should not exceed 10."""
        env = _build_fred_env()
        # COIN is in both fintech — give both bullish
        env["sector_signals"]["fintech"] = {"bias": "bullish", "reason": "test"}
        result = score_ticker("COIN", env)
        assert 0 <= result["score"] <= 10

    def test_score_clamped_at_0(self):
        """Multiple bearish signals should not go below 0."""
        env = _build_fred_env()
        env["sector_signals"]["tech"] = {"bias": "bearish", "reason": "test"}
        result = score_ticker("NVDA", env)
        assert 0 <= result["score"] <= 10


# ---------------------------------------------------------------------------
# Return schema
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_result_has_all_fields(self):
        env = _build_fred_env()
        result = score_ticker("AAPL", env)
        required_keys = {"ticker", "score", "direction", "macro_reasons",
                         "yield_10y", "yield_2y", "vix", "fed_funds",
                         "cpi", "unemployment", "yield_curve_inverted",
                         "fed_funds_rising"}
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# write_to_shared_memory — delegates to shared_memory_io
# ---------------------------------------------------------------------------

class TestWriteToSharedMemory:
    """Validates shared memory integration."""

    def test_writes_and_reads_back(self, tmp_path):
        """Round-trip: write results, read them back via shared_memory_io."""
        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

            sample = [
                {"ticker": "NVDA", "score": 3.5, "direction": "PUT",
                 "macro_reasons": ["Rising yields"]},
                {"ticker": "SPY", "score": 6.5, "direction": "CALL",
                 "macro_reasons": ["Low VIX"]},
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("macro", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "macro"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 2
            assert parsed["results"][0]["ticker"] == "NVDA"
