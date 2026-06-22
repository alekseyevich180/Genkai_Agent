"""History reading tools for the thinking_agent.

These tools let the planner inspect trajectory logs and the execution graph
after execution returns to planning (e.g. after cancellation, failure, or
partial completion).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


def _workspace_root():
    from ...workspace import get_workspace_root  # lazy import avoids circular deps

    return get_workspace_root()


def read_execution_trajectory(
    tool_context: ToolContext,
    last_n_steps: Optional[int] = None,
    session_id: Optional[str] = None,
) -> dict:
    """Read the execution trajectory log for this session.

    Returns completed step summaries: step_index, goal, key_results, artifacts,
    and concise_summary for each step. Use this after execution returns to
    planning to understand what work has been done before replanning.

    Args:
        last_n_steps: Return only the most recent N steps. Omit for all steps.
        session_id: Session to read. Defaults to the current session.
    """
    sid = session_id or tool_context._invocation_context.session.id
    traj_path = _workspace_root() / "trajectories" / f"{sid}.jsonl"

    if not traj_path.exists():
        return {
            "status": "not_found",
            "session_id": sid,
            "message": (
                f"No trajectory found for session {sid}. "
                "Execution may not have started or completed any steps yet."
            ),
            "steps": [],
            "total_steps": 0,
        }

    entries = []
    try:
        with traj_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError as exc:
        return {
            "status": "error",
            "session_id": sid,
            "message": f"Failed to read trajectory: {exc}",
            "steps": [],
        }

    total = len(entries)
    if last_n_steps is not None and last_n_steps > 0:
        entries = entries[-last_n_steps:]

    return {
        "status": "ok",
        "session_id": sid,
        "total_steps": total,
        "returned_steps": len(entries),
        "steps": entries,
    }


def read_agent_graph(
    tool_context: ToolContext,
    node_type_filter: Optional[str] = None,
    include_conversation: bool = False,
    session_id: Optional[str] = None,
) -> dict:
    """Read the agent execution graph for this session.

    Returns the hierarchical execution tree with node statuses, tool calls,
    and artifacts. Use this to diagnose which steps failed and what tools
    were called during execution.

    Args:
        node_type_filter: Restrict returned nodes to this type. Options:
            'step', 'execution', 'planning', 'orchestrator', 'tester'.
        include_conversation: If True, include the full conversation log per
            node. Defaults to False — conversation logs can be hundreds of KB.
        session_id: Session to read. Defaults to the current session.
    """
    sid = session_id or tool_context._invocation_context.session.id
    graph_path = _workspace_root() / "agent_graphs" / f"{sid}.json"

    if not graph_path.exists():
        return {
            "status": "not_found",
            "session_id": sid,
            "message": f"No agent graph found for session {sid}.",
        }

    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"status": "error", "session_id": sid, "message": f"Failed to read agent graph: {exc}"}

    nodes = data.get("nodes", {})

    if node_type_filter:
        nodes = {nid: n for nid, n in nodes.items() if n.get("type") == node_type_filter}

    if not include_conversation:
        nodes = {
            nid: {k: v for k, v in n.items() if k != "conversation"}
            for nid, n in nodes.items()
        }

    return {
        "status": "ok",
        "session_id": sid,
        "node_count": len(nodes),
        "nodes": nodes,
        "edges": data.get("edges", []),
        "updated_at": data.get("updated_at"),
    }
