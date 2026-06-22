"""Memory utilities for the thinking agent.

Exposes knowledge-graph-based tools (preferred) and legacy MEMORY.md helpers
(kept for backward compatibility and manual use).
"""

from __future__ import annotations

import os
from google.adk.tools import ToolContext
from ...workspace import WORKSPACE_ROOT

_MEMORY_PATH = WORKSPACE_ROOT / "MEMORY.md"


# ---------------------------------------------------------------------------
# Knowledge graph tools (preferred)
# ---------------------------------------------------------------------------

from ...knowledge.query import (
    query_knowledge_graph as _query_knowledge_graph,
    save_to_knowledge_graph as _save_to_knowledge_graph,
    search_skills,
    get_related_skills,
)
from ...knowledge.synthesizer import run_knowledge_synthesizer as _run_synthesizer


def query_knowledge_graph(
    query: str,
    depth: int = 2,
    top_k: int = 15,
) -> str:
    """Query the memory knowledge graph for lessons and past findings relevant to *query*.

    Returns user-generated memory nodes from past sessions. Memory nodes may
    reference skill names in their content to express skill associations.
    To discover available skills, use `search_skills` instead.

    Args:
        query: Free-text search string.
        depth: BFS expansion depth (default 2).
        top_k: Maximum nodes to return (default 15).
    """
    return _query_knowledge_graph(query, depth=depth, top_k=top_k)


def save_to_knowledge_graph(
    content: str,
    tool_context: ToolContext,
    context: str = "",
) -> str:
    """Save a finding to the current session's writable MemGraph.

    Args:
        content: The observation, lesson, warning, or result to remember.
        context: Short task or skill context for later retrieval.
    """
    session_id = tool_context.state.get("session_id", "default")
    return _save_to_knowledge_graph(
        content,
        context=context,
        session_id=session_id,
    )


def run_synthesizer(
    stale_days: int = 30,
    stale_min_refs: int = 0,
    min_insights_for_workflow: int = 3,
) -> dict:
    """Distill repeated successful memory into durable Know-Do knowledge.

    Similar observations from successful executions are promoted after enough
    evidence, linked to their source capabilities, and marked as promoted in
    MemGraph. Stale failed or unchecked observations are pruned.

    Args:
        stale_days: Delete nodes older than this many days with few references.
        stale_min_refs: Nodes with <= this many references are stale candidates.
        min_insights_for_workflow: Minimum Insight nodes sharing a skill/workflow
            before a Workflow abstraction node is synthesized above them.
    """
    return _run_synthesizer(
        stale_days=stale_days,
        stale_min_refs=stale_min_refs,
        min_insights_for_workflow=min_insights_for_workflow,
    )


# ---------------------------------------------------------------------------
# Legacy MEMORY.md helpers (backward-compatible)
# ---------------------------------------------------------------------------

def load_memory() -> str:
    """Return the full contents of MEMORY.md, or an empty string if missing."""
    try:
        with open(_MEMORY_PATH, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_memory(content: str) -> str:
    """Append *content* to MEMORY.md and return a confirmation message."""
    os.makedirs(os.path.dirname(_MEMORY_PATH), exist_ok=True)
    with open(_MEMORY_PATH, "a") as f:
        f.write(content)
    return f"Memory appended successfully at {_MEMORY_PATH}"


def update_memory(new_entries: str) -> str:
    """Append new_entries to MEMORY.md.

    Prefer save_to_knowledge_graph for new knowledge. This function is kept
    for manual/legacy use.
    """
    return write_memory("\n" + new_entries)


def read_memory() -> str:
    """Read the full contents of MEMORY.md.

    Prefer query_knowledge_graph for targeted retrieval. This function loads
    the entire file and should be used only when a broad context dump is needed.
    """
    content = load_memory()
    if not content.strip():
        return "Memory is empty. No past context available."
    return content
