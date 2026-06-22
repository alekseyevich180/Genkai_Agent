"""Persistent cross-session state for the knowledge pipeline."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from ..constants import _ADK_DIR

logger = logging.getLogger(__name__)

_STATE_PATH = _ADK_DIR / ".kg_state.json"
_STATE_LOCK = threading.Lock()


def _load() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except Exception:
            pass
    return {}


def _save(state: dict) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2))


def increment_exec_count() -> int:
    """Increment and persist the global execution-completion counter. Returns new value."""
    with _STATE_LOCK:
        state = _load()
        count = state.get("exec_completion_count", 0) + 1
        state["exec_completion_count"] = count
        _save(state)
        return count


def get_exec_count() -> int:
    return _load().get("exec_completion_count", 0)


def record_synthesizer_run() -> None:
    with _STATE_LOCK:
        state = _load()
        state["last_synthesizer_run"] = datetime.now(timezone.utc).isoformat()
        _save(state)


def get_extraction_cursor(session_id: str) -> int:
    """Return the number of trajectory lines already processed for a session."""
    sessions = _load().get("extracted_sessions", {})
    raw = sessions.get(session_id, {}).get("trajectory_lines", 0)
    return raw if isinstance(raw, int) and raw >= 0 else 0


def has_extraction_record(session_id: str) -> bool:
    """Return whether extraction progress has ever been recorded for a session."""
    sessions = _load().get("extracted_sessions", {})
    return session_id in sessions


def record_extraction(session_id: str, trajectory_lines: int) -> None:
    """Persist successful extraction progress for a session."""
    with _STATE_LOCK:
        state = _load()
        sessions = state.setdefault("extracted_sessions", {})
        sessions[session_id] = {
            "trajectory_lines": trajectory_lines,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
        _save(state)
