"""Knowledge extractor: processes a session trajectory JSONL and populates the graph."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from know_do_graph import EdgeRelation

from ..workspace import WORKSPACE_ROOT
from .kdg_memory import add_memory, connect_once
from .kg_state import (
    get_extraction_cursor,
    has_extraction_record,
    record_extraction,
)
from .query import _get_kg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM-based extraction
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """You are a knowledge extraction assistant.

Given a session trajectory (per-step results) and an optional session-level summary
(global narrative, decisions, failures, lessons), extract knowledge graph entries.

Return a JSON array of objects. Each object must have:
  "name":        short canonical name (≤80 chars)
  "description": one sentence describing it
  "relations":   list of {{source_name, edge_type, target_name}} objects
                 edge_type must be one of: depends_on | belongs_to | relates_to

All extracted nodes are memory nodes (lessons, findings, heuristics).
Relations may reference skill node names (existing tool/guide names) as targets.

Rules:
- Extract 5-20 entries total — quality over quantity.
- Focus on lessons learned, heuristics, warnings, quantitative results.
- Prefer extracting from the session summary (lessons_learned, failed_attempts)
  and per-step results from the trajectory.
- Only emit relations where source appears in the entry list or is a known skill name.
- Output ONLY the JSON array, no prose.

Session summary (global narrative):
{session_summary}

Trajectory (per-step results):
{trajectory}
"""


def _call_llm(prompt: str) -> str:
    """Call the configured LLM. Falls back gracefully if unavailable."""
    try:
        from litellm import completion
        from ..constants import GRAPH_AGENT_MODEL, LLM_API_KEY, LLM_BASE_URL

        model = os.environ.get("GRAPH_AGENT_MODEL", GRAPH_AGENT_MODEL)
        api_key = os.environ.get("LLM_API_KEY", LLM_API_KEY)
        base_url = os.environ.get("LLM_BASE_URL", LLM_BASE_URL)

        response = completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            base_url=base_url,
            temperature=0.0,
            max_tokens=2048,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.warning("LLM call failed in extractor: %s", exc)
        return ""


def _parse_extraction(raw: str) -> list[dict[str, Any]]:
    """Parse JSON array from LLM output, tolerating markdown fences."""
    import re
    raw = raw.strip()
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return []


def _read_trajectory_delta(session_id: str, start_line: int = 0) -> tuple[str, int]:
    """Return summaries appended after ``start_line`` and the current line count."""
    traj_path = WORKSPACE_ROOT / "trajectories" / f"{session_id}.jsonl"
    if not traj_path.exists():
        return "", 0
    raw_lines = traj_path.read_text(encoding="utf-8").splitlines()
    if start_line > len(raw_lines):
        start_line = 0
    lines = []
    for line in raw_lines[start_line:]:
        try:
            entry = json.loads(line)
            skill = entry.get("active_skill") or "unknown"
            summary = entry.get("concise_summary") or entry.get("key_results") or ""
            if summary:
                lines.append(f"[Step {entry.get('step_index', '?')} | {skill}] {summary}")
        except json.JSONDecodeError:
            continue
    return "\n".join(lines), len(raw_lines)


def _read_trajectory(session_id: str) -> str:
    """Return all concatenated summaries from a session trajectory."""
    return _read_trajectory_delta(session_id)[0]


def _read_session_summary(session_id: str) -> str:
    """Return a formatted session-level summary if one was written by the thinking agent."""
    summary_path = WORKSPACE_ROOT / "trajectories" / f"{session_id}_summary.json"
    if not summary_path.exists():
        return "(No session summary available)"
    try:
        data = json.loads(summary_path.read_text())
        parts = [f"Goal: {data.get('goal', '')}"]
        if data.get("approach"):
            parts.append(f"Approach: {data['approach']}")
        if data.get("outcome"):
            parts.append(f"Outcome: {data['outcome']}")
        if data.get("key_decisions"):
            parts.append("Key decisions:\n" + "\n".join(f"  - {d}" for d in data["key_decisions"]))
        if data.get("lessons_learned"):
            parts.append("Lessons learned:\n" + "\n".join(f"  - {l}" for l in data["lessons_learned"]))
        if data.get("failed_attempts"):
            parts.append("Failed attempts:\n" + "\n".join(f"  - {f}" for f in data["failed_attempts"]))
        return "\n".join(parts)
    except Exception as exc:
        logger.warning("Failed to read session summary for %s: %s", session_id, exc)
        return "(Session summary unreadable)"


def _has_legacy_extraction(graph, session_id: str) -> bool:
    """Detect sessions extracted before per-session cursors were introduced."""
    return any(
        "extracted" in memory.tags
        for memory in graph.memory(session_id).list()
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_knowledge_extractor(session_id: str) -> dict:
    """Extract knowledge from a completed session and upsert into the graph.

    Reads both the per-step trajectory JSONL and the session-level summary JSON
    (written by the thinking agent via write_session_summary). The session summary
    provides global narrative, key decisions, and failures that step-level entries miss.

    Args:
        session_id: The ADK session ID whose trajectory JSONL should be processed.

    Returns:
        Dict with keys: status, nodes_created, edges_created, message.
    """
    extraction_cursor = get_extraction_cursor(session_id)
    extraction_recorded = has_extraction_record(session_id)
    trajectory, trajectory_lines = _read_trajectory_delta(
        session_id,
        start_line=extraction_cursor,
    )
    kg = None
    if not extraction_recorded and trajectory_lines:
        kg = _get_kg()
        if _has_legacy_extraction(kg, session_id):
            record_extraction(session_id, trajectory_lines)
            return {
                "status": "skipped",
                "message": (
                    f"Session {session_id} was extracted before cursor tracking; "
                    "initialized its extraction cursor."
                ),
                "nodes_created": 0,
                "edges_created": 0,
            }
    if trajectory_lines == extraction_cursor:
        return {
            "status": "skipped",
            "message": f"Session {session_id} trajectory was already extracted.",
            "nodes_created": 0,
            "edges_created": 0,
        }
    if not trajectory.strip():
        if trajectory_lines > extraction_cursor:
            record_extraction(session_id, trajectory_lines)
        return {
            "status": "skipped",
            "message": f"No new trajectory content found for session {session_id}",
            "nodes_created": 0,
            "edges_created": 0,
        }

    session_summary = (
        _read_session_summary(session_id)
        if extraction_cursor == 0
        else "(Omitted for incremental extraction; use only the new trajectory records.)"
    )
    prompt = _EXTRACTION_PROMPT.format(
        session_summary=session_summary,
        trajectory=trajectory,
    )
    raw = _call_llm(prompt)
    entries = _parse_extraction(raw)

    if not entries:
        logger.info("Extractor: no entries parsed for session %s", session_id)
        if raw.strip():
            record_extraction(session_id, trajectory_lines)
        return {
            "status": "ok",
            "message": "LLM returned no extractable entries.",
            "nodes_created": 0,
            "edges_created": 0,
        }

    kg = kg or _get_kg()
    nodes_created = 0
    edges_created = 0
    memory_ids: dict[str, str] = {}
    skill_ids: dict[str, str] = {}
    existing_content = {
        memory.content.strip().casefold()
        for memory in kg.memory(session_id).list()
    }

    # Session findings stay in writable MemGraph until repeated evidence is
    # distilled by the synthesizer into durable Know-Do entries.
    for entry in entries:
        nname = entry.get("name", "").strip()
        ndesc = entry.get("description", "")
        if not nname:
            continue
        related_ids: list[str] = []
        for rel in entry.get("relations", []):
            for name in (rel.get("source_name", ""), rel.get("target_name", "")):
                matches = kg.search(
                    name,
                    tags=["matcreator-skill"],
                    limit=1,
                    mode="keyword",
                )
                durable = matches[0] if matches else None
                if durable and "matcreator-skill" in durable.tags:
                    related_ids.append(durable.id)
                    skill_ids[name] = durable.id
        memory_content = f"{nname}: {ndesc}" if ndesc else nname
        if memory_content.strip().casefold() in existing_content:
            continue
        memory = add_memory(
            kg,
            session_id,
            memory_content,
            tags=["extracted", "successful-execution"],
            source_entry_ids=related_ids,
            success=True,
        )
        existing_content.add(memory_content.strip().casefold())
        memory_ids[nname] = memory.id
        nodes_created += 1

    for entry in entries:
        for relation in entry.get("relations", []):
            source_name = relation.get("source_name", "")
            target_name = relation.get("target_name", "")
            source_memory = memory_ids.get(source_name)
            target_memory = memory_ids.get(target_name)
            if source_memory and target_memory and connect_once(
                kg,
                source_memory,
                target_memory,
                relation=EdgeRelation.related_memory,
                metadata={"extracted_relation": relation.get("edge_type")},
            ):
                edges_created += 1
                continue

            memory_id = source_memory or target_memory
            skill_id = skill_ids.get(target_name) or skill_ids.get(source_name)
            if memory_id and skill_id and connect_once(
                kg,
                memory_id,
                skill_id,
                relation=EdgeRelation.memory_of,
                metadata={"extracted_relation": relation.get("edge_type")},
            ):
                edges_created += 1

    logger.info(
        "Extractor session=%s: %d memory entries, %d edges",
        session_id,
        nodes_created,
        edges_created,
    )
    record_extraction(session_id, trajectory_lines)
    return {
        "status": "ok",
        "nodes_created": nodes_created,
        "edges_created": edges_created,
        "message": (
            f"Extracted {nodes_created} working-memory nodes and "
            f"{edges_created} edges from session {session_id}."
        ),
    }
