"""Retrieval and write tools for unified Know-Do Graph storage."""

from __future__ import annotations

import logging
import os
from typing import Optional

from know_do_graph import (
    Entry,
    EntryType,
    KnowDoGraph,
)

from .kdg_memory import (
    add_memory,
    increment_usage,
    migrate_kdg_database,
    migrate_legacy_memory_json,
    migrate_legacy_graphs,
)
from .review import (
    normalize_review_model,
    review_policy,
    review_threshold,
)

logger = logging.getLogger(__name__)
_graph: Optional[KnowDoGraph] = None
_migration_result: dict[str, int] | None = None


def _configure_auto_review(graph: KnowDoGraph) -> None:
    """Attach KDG's policy-controlled durable-node review scheduler."""
    enabled = os.environ.get("MATCREATOR_AUTO_REVIEW", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return

    from ..constants import GRAPH_AGENT_MODEL, LLM_API_KEY, LLM_BASE_URL

    threshold = review_threshold()
    model = normalize_review_model(
        os.environ.get("REVIEW_AGENT_MODEL")
        or os.environ.get("GRAPH_AGENT_MODEL", GRAPH_AGENT_MODEL)
    )
    api_key = (
        os.environ.get("LLM_API_KEY")
        or LLM_API_KEY
        or os.environ.get("MINIMAX_API_KEY", "")
    )
    base_url = (
        os.environ.get("LLM_BASE_URL")
        or LLM_BASE_URL
        or os.environ.get("MINIMAX_API_BASE")
        or None
    )
    batch_size = int(os.environ.get("MATCREATOR_REVIEW_BATCH_SIZE", "5"))
    graph.auto_review(
        threshold=threshold,
        policy=review_policy(),
        strategy=os.environ.get("MATCREATOR_REVIEW_STRATEGY", "auto"),
        include_existing=True,
        model=model,
        api_key=api_key,
        base_url=base_url,
        batch_size=batch_size,
    )


def _get_kg() -> KnowDoGraph:
    global _graph, _migration_result
    if _graph is None:
        from ..constants import (
            KNOW_DO_GRAPH_DB,
            KNOW_DO_MEMORY_DIR,
            LEGACY_MEMORY_GRAPH_DB,
            LEGACY_SKILL_GRAPH_DB,
            LEGACY_UNIFIED_GRAPH_DB,
            LEGACY_UNIFIED_MEMORY_DIR,
        )

        _graph = KnowDoGraph(path=KNOW_DO_GRAPH_DB, memory_dir=KNOW_DO_MEMORY_DIR)
        unified = {"nodes": 0, "edges": 0}
        if LEGACY_UNIFIED_GRAPH_DB.resolve() != KNOW_DO_GRAPH_DB.resolve():
            unified = migrate_kdg_database(_graph, LEGACY_UNIFIED_GRAPH_DB)
        memories = migrate_legacy_memory_json(_graph, LEGACY_UNIFIED_MEMORY_DIR)
        legacy = migrate_legacy_graphs(
            _graph,
            skill_db=LEGACY_SKILL_GRAPH_DB,
            memory_db=LEGACY_MEMORY_GRAPH_DB,
        )
        _migration_result = {
            "know_do_nodes": unified["nodes"] + legacy["know_do_nodes"],
            "memory_entries": memories + legacy["memory_entries"],
            "edges": unified["edges"] + legacy["edges"],
        }
        _configure_auto_review(_graph)
    return _graph


def get_migration_result() -> dict[str, int]:
    _get_kg()
    return dict(_migration_result or {})


# Compatibility aliases for callers from the previous split implementation.
_get_skill_kg = _get_kg
_get_memory_kg = _get_kg


def _format_durable(entries: list[Entry]) -> str:
    lines = []
    for entry in entries:
        line = f"- **{entry.title}** [{entry.entry_type.value}]"
        if entry.content:
            line += f": {entry.content}"
        lines.append(line)
    return "\n".join(lines)


def _format_memory(entries: list[Entry]) -> str:
    lines = []
    for entry in entries:
        memory = entry.metadata.custom.get("memory", {})
        success = memory.get("success")
        status = "success" if success is True else "failed" if success is False else "unchecked"
        lines.append(f"- [{memory.get('session_id', 'default')}; {status}] {entry.content}")
    return "\n".join(lines)


def query_knowledge_graph(query: str, depth: int = 2, top_k: int = 15) -> str:
    """Search durable Know-Do knowledge and frequently updated MemGraph entries."""
    graph = _get_kg()
    try:
        durable = [
            entry
            for entry in graph.search(query, limit=top_k * 2, mode="hybrid")
            if entry.entry_type != EntryType.memory
        ][:top_k]
        candidates = {entry.id: entry for entry in durable}
        if depth > 0:
            for seed in durable:
                for related in graph.related(seed.id, depth=depth):
                    candidates.setdefault(related.id, related)
        durable = list(candidates.values())[:top_k]
        for entry in durable:
            increment_usage(graph, entry)

        memory_entries = [
            entry
            for entry in graph.search(
                query,
                entry_type=EntryType.memory,
                limit=top_k,
                mode="hybrid",
            )
            if not entry.metadata.custom.get("memory", {}).get("promoted", False)
        ]
        for entry in memory_entries:
            increment_usage(graph, entry)

        sections = []
        if durable:
            sections.append("### Know-Do Knowledge\n" + _format_durable(durable))
        if memory_entries:
            sections.append("### Working Memory\n" + _format_memory(memory_entries))
        return "\n\n".join(sections) or f"No knowledge graph entries found for '{query}'."
    except Exception as exc:
        logger.warning("query_knowledge_graph failed: %s", exc)
        return f"Knowledge graph query failed: {exc}"


def save_to_knowledge_graph(
    content: str,
    context: str = "",
    session_id: str = "default",
    success: bool | None = None,
) -> str:
    """Write an observation to MemGraph for later validation and distillation."""
    graph = _get_kg()
    tags = ["matcreator-memory"]
    if context:
        tags.append(f"context:{context[:80]}")
    try:
        memory = add_memory(
            graph,
            session_id,
            content,
            tags=tags,
            success=success,
        )
        return f"Saved working memory (id={memory.id}, session={session_id})."
    except Exception as exc:
        logger.warning("save_to_knowledge_graph failed: %s", exc)
        return f"Failed to save working memory: {exc}"


def search_skills(query: str, top_k: int = 5) -> str:
    """Search durable capabilities, procedures, workflows, and tools."""
    from ..config import get_disabled_skills

    graph = _get_kg()
    disabled = set(get_disabled_skills())
    allowed = {
        EntryType.capability,
        EntryType.procedure,
        EntryType.workflow,
        EntryType.tool,
    }
    try:
        results = [
            entry
            for entry in graph.search(query, limit=max(top_k * 3, 15), mode="hybrid")
            if entry.entry_type in allowed
            and "matcreator-skill" in entry.tags
            and entry.title not in disabled
        ][:top_k]
        for entry in results:
            increment_usage(graph, entry)
        return _format_durable(results) if results else f"No skills found for '{query}'."
    except Exception as exc:
        logger.warning("search_skills failed: %s", exc)
        return f"Skill search failed: {exc}"


def get_related_skills(start_node: str, top_k: int = 5, depth: int = 2) -> str:
    """Traverse durable Know-Do relationships from a known skill."""
    graph = _get_kg()
    try:
        start = graph.get(start_node)
        if start is None:
            matches = graph.search(start_node, tags=["matcreator-skill"], limit=1)
            start = matches[0] if matches else None
        if start is None:
            return f"No skill node found matching '{start_node}'."

        related = [
            entry
            for entry in graph.related(start.id, depth=depth)
            if "matcreator-skill" in entry.tags
        ][:top_k]
        for entry in related:
            increment_usage(graph, entry)
        return _format_durable(related) if related else f"No related skills found near '{start_node}'."
    except Exception as exc:
        logger.warning("get_related_skills failed: %s", exc)
        return f"Related skills lookup failed: {exc}"
