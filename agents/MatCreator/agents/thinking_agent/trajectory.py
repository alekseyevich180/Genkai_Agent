"""Execution trajectory logging for the thinking_agent.

Each call to summarize_agent appends one JSON line to
  {workspace_root}/trajectories/{session_id}.jsonl

Record schema
-------------
{
  "timestamp":       "<ISO-8601 UTC>",
  "session_id":      "<str>",
  "step_index":      <int>,
  "goal":            "<str | null>",
  "active_skill":    "<str | null>",
  "key_results":     "<str>",
  "artifacts":       ["<str>", ...],
  "concise_summary": "<str>"
}
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ...workspace import get_workspace_root


def append_trajectory_entry(
    session_id: str,
    step_index: int,
    goal: Optional[str],
    active_skill: Optional[str],
    summarize_response: Any,
) -> Path:
    """Parse *summarize_response* and append one JSONL entry for the session.

    Args:
        session_id:        ADK session ID (used as filename stem).
        step_index:        Monotonically increasing step counter for this session.
        goal:              Current goal from session state (may be None).
        active_skill:      Active skill name from session state (may be None).
        summarize_response: Raw response from summarize_agent (str or dict).

    Returns:
        The Path to the trajectory file that was written.
    """
    # Normalise the summarize_agent response to a dict
    parsed: Dict[str, Any] = {}
    if isinstance(summarize_response, dict):
        parsed = summarize_response
    elif isinstance(summarize_response, str):
        import re
        m = re.search(r"\{[\s\S]*\}", summarize_response)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = {"raw": summarize_response}
        else:
            parsed = {"raw": summarize_response}

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "step_index": step_index,
        "goal": goal,
        "active_skill": active_skill,
        "key_results": parsed.get("key_results", ""),
        "artifacts": parsed.get("artifacts", []),
        "concise_summary": parsed.get("concise_summary", ""),
    }

    traj_dir = get_workspace_root() / "trajectories"
    traj_dir.mkdir(parents=True, exist_ok=True)
    log_path = traj_dir / f"{session_id}.jsonl"

    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return log_path
