"""Session-level summary tool for the thinking agent.

Called after execution results return to the planner. Captures the global
narrative (why, key decisions, failures) that per-step trajectory entries miss.
Saved to {workspace}/trajectories/{session_id}_summary.json for the extractor.

File writes are dispatched to a background thread so the agent is not blocked
on disk I/O during response generation.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field, ValidationError

from ...workspace import get_workspace_root

logger = logging.getLogger(__name__)

_io_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="summary-io")


class SessionSummary(BaseModel):
    goal: str = Field(..., description="Original user goal in their own words")
    approach: str = Field(..., description="Overall approach taken and why it was chosen")
    key_decisions: List[str] = Field(
        default_factory=list,
        description="Important choices made during the session (e.g. code choice, parameter values)",
    )
    lessons_learned: List[str] = Field(
        default_factory=list,
        description="Heuristics or warnings useful for future similar tasks",
    )
    failed_attempts: List[str] = Field(
        default_factory=list,
        description="Things that were tried and did not work, with brief reason",
    )
    outcome: str = Field(..., description="One-sentence statement of what was accomplished")


def write_session_summary(summary: dict, tool_context: ToolContext) -> dict:
    """Write a session-level summary capturing the global narrative of this session.

    Call this once per session, after execution has completed and results are
    available. Unlike per-step summaries, this captures WHY decisions were made,
    what failed, and high-level lessons that apply to future similar tasks.

    The summary is saved alongside the trajectory JSONL and is read by the
    knowledge extractor to build richer graph entries.

    File I/O is dispatched to a background thread — the function returns
    immediately after validation without blocking on disk writes.

    Args:
        summary: Dict with keys:
            - goal (str): Original user goal in their own words.
            - approach (str): Overall approach and reasoning.
            - key_decisions (list[str]): Important choices made.
            - lessons_learned (list[str]): Heuristics for future tasks.
            - failed_attempts (list[str]): What was tried and failed.
            - outcome (str): One-sentence statement of what was accomplished.
    """
    try:
        validated = SessionSummary(**summary)
        data = validated.model_dump()

        session_id = tool_context._invocation_context.session.id
        traj_dir = get_workspace_root() / "trajectories"
        traj_dir.mkdir(parents=True, exist_ok=True)
        summary_path = traj_dir / f"{session_id}_summary.json"

        data["session_id"] = session_id
        data["timestamp"] = datetime.now(timezone.utc).isoformat()

        _io_executor.submit(_write_summary_file, summary_path, data)

        return {
            "status": "ok",
            "path": str(summary_path),
            "message": "Session summary queued. The knowledge extractor will use it to build the knowledge graph.",
        }
    except ValidationError as exc:
        return {
            "status": "error",
            "errors": exc.errors(),
            "message": "Session summary validation failed. Fix the errors and retry.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Unexpected error: {exc}",
        }


def _write_summary_file(path: Path, data: dict) -> None:
    """Background worker: write the summary JSON to disk."""
    try:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Session summary written to %s", path)
    except Exception as exc:
        logger.warning("Failed to write session summary to %s: %s", path, exc)
