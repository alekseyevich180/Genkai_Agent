"""MatCreator orchestration for KDG's built-in review agents."""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from know_do_graph import (
    EntryType,
    KnowDoGraph,
    ReviewPolicy,
    VerificationStatus,
)

ReviewStatusCallback = Callable[[str, dict[str, Any]], None]
_pipeline_lock = threading.Lock()


def review_policy() -> ReviewPolicy:
    return ReviewPolicy(
        exclude_types=frozenset({EntryType.memory}),
        protected_statuses=frozenset(
            {
                VerificationStatus.peer_reviewed,
                VerificationStatus.community_tested,
            }
        ),
        assignable_statuses=frozenset(
            {
                VerificationStatus.unverified,
                VerificationStatus.self_tested,
                VerificationStatus.bugged,
                VerificationStatus.deprecated,
            }
        ),
        allowed_actions=frozenset(
            {"modify", "delete", "distill", "merge_similar", "link"}
        ),
    )


def review_threshold() -> int:
    return int(os.environ.get("MATCREATOR_REVIEW_TRIGGER_THRESHOLD", "20"))


def normalize_review_model(model: str) -> str:
    return model.split("/", 1)[1] if "/" in model else model


def count_unreviewed_durable_nodes(
    graph: KnowDoGraph,
    *,
    policy: ReviewPolicy | None = None,
) -> int:
    active_policy = policy or review_policy()
    count = 0
    offset = 0
    while True:
        entries = graph.list(limit=200, offset=offset)
        count += sum(
            entry.entry_type not in active_policy.exclude_types
            and entry.metadata.verification_status not in active_policy.protected_statuses
            and entry.metadata.review_count == 0
            for entry in entries
        )
        if len(entries) < 200:
            return count
        offset += 200


def has_reviewable_memory(graph: KnowDoGraph) -> bool:
    memories = graph.search(
        entry_type=EntryType.memory,
        limit=100_000,
        mode="keyword",
    )
    for entry in memories:
        memory = entry.metadata.custom.get("memory", {})
        if not memory.get("promoted", False) and memory.get("distillation_status") != "skipped":
            return True
    return False


def _tag_results(phase: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    tagged = []
    for item in result.get("results", []):
        if isinstance(item, dict):
            tagged.append({"phase": phase, **item})
        else:
            tagged.append({"phase": phase, "result": item})
    return tagged


def run_review_pipeline(
    graph: KnowDoGraph,
    *,
    model: str,
    api_key: str,
    base_url: str | None = None,
    batch_size: int = 20,
    threshold: int | None = None,
    strategy: str = "auto",
    on_status: ReviewStatusCallback | None = None,
) -> dict[str, Any]:
    """Review memory first, then review durable nodes when backlog is large enough."""
    with _pipeline_lock:
        return _run_review_pipeline(
            graph,
            model=model,
            api_key=api_key,
            base_url=base_url,
            batch_size=batch_size,
            threshold=threshold,
            strategy=strategy,
            on_status=on_status,
        )


def _run_review_pipeline(
    graph: KnowDoGraph,
    *,
    model: str,
    api_key: str,
    base_url: str | None,
    batch_size: int,
    threshold: int | None,
    strategy: str,
    on_status: ReviewStatusCallback | None,
) -> dict[str, Any]:
    phase_results: dict[str, dict[str, Any]] = {}
    common = {
        "agent": "reviewer",
        "model": normalize_review_model(model),
        "api_key": api_key,
        "base_url": base_url,
        "batch_size": batch_size,
    }

    if has_reviewable_memory(graph):
        memory_review = graph.chat(
            **common,
            on_status=(
                (lambda status: on_status("memory", status))
                if on_status is not None
                else None
            ),
        ).review_memory()
        phase_results["memory"] = memory_review
        graph.refresh()

    target = threshold if threshold is not None else review_threshold()
    unreviewed = count_unreviewed_durable_nodes(graph)
    if unreviewed >= target:
        graph_review = graph.chat(
            **common,
            policy=review_policy(),
            strategy=strategy,
            on_status=(
                (lambda status: on_status("graph", status))
                if on_status is not None
                else None
            ),
        ).review_nodes()
        phase_results["graph"] = graph_review
        graph.refresh()

    results = [
        item
        for phase, result in phase_results.items()
        for item in _tag_results(phase, result)
    ]
    errors = [
        f"{phase}: {error}"
        for phase, result in phase_results.items()
        for error in result.get("errors", [])
    ]
    completed = sum(
        result.get("progress", {}).get("completed", 0)
        for result in phase_results.values()
    )
    total = sum(
        result.get("progress", {}).get("total", 0)
        for result in phase_results.values()
    )
    summaries = [
        f"{phase}: {result['summary']}"
        for phase, result in phase_results.items()
        if result.get("summary")
    ]
    if not phase_results:
        summaries.append(
            f"No review needed: no pending memory and {unreviewed} unreviewed "
            f"durable nodes (threshold {target})."
        )
    elif "graph" not in phase_results:
        summaries.append(
            f"Graph review skipped: {unreviewed} unreviewed durable nodes "
            f"(threshold {target})."
        )

    return {
        "status": "completed" if not errors else "completed_with_errors",
        "phase": "complete",
        "progress": {
            "completed": completed,
            "total": total,
            "percent": round(100 * completed / total) if total else 100,
        },
        "results": results,
        "errors": errors,
        "summary": " ".join(summaries),
        "memory_review": phase_results.get("memory"),
        "graph_review": phase_results.get("graph"),
        "unreviewed_durable_nodes": unreviewed,
        "review_threshold": target,
    }
