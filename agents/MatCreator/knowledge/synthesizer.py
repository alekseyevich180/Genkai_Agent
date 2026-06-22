"""Distill repeated MemGraph observations into durable Know-Do entries."""

from __future__ import annotations

import difflib
import logging
import re
from datetime import datetime, timezone

from know_do_graph import EdgeRelation

from .kdg_memory import connect_once, iter_memory, promote_memory
from .query import _get_kg

logger = logging.getLogger(__name__)


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9_.+-]+", text.casefold()))


def _clusters(memories, threshold: float = 0.72):
    clusters: list[list] = []
    for memory in memories:
        normalized = _normalized(memory.content)
        for cluster in clusters:
            representative = _normalized(cluster[0].content)
            if difflib.SequenceMatcher(None, normalized, representative).ratio() >= threshold:
                cluster.append(memory)
                break
        else:
            clusters.append([memory])
    return clusters


def run_knowledge_synthesizer(
    stale_days: int = 30,
    stale_min_refs: int = 0,
    min_insights_for_workflow: int = 3,
) -> dict:
    """Promote repeated successful memory and prune stale failed/unchecked notes.

    ``min_insights_for_workflow`` is retained for API compatibility and now
    controls the minimum evidence count required for promotion.
    """
    del stale_min_refs
    graph = _get_kg()
    unpromoted = list(iter_memory(graph, include_promoted=False))
    eligible = [entry for entry in unpromoted if entry.success is not False]

    promoted = 0
    linked = 0
    for cluster in _clusters(eligible):
        sessions = {entry.session_id for entry in cluster}
        successful = [entry for entry in cluster if entry.success is True]
        if len(cluster) < min_insights_for_workflow:
            continue
        if len(successful) < 2 and len(sessions) < 2:
            continue

        canonical = max(cluster, key=lambda entry: len(entry.content))
        title = canonical.content.split(":", 1)[0].strip()[:80].rstrip(".")
        durable, created = promote_memory(
            graph,
            canonical,
            title=title,
            content=canonical.content,
        )
        promoted += int(created)

        for memory in cluster:
            if memory.id != canonical.id:
                connect_once(
                    graph,
                    memory.id,
                    canonical.id,
                    relation=EdgeRelation.related_memory,
                    metadata={"source": "matcreator-distillation-cluster"},
                )
                graph.memory(memory.session_id).mark_promoted(memory.id, durable.id)

        source_ids = {
            source_id
            for memory in cluster
            for source_id in memory.source_entry_ids
            if graph.get(source_id) is not None
        }
        for source_id in source_ids:
            linked += int(
                connect_once(
                    graph,
                    durable.id,
                    source_id,
                    relation=EdgeRelation.heuristic_for,
                )
            )

    cutoff = datetime.now(timezone.utc)
    pruned = 0
    for memory in unpromoted:
        created_at = memory.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (cutoff - created_at).days
        if age_days >= stale_days and memory.success is not True:
            if graph.memory(memory.session_id).delete(memory.id):
                pruned += 1

    graph.refresh()
    logger.info(
        "Know-Do distillation: promoted=%d linked=%d pruned=%d",
        promoted,
        linked,
        pruned,
    )
    return {
        "pruned": pruned,
        "merged": 0,
        "abstracted": promoted,
        "promoted": promoted,
        "linked": linked,
        "message": (
            f"Know-Do distillation complete: promoted {promoted}, "
            f"linked {linked}, pruned {pruned}."
        ),
    }
