"""
Fleet Launcher Skill

Launches all 7 sub-agents concurrently using asyncio, writes a run manifest
to shared memory, and polls for completion with configurable timeout.

Each sub-agent reads the watchlist from shared_memory/config/watchlist.json,
runs its analysis, and writes results to shared_memory/runs/.

Requirements: 1.3, 1.4, 2.1, 2.3, 2.4, 2.5, 21.3
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach shared_memory_io
# and the sub-agent skill modules.
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io  # noqa: E402

logger = logging.getLogger(__name__)

# The 7 sub-agents launched during a fleet run (options_chain is invoked
# separately after pick selection, not during the initial fleet sweep).
SUB_AGENTS = [
    "fundamentals",
    "sentiment",
    "macro",
    "news",
    "technical",
    "premarket",
    "congress",
]

# Maps agent id → module path relative to project root
_AGENT_MODULE_MAP: dict[str, str] = {
    "fundamentals": "agents.fundamentals.skills.fundamentals_analysis",
    "sentiment":    "agents.sentiment.skills.sentiment_analysis",
    "macro":        "agents.macro.skills.macro_analysis",
    "news":         "agents.news.skills.news_analysis",
    "technical":    "agents.technical.skills.technical_analysis",
    "premarket":    "agents.premarket.skills.premarket_analysis",
    "congress":     "agents.congress.skills.congress_analysis",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _import_agent_module(agent_id: str) -> Any:
    """Dynamically import a sub-agent's skill module."""
    import importlib

    module_path = _AGENT_MODULE_MAP.get(agent_id)
    if not module_path:
        raise ValueError(f"Unknown agent id: {agent_id}")
    return importlib.import_module(module_path)


async def _run_agent(
    agent_id: str,
    run_id: str,
    watchlist: list[str],
    config: dict | None,
) -> dict[str, str]:
    """
    Run a single sub-agent in a thread executor and write results to shared memory.

    Returns a status dict: {"agent_id": ..., "status": "complete"|"error", ...}.
    """
    loop = asyncio.get_running_loop()

    def _execute() -> str:
        mod = _import_agent_module(agent_id)
        results = mod.run(watchlist, config)
        mod.write_to_shared_memory(run_id, results)
        return "complete"

    try:
        status = await loop.run_in_executor(None, _execute)
        logger.info("Agent %s completed for run %s", agent_id, run_id)
        return {"agent_id": agent_id, "status": status}
    except Exception as exc:
        logger.error("Agent %s failed for run %s: %s", agent_id, run_id, exc)
        return {"agent_id": agent_id, "status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def launch_fleet(
    run_id: str,
    config: dict | None = None,
    run_type: str = "morning_analysis",
) -> dict[str, str]:
    """
    Launch all 7 sub-agents concurrently and return their launch statuses.

    1. Writes a run manifest to shared memory.
    2. Loads the watchlist from shared_memory/config/watchlist.json.
    3. Launches every sub-agent concurrently via asyncio.
    4. Returns a dict mapping agent_id → final status string.

    Args:
        run_id:   Unique identifier for this run (e.g. '20260115_053000').
        config:   Optional config dict forwarded to each agent's ``run()``.
        run_type: Manifest run type label (default 'morning_analysis').

    Returns:
        ``{agent_id: status}`` where status is 'complete' or 'error'.
    """
    # Step 1 — write manifest
    manifest_path = shared_memory_io.write_manifest(run_id, run_type)
    logger.info("Manifest written: %s", manifest_path)

    # Step 2 — load watchlist
    watchlist_data = shared_memory_io.load_watchlist()
    watchlist: list[str] = watchlist_data.get("all_tickers", [])
    if not watchlist:
        logger.error("Watchlist is empty — aborting fleet launch")
        return {agent: "error" for agent in SUB_AGENTS}

    logger.info(
        "Launching %d agents for run %s (%d tickers)",
        len(SUB_AGENTS),
        run_id,
        len(watchlist),
    )

    # Step 3 — launch all agents concurrently
    async def _launch_all() -> list[dict[str, str]]:
        tasks = [
            _run_agent(agent_id, run_id, watchlist, config)
            for agent_id in SUB_AGENTS
        ]
        return await asyncio.gather(*tasks)

    results = asyncio.run(_launch_all())

    # Step 4 — build status map and update manifest
    status_map: dict[str, str] = {}
    for r in results:
        aid = r["agent_id"]
        st = r["status"]
        status_map[aid] = st
        shared_memory_io.update_manifest_status(run_id, aid, st)

    logger.info("Fleet launch complete: %s", status_map)
    return status_map


def poll_completion(
    run_id: str,
    timeout_s: int = 120,
    interval_s: int = 5,
) -> dict:
    """
    Poll shared memory for sub-agent result files until all 7 are present
    or the timeout is reached.

    Behaviour:
    - Checks ``shared_memory/runs/`` every *interval_s* seconds for files
      matching ``{agent_id}_{run_id}.md`` for each of the 7 sub-agents.
    - As each result file appears, reads it and updates the run manifest
      status to 'complete'.
    - If all 7 files are found before *timeout_s*, returns all results
      immediately.
    - If the timeout expires, proceeds with whatever results are available
      and marks missing agents as 'timed_out' in the manifest.

    Args:
        run_id:     The run identifier to poll for.
        timeout_s:  Maximum seconds to wait (default 120).
        interval_s: Seconds between polls (default 5).

    Returns:
        A dict with keys:
        - ``results``: ``{agent_id: parsed_result_dict}`` for all agents
          that completed.
        - ``timed_out``: list of agent_ids that did not complete in time.
        - ``all_complete``: bool indicating whether every agent finished.
    """
    deadline = time.monotonic() + timeout_s
    collected: dict[str, dict] = {}
    remaining = set(SUB_AGENTS)

    logger.info(
        "Polling for %d agent results (run %s, timeout %ds, interval %ds)",
        len(SUB_AGENTS),
        run_id,
        timeout_s,
        interval_s,
    )

    while remaining and time.monotonic() < deadline:
        # Check for newly arrived results
        for agent_id in list(remaining):
            result = shared_memory_io.read_agent_result(agent_id, run_id)
            if result is not None:
                collected[agent_id] = result
                remaining.discard(agent_id)
                shared_memory_io.update_manifest_status(run_id, agent_id, "complete")
                logger.info(
                    "Result received: %s (%d/%d)",
                    agent_id,
                    len(collected),
                    len(SUB_AGENTS),
                )

        if not remaining:
            break

        # Sleep until next poll (but don't overshoot the deadline)
        sleep_time = min(interval_s, max(0, deadline - time.monotonic()))
        if sleep_time > 0:
            time.sleep(sleep_time)

    # Mark any agents that didn't finish as timed_out
    timed_out_agents: list[str] = []
    for agent_id in remaining:
        timed_out_agents.append(agent_id)
        shared_memory_io.update_manifest_status(run_id, agent_id, "timed_out")
        logger.warning("Agent %s timed out for run %s", agent_id, run_id)

    all_complete = len(timed_out_agents) == 0
    if all_complete:
        logger.info("All %d agents completed for run %s", len(SUB_AGENTS), run_id)
    else:
        logger.warning(
            "Run %s finished with %d/%d agents (timed out: %s)",
            run_id,
            len(collected),
            len(SUB_AGENTS),
            ", ".join(timed_out_agents),
        )

    return {
        "results": collected,
        "timed_out": timed_out_agents,
        "all_complete": all_complete,
    }
