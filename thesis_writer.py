"""
Claude Thesis Writer via Amazon Bedrock

Generates a concise 2-sentence thesis for each top pick using Claude Sonnet
via Amazon Bedrock.  Gracefully returns an empty string if Bedrock is
unavailable or credentials are not configured.

This module is optional — if it fails, picks are returned without a thesis.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250514"
BEDROCK_REGION = "us-east-1"


def generate_thesis(pick: dict) -> str:
    """
    Generate a 2-sentence thesis for a single pick using Claude via Bedrock.

    Args:
        pick: A pick dict containing at minimum:
            - ticker (str)
            - composite_score (float)
            - direction (str): "CALL", "PUT", or "HOLD"
            - confidence (str): "HIGH", "MEDIUM", or "LOW"
            - agent_scores (dict): per-agent score breakdown

    Returns:
        A thesis string (2 sentences max), or empty string on any failure.
    """
    try:
        import boto3
    except ImportError:
        logger.debug("boto3 not installed — skipping thesis generation")
        return ""

    ticker = pick.get("ticker", "???")
    score = pick.get("composite_score", 5.0)
    direction = pick.get("direction", "HOLD")
    confidence = pick.get("confidence", "LOW")
    agent_scores = pick.get("agent_scores", {})

    # Build agent data summary for the prompt
    agent_lines = []
    for agent_id, info in agent_scores.items():
        if isinstance(info, dict):
            a_score = info.get("score", 5.0)
            a_dir = info.get("direction", "HOLD")
            agent_lines.append(f"  - {agent_id}: score={a_score}, direction={a_dir}")
        else:
            agent_lines.append(f"  - {agent_id}: {info}")

    agent_data_str = "\n".join(agent_lines) if agent_lines else "  No agent data available."

    prompt = (
        f"You are a market analyst. Summarize why {ticker} scored {score:.1f} "
        f"({direction}). Use ONLY the agent data below. Do not add opinions, "
        f"predictions, or external knowledge. 2 sentences max.\n\n"
        f"Ticker: {ticker}\n"
        f"Composite Score: {score:.1f}\n"
        f"Direction: {direction}\n"
        f"Confidence: {confidence}\n"
        f"Agent Scores:\n{agent_data_str}"
    )

    try:
        client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 150,
            "messages": [
                {"role": "user", "content": prompt}
            ],
        })

        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        result = json.loads(response["body"].read())
        content = result.get("content", [])
        if content and isinstance(content, list):
            thesis = content[0].get("text", "").strip()
            logger.info("Generated thesis for %s: %s", ticker, thesis[:80])
            return thesis

        return ""

    except Exception as exc:
        logger.debug("Thesis generation failed for %s: %s", ticker, exc)
        return ""


def attach_theses(picks: list[dict]) -> list[dict]:
    """
    Generate and attach a thesis to each pick in the list.

    Adds a "thesis" key to each pick dict. If generation fails for a pick,
    the thesis will be an empty string.

    Args:
        picks: List of pick dicts (options or stocks).

    Returns:
        The same list with "thesis" keys added.
    """
    for pick in picks:
        try:
            pick["thesis"] = generate_thesis(pick)
        except Exception as exc:
            logger.debug("Thesis attachment failed for %s: %s",
                         pick.get("ticker", "???"), exc)
            pick["thesis"] = ""
    return picks
