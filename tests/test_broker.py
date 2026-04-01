"""
Tests for broker integration: AlpacaClient and OrderManager.

Requirements: 14.1, 14.3, 14.7, 16.3, 16.4, 21.2
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from broker.alpaca_client import AlpacaClient


# ---------------------------------------------------------------------------
# AlpacaClient — mode selection (Req 14.1)
# ---------------------------------------------------------------------------

class TestAlpacaClientMode:
    def test_paper_mode_default(self):
        c = AlpacaClient(api_key="k", secret_key="s")
        assert c.mode == "paper"
        assert c.base_url == "https://paper-api.alpaca.markets"

    def test_paper_mode_explicit(self):
        c = AlpacaClient(api_key="k", secret_key="s", mode="paper")
        assert c.base_url == "https://paper-api.alpaca.markets"

    def test_live_mode(self):
        c = AlpacaClient(api_key="k", secret_key="s", mode="live")
        assert c.mode == "live"
        assert c.base_url == "https://api.alpaca.markets"

    def test_invalid_mode_falls_back_to_paper(self):
        c = AlpacaClient(api_key="k", secret_key="s", mode="invalid")
        assert c.mode == "paper"
        assert c.base_url == "https://paper-api.alpaca.markets"

    def test_mode_from_env(self):
        with patch.dict(os.environ, {"ALPACA_MODE": "live"}):
            c = AlpacaClient(api_key="k", secret_key="s")
            assert c.mode == "live"


# ---------------------------------------------------------------------------
# AlpacaClient — option symbol construction (Req 14.3)
# ---------------------------------------------------------------------------

class TestOptionSymbol:
    def test_call_symbol(self):
        sym = AlpacaClient._build_option_symbol("NVDA", 128.0, "2026-04-04", "CALL")
        assert sym == "NVDA260404C00128000"

    def test_put_symbol(self):
        sym = AlpacaClient._build_option_symbol("AAPL", 175.5, "2026-01-17", "PUT")
        assert sym == "AAPL260117P00175500"

    def test_lowercase_direction(self):
        sym = AlpacaClient._build_option_symbol("MSFT", 400.0, "2026-06-20", "call")
        assert sym == "MSFT260620C00400000"

    def test_single_char_direction(self):
        sym = AlpacaClient._build_option_symbol("TSLA", 250.0, "2026-03-15", "C")
        assert sym == "TSLA260315C00250000"

    def test_fractional_strike(self):
        sym = AlpacaClient._build_option_symbol("SPY", 450.25, "2026-02-28", "PUT")
        assert sym == "SPY260228P00450250"

    def test_ticker_uppercased(self):
        sym = AlpacaClient._build_option_symbol("nvda", 100.0, "2026-01-01", "CALL")
        assert sym.startswith("NVDA")


# ---------------------------------------------------------------------------
# AlpacaClient — error response handling (Req 14.7)
# ---------------------------------------------------------------------------

class TestErrorResponse:
    def test_error_response_with_json_body(self):
        resp = MagicMock()
        resp.status_code = 403
        resp.json.return_value = {"message": "forbidden"}
        resp.text = '{"message": "forbidden"}'

        result = AlpacaClient._error_response(resp)
        assert result["success"] is False
        assert result["status_code"] == 403
        assert result["error"] == "forbidden"

    def test_error_response_with_plain_text(self):
        resp = MagicMock()
        resp.status_code = 500
        resp.json.side_effect = ValueError("not json")
        resp.text = "Internal Server Error"

        result = AlpacaClient._error_response(resp)
        assert result["success"] is False
        assert result["status_code"] == 500
        assert result["error"] == "Internal Server Error"


# ---------------------------------------------------------------------------
# AlpacaClient — order placement with mocked requests (Req 14.2)
# ---------------------------------------------------------------------------

class TestOrderPlacement:
    def _make_client(self):
        return AlpacaClient(api_key="test_key", secret_key="test_secret", mode="paper")

    @patch("broker.alpaca_client.requests.post")
    def test_buy_stock_market_order(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "order-123",
                "status": "accepted",
                "symbol": "NVDA",
                "side": "buy",
                "qty": "10",
                "type": "market",
                "filled_avg_price": None,
            },
        )
        c = self._make_client()
        result = c.buy_stock("NVDA", 10)
        assert result["success"] is True
        assert result["order_id"] == "order-123"
        assert result["symbol"] == "NVDA"
        assert result["side"] == "buy"

        # Verify the request was made to paper URL
        call_args = mock_post.call_args
        assert "paper-api.alpaca.markets" in call_args[0][0]

    @patch("broker.alpaca_client.requests.post")
    def test_buy_stock_limit_order(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "order-456",
                "status": "accepted",
                "symbol": "AAPL",
                "side": "buy",
                "qty": "5",
                "type": "limit",
                "filled_avg_price": None,
            },
        )
        c = self._make_client()
        result = c.buy_stock("AAPL", 5, limit_price=175.50)
        assert result["success"] is True
        # Verify limit_price was included in the order
        posted_json = mock_post.call_args[1]["json"]
        assert posted_json["limit_price"] == "175.5"
        assert posted_json["type"] == "limit"

    @patch("broker.alpaca_client.requests.post")
    def test_sell_stock(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "order-789",
                "status": "accepted",
                "symbol": "MSFT",
                "side": "sell",
                "qty": "3",
                "type": "market",
                "filled_avg_price": None,
            },
        )
        c = self._make_client()
        result = c.sell_stock("MSFT", 3)
        assert result["success"] is True
        assert result["side"] == "sell"

    @patch("broker.alpaca_client.requests.post")
    def test_order_failure_returns_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 422
        mock_resp.json.return_value = {"message": "insufficient buying power"}
        mock_resp.text = '{"message": "insufficient buying power"}'
        mock_post.return_value = mock_resp

        c = self._make_client()
        result = c.buy_stock("NVDA", 1000)
        assert result["success"] is False
        assert result["status_code"] == 422
        assert "insufficient" in result["error"]

    @patch("broker.alpaca_client.requests.post")
    def test_order_exception_returns_error(self, mock_post):
        mock_post.side_effect = ConnectionError("network down")
        c = self._make_client()
        result = c.buy_stock("NVDA", 1)
        assert result["success"] is False
        assert "network down" in result["error"]

    @patch("broker.alpaca_client.requests.post")
    def test_buy_option(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "id": "opt-001",
                "status": "accepted",
                "symbol": "NVDA260404C00128000",
                "side": "buy",
                "qty": "2",
                "type": "market",
                "filled_avg_price": None,
            },
        )
        c = self._make_client()
        result = c.buy_option("NVDA", 128.0, "2026-04-04", "CALL", 2)
        assert result["success"] is True
        posted_json = mock_post.call_args[1]["json"]
        assert posted_json["symbol"] == "NVDA260404C00128000"
        assert posted_json["qty"] == "2"

    @patch("broker.alpaca_client.requests.post")
    def test_timeout_on_order(self, mock_post):
        """Verify 10-second timeout is passed to requests."""
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {"id": "x", "status": "ok", "symbol": "X",
                          "side": "buy", "qty": "1", "type": "market",
                          "filled_avg_price": None},
        )
        c = self._make_client()
        c.buy_stock("X", 1)
        assert mock_post.call_args[1]["timeout"] == 10


# ---------------------------------------------------------------------------
# AlpacaClient — positions and account (Req 14.4, 14.5)
# ---------------------------------------------------------------------------

class TestPositionsAndAccount:
    def _make_client(self):
        return AlpacaClient(api_key="k", secret_key="s", mode="paper")

    @patch("broker.alpaca_client.requests.get")
    def test_get_positions(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: [
                {
                    "symbol": "NVDA",
                    "qty": "10",
                    "side": "long",
                    "avg_entry_price": "125.00",
                    "current_price": "130.00",
                    "market_value": "1300.00",
                    "unrealized_pl": "50.00",
                    "unrealized_plpc": "0.04",
                }
            ],
        )
        c = self._make_client()
        positions = c.get_positions()
        assert isinstance(positions, list)
        assert len(positions) == 1
        assert positions[0]["symbol"] == "NVDA"
        assert positions[0]["qty"] == 10
        assert positions[0]["unrealized_plpc"] == 4.0  # 0.04 * 100

    @patch("broker.alpaca_client.requests.get")
    def test_get_account(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "cash": "5000.00",
                "buying_power": "10000.00",
                "portfolio_value": "15000.00",
                "equity": "15000.00",
                "last_equity": "14800.00",
            },
        )
        c = self._make_client()
        acct = c.get_account()
        assert acct["cash"] == 5000.0
        assert acct["daily_pnl"] == 200.0
        assert acct["mode"] == "paper"

    @patch("broker.alpaca_client.requests.delete")
    def test_close_all(self, mock_delete):
        mock_delete.return_value = MagicMock(ok=True)
        c = self._make_client()
        result = c.close_all()
        assert result["success"] is True


# ---------------------------------------------------------------------------
# OrderManager — trade logging (Req 16.3, 16.4)
# ---------------------------------------------------------------------------

class TestOrderManagerTradeLogging:
    def test_log_and_load_trade(self, tmp_path):
        with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
            from broker.order_manager import _log_trade, _load_trades_history

            _log_trade(
                ticker="NVDA",
                action="BUY",
                qty=10,
                price=128.50,
                order_result={"order_id": "ord-1", "status": "accepted"},
            )
            trades = _load_trades_history()
            assert len(trades) == 1
            t = trades[0]
            assert t["ticker"] == "NVDA"
            assert t["action"] == "BUY"
            assert t["qty"] == 10
            assert t["price"] == 128.50
            assert t["total_cost"] == 1285.0
            assert t["order_id"] == "ord-1"

    def test_log_option_trade(self, tmp_path):
        with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
            from broker.order_manager import _log_trade, _load_trades_history

            _log_trade(
                ticker="AAPL",
                action="BUY_CALL",
                qty=2,
                price=None,
                order_result={"order_id": "opt-1", "status": "accepted"},
                option_details={
                    "strike": 175.0,
                    "expiry": "2026-01-17",
                    "direction": "CALL",
                    "contracts": 2,
                },
            )
            trades = _load_trades_history()
            assert len(trades) == 1
            assert trades[0]["option_details"]["strike"] == 175.0

    def test_update_trade_close(self, tmp_path):
        with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
            from broker.order_manager import (
                _log_trade,
                update_trade_close,
                _load_trades_history,
            )

            _log_trade(
                ticker="MSFT",
                action="BUY",
                qty=5,
                price=400.0,
                order_result={"order_id": "ord-close", "status": "filled"},
            )
            updated = update_trade_close("ord-close", 410.0, 50.0)
            assert updated is True

            trades = _load_trades_history()
            assert trades[0]["close_price"] == 410.0
            assert trades[0]["realized_pnl"] == 50.0
            assert "close_timestamp" in trades[0]

    def test_update_trade_close_not_found(self, tmp_path):
        with patch.dict(os.environ, {"SHARED_MEMORY_PATH": str(tmp_path)}):
            from broker.order_manager import update_trade_close
            assert update_trade_close("nonexistent", 100.0, 0.0) is False


# ---------------------------------------------------------------------------
# OrderManager — confirmation formatting
# ---------------------------------------------------------------------------

class TestConfirmationFormatting:
    def test_buy_confirmation_with_price(self):
        from broker.order_manager import format_buy_confirmation
        msg = format_buy_confirmation("NVDA", 10, estimated_price=128.50)
        assert "BUY" in msg
        assert "NVDA" in msg
        assert "10" in msg
        assert "$128.50" in msg
        assert "$1285.00" in msg

    def test_buy_confirmation_market(self):
        from broker.order_manager import format_buy_confirmation
        msg = format_buy_confirmation("AAPL", 5)
        assert "market" in msg.lower()

    def test_sell_confirmation(self):
        from broker.order_manager import format_sell_confirmation
        msg = format_sell_confirmation("TSLA", 3, estimated_price=250.0)
        assert "SELL" in msg
        assert "TSLA" in msg

    def test_option_confirmation(self):
        from broker.order_manager import format_option_confirmation
        msg = format_option_confirmation("NVDA", 128.0, "2026-04-04", "CALL", 2, 2.45)
        assert "CALL" in msg
        assert "$128.00" in msg
        assert "$490.00" in msg

    def test_close_all_confirmation(self):
        from broker.order_manager import format_close_all_confirmation
        msg = format_close_all_confirmation()
        assert "Close All" in msg
        assert "liquidate" in msg.lower()


# ---------------------------------------------------------------------------
# OrderManager — rejection handling (Req 14.7, 21.2)
# ---------------------------------------------------------------------------

class TestRejectionHandling:
    def test_insufficient_funds_suggestion(self):
        from broker.order_manager import _handle_rejection
        result = _handle_rejection({
            "success": False,
            "status_code": 422,
            "error": "insufficient buying power",
        })
        assert "Reduce quantity" in result["suggestion"]

    def test_symbol_not_found_suggestion(self):
        from broker.order_manager import _handle_rejection
        result = _handle_rejection({
            "success": False,
            "status_code": 404,
            "error": "symbol not found",
        })
        assert "ticker symbol" in result["suggestion"].lower()

    def test_rate_limit_suggestion(self):
        from broker.order_manager import _handle_rejection
        result = _handle_rejection({
            "success": False,
            "status_code": 429,
            "error": "too many requests",
        })
        assert "Rate limit" in result["suggestion"]

    def test_format_rejection_message(self):
        from broker.order_manager import format_rejection_message
        msg = format_rejection_message({
            "user_message": "❌ Order rejected: insufficient buying power",
            "suggestion": "💡 Reduce quantity or add funds.",
        })
        assert "❌" in msg
        assert "Reduce quantity" in msg
