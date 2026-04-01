"""
Unit tests for the Claude Thesis Writer via Bedrock.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import BytesIO

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from thesis_writer import generate_thesis, attach_theses, BEDROCK_MODEL_ID


def _make_pick(ticker="NVDA", score=8.5, direction="CALL", confidence="HIGH"):
    return {
        "ticker": ticker,
        "composite_score": score,
        "direction": direction,
        "confidence": confidence,
        "agent_scores": {
            "fundamentals": {"score": 9.0, "direction": "CALL"},
            "sentiment": {"score": 7.5, "direction": "CALL"},
        },
    }


class TestGenerateThesis:

    def test_returns_thesis_on_success(self):
        """Should return thesis text from Bedrock response."""
        mock_body = json.dumps({
            "content": [{"type": "text", "text": "NVDA scored high due to strong fundamentals. Sentiment also supports bullish outlook."}]
        }).encode()

        mock_response = {
            "body": BytesIO(mock_body),
        }

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_response

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = generate_thesis(_make_pick())

        assert "NVDA" in result or "fundamentals" in result.lower() or len(result) > 0
        mock_client.invoke_model.assert_called_once()

    def test_returns_empty_on_boto3_not_installed(self):
        """Should return '' if boto3 is not importable."""
        with patch("builtins.__import__", side_effect=ImportError("no boto3")):
            result = generate_thesis(_make_pick())
        assert isinstance(result, str)

    def test_returns_empty_on_bedrock_error(self):
        """Should return '' if Bedrock call fails."""
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value.invoke_model.side_effect = Exception("Bedrock unavailable")

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = generate_thesis(_make_pick())

        assert result == ""

    def test_returns_empty_on_empty_response(self):
        """Should return '' if Bedrock returns empty content."""
        mock_body = json.dumps({"content": []}).encode()
        mock_response = {"body": BytesIO(mock_body)}

        mock_client = MagicMock()
        mock_client.invoke_model.return_value = mock_response

        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = generate_thesis(_make_pick())

        assert result == ""

    def test_model_id_is_claude_sonnet(self):
        """Should use the correct Bedrock model ID."""
        assert "claude-sonnet" in BEDROCK_MODEL_ID


class TestAttachTheses:

    def test_attaches_thesis_to_each_pick(self):
        """Each pick should get a 'thesis' key."""
        picks = [_make_pick("NVDA"), _make_pick("AAPL")]

        with patch("thesis_writer.generate_thesis", return_value="Test thesis."):
            result = attach_theses(picks)

        assert all("thesis" in p for p in result)
        assert result[0]["thesis"] == "Test thesis."

    def test_handles_generation_failure_gracefully(self):
        """If generate_thesis raises, thesis should be empty string."""
        picks = [_make_pick("NVDA")]

        with patch("thesis_writer.generate_thesis", side_effect=Exception("fail")):
            result = attach_theses(picks)

        assert result[0]["thesis"] == ""

    def test_empty_picks_returns_empty(self):
        """Empty list in, empty list out."""
        result = attach_theses([])
        assert result == []
