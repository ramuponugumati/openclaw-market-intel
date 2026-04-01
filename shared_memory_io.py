"""
Shared Memory I/O Module

Provides read/write utilities for the OpenClaw Market Intel shared memory system.
All agents use this module to publish results, read other agents' outputs,
manage run manifests, and access shared configuration (watchlist, weights, horizon state).

The shared memory base path is configurable via the SHARED_MEMORY_PATH environment variable,
defaulting to the local shared_memory/ directory relative to this file.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _get_base_path() -> Path:
    """Return the shared memory base path, configurable via SHARED_MEMORY_PATH env var."""
    env_path = os.environ.get("SHARED_MEMORY_PATH")
    if env_path:
        return Path(env_path)
    return Path(__file__).parent / "shared_memory"


def _ensure_dir(path: Path) -> None:
    """Create directory and parents if they don't exist."""
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Agent Result Files
# ---------------------------------------------------------------------------

def write_agent_result(agent_id: str, run_id: str, results: list[dict]) -> str:
    """
    Write agent analysis results as a markdown file with YAML front matter
    and embedded JSON raw data.

    Args:
        agent_id: The agent identifier (e.g. 'fundamentals', 'sentiment').
        run_id: The run identifier (e.g. '20260115_053000').
        results: List of per-ticker result dicts, each containing at minimum
                 'ticker', 'score', and 'direction'.

    Returns:
        The file path of the written result file.
    """
    base = _get_base_path()
    runs_dir = base / "runs"
    _ensure_dir(runs_dir)

    filename = f"{agent_id}_{run_id}.md"
    filepath = runs_dir / filename
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tickers_analyzed = len(results)

    # Build markdown scores table
    table_rows = []
    for r in results:
        ticker = r.get("ticker", "???")
        score = r.get("score", 5.0)
        direction = r.get("direction", "HOLD")
        # Collect any extra keys as key metrics summary
        skip_keys = {"ticker", "score", "direction"}
        metrics = ", ".join(
            f"{k}:{v}" for k, v in r.items() if k not in skip_keys
        )
        table_rows.append(f"| {ticker} | {score} | {direction} | {metrics} |")

    scores_table = "\n".join(table_rows)
    raw_json = json.dumps(results, indent=2, default=str)

    content = f"""# {agent_id.replace('_', ' ').title()} Analysis Results
<!-- run_id: {run_id} -->
<!-- agent_id: {agent_id} -->
<!-- timestamp: {timestamp} -->
<!-- status: complete -->
<!-- tickers_analyzed: {tickers_analyzed} -->

## Scores

| Ticker | Score | Direction | Key Metrics |
|--------|-------|-----------|-------------|
{scores_table}

## Raw Data

```json
{raw_json}
```
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def read_agent_result(agent_id: str, run_id: str) -> Optional[dict]:
    """
    Read and parse a single agent result file.

    Returns a dict with keys: agent_id, run_id, timestamp, status,
    tickers_analyzed, and results (the parsed JSON data).
    Returns None if the file does not exist.
    """
    base = _get_base_path()
    filepath = base / "runs" / f"{agent_id}_{run_id}.md"

    if not filepath.exists():
        return None

    content = filepath.read_text(encoding="utf-8")
    return _parse_agent_result(content)


def _parse_agent_result(content: str) -> dict:
    """Parse an agent result markdown file into a structured dict."""
    metadata: dict[str, Any] = {}

    # Extract YAML front matter from HTML comments
    for match in re.finditer(r"<!--\s*(\w+):\s*(.+?)\s*-->", content):
        key, value = match.group(1), match.group(2)
        metadata[key] = value

    # Extract embedded JSON from fenced code block
    json_match = re.search(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
    results = []
    if json_match:
        try:
            results = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            results = []

    # Coerce tickers_analyzed to int
    tickers_str = metadata.get("tickers_analyzed", "0")
    try:
        tickers_analyzed = int(tickers_str)
    except (ValueError, TypeError):
        tickers_analyzed = 0

    return {
        "agent_id": metadata.get("agent_id", ""),
        "run_id": metadata.get("run_id", ""),
        "timestamp": metadata.get("timestamp", ""),
        "status": metadata.get("status", ""),
        "tickers_analyzed": tickers_analyzed,
        "results": results,
    }


def read_all_results(run_id: str) -> dict[str, dict]:
    """
    Read all agent result files for a given run_id.

    Returns a dict mapping agent_id -> parsed result dict.
    """
    base = _get_base_path()
    runs_dir = base / "runs"

    if not runs_dir.exists():
        return {}

    collected: dict[str, dict] = {}
    pattern = f"*_{run_id}.md"
    for filepath in runs_dir.glob(pattern):
        content = filepath.read_text(encoding="utf-8")
        parsed = _parse_agent_result(content)
        agent_id = parsed.get("agent_id", "")
        if agent_id:
            collected[agent_id] = parsed

    return collected


# ---------------------------------------------------------------------------
# Run Manifests
# ---------------------------------------------------------------------------

def write_manifest(run_id: str, run_type: str) -> str:
    """
    Create a run manifest markdown file.

    Args:
        run_id: The run identifier.
        run_type: The type of run (e.g. 'morning_analysis', 'eod_recap', 'ad_hoc').

    Returns:
        The file path of the written manifest.
    """
    base = _get_base_path()
    runs_dir = base / "runs"
    _ensure_dir(runs_dir)

    filepath = runs_dir / f"manifest_{run_id}.md"
    launched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    expected_agents = "fundamentals,sentiment,macro,news,technical,premarket,congress"

    agent_rows = []
    for agent in expected_agents.split(","):
        agent_rows.append(f"| {agent} | pending | - |")

    agent_table = "\n".join(agent_rows)

    content = f"""# Run Manifest
<!-- run_id: {run_id} -->
<!-- type: {run_type} -->
<!-- launched_at: {launched_at} -->
<!-- expected_agents: {expected_agents} -->
<!-- timeout_s: 120 -->

## Agent Status

| Agent | Status | Completed At |
|-------|--------|-------------|
{agent_table}
"""
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def update_manifest_status(run_id: str, agent_id: str, status: str) -> None:
    """
    Update a specific agent's status in the run manifest.

    Args:
        run_id: The run identifier.
        agent_id: The agent whose status to update.
        status: New status string (e.g. 'complete', 'timed_out', 'error').
    """
    base = _get_base_path()
    filepath = base / "runs" / f"manifest_{run_id}.md"

    if not filepath.exists():
        return

    content = filepath.read_text(encoding="utf-8")
    completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Replace the agent's row in the status table
    old_pattern = rf"\| {re.escape(agent_id)} \| \w+ \| [^\|]+ \|"
    new_row = f"| {agent_id} | {status} | {completed_at} |"
    updated = re.sub(old_pattern, new_row, content)

    filepath.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------------------
# Watchlist Configuration
# ---------------------------------------------------------------------------

def load_watchlist() -> dict:
    """
    Load the watchlist configuration from shared_memory/config/watchlist.json.

    Returns the parsed JSON dict with keys: updated, sectors, etf_tickers, all_tickers.
    """
    base = _get_base_path()
    filepath = base / "config" / "watchlist.json"
    return _load_json(filepath)


def save_watchlist(data: dict) -> None:
    """
    Save the watchlist configuration to shared_memory/config/watchlist.json.

    Automatically updates the 'updated' timestamp.
    """
    base = _get_base_path()
    config_dir = base / "config"
    _ensure_dir(config_dir)
    filepath = config_dir / "watchlist.json"
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_json(filepath, data)


# ---------------------------------------------------------------------------
# Learned Weights
# ---------------------------------------------------------------------------

def load_weights() -> dict:
    """
    Load learned agent weights from shared_memory/weights/learned_weights.json.

    Returns the parsed JSON dict with keys: updated, weights, accuracy_data, days_evaluated.
    """
    base = _get_base_path()
    filepath = base / "weights" / "learned_weights.json"
    return _load_json(filepath)


def save_weights(data: dict) -> None:
    """
    Save learned agent weights to shared_memory/weights/learned_weights.json.

    Automatically updates the 'updated' timestamp.
    """
    base = _get_base_path()
    weights_dir = base / "weights"
    _ensure_dir(weights_dir)
    filepath = weights_dir / "learned_weights.json"
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_json(filepath, data)


# ---------------------------------------------------------------------------
# Horizon State
# ---------------------------------------------------------------------------

def load_horizon_state() -> dict:
    """
    Load the trading horizon state from shared_memory/config/horizon_state.json.

    Returns the parsed JSON dict with keys: current_mode, consecutive_days_at_threshold,
    accuracy_history, mode_transitions.
    """
    base = _get_base_path()
    filepath = base / "config" / "horizon_state.json"
    return _load_json(filepath)


def save_horizon_state(data: dict) -> None:
    """
    Save the trading horizon state to shared_memory/config/horizon_state.json.
    """
    base = _get_base_path()
    config_dir = base / "config"
    _ensure_dir(config_dir)
    filepath = config_dir / "horizon_state.json"
    _save_json(filepath, data)


# ---------------------------------------------------------------------------
# Internal JSON helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared Memory Cleanup (Requirement 2.6, 16.5)
# ---------------------------------------------------------------------------

# Retention periods
RUNS_RETENTION_DAYS = 30
PICKS_RETENTION_DAYS = 365


def cleanup_shared_memory() -> dict:
    """
    Remove stale files from shared memory to control disk usage.

    - shared_memory/runs/ files older than 30 days are deleted (Req 2.6).
    - picks_history.json entries older than 365 days are pruned (Req 16.5).

    Returns:
        Dict summarising what was cleaned: runs_deleted, picks_pruned.
    """
    import logging
    from datetime import date, timedelta

    logger = logging.getLogger(__name__)
    base = _get_base_path()
    today = date.today()

    # --- 1. Prune shared_memory/runs/ files older than 30 days ---
    runs_dir = base / "runs"
    runs_deleted = 0
    if runs_dir.exists():
        cutoff = today - timedelta(days=RUNS_RETENTION_DAYS)
        for filepath in runs_dir.iterdir():
            if not filepath.is_file():
                continue
            try:
                # Use file modification time as the age indicator
                mtime = datetime.fromtimestamp(
                    filepath.stat().st_mtime, tz=timezone.utc
                )
                if mtime.date() < cutoff:
                    filepath.unlink()
                    runs_deleted += 1
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", filepath, exc)

    # --- 2. Prune picks_history.json entries older than 365 days ---
    picks_pruned = 0
    picks_path = base / "picks" / "picks_history.json"
    if picks_path.exists():
        try:
            raw = json.loads(picks_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                cutoff_str = str(today - timedelta(days=PICKS_RETENTION_DAYS))
                kept = [e for e in raw if e.get("date", "") >= cutoff_str]
                picks_pruned = len(raw) - len(kept)
                if picks_pruned > 0:
                    picks_path.write_text(
                        json.dumps(kept, indent=2, default=str) + "\n",
                        encoding="utf-8",
                    )
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to prune picks history: %s", exc)

    logger.info(
        "Shared memory cleanup: %d run files deleted, %d pick entries pruned",
        runs_deleted,
        picks_pruned,
    )
    return {"runs_deleted": runs_deleted, "picks_pruned": picks_pruned}


# ---------------------------------------------------------------------------
# Internal JSON helpers
# ---------------------------------------------------------------------------

def _load_json(filepath: Path) -> dict:
    """Load and parse a JSON file. Returns empty dict if file doesn't exist."""
    if not filepath.exists():
        return {}
    content = filepath.read_text(encoding="utf-8")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def _save_json(filepath: Path, data: dict) -> None:
    """Write a dict as formatted JSON to a file."""
    filepath.write_text(
        json.dumps(data, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
