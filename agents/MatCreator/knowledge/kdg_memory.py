"""Integration helpers for Know-Do Graph and its writable MemGraph."""

from __future__ import annotations

import difflib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from know_do_graph import (
    EdgeRelation,
    Entry,
    EntryMetadata,
    EntryType,
    KnowDoGraph,
    MemEntry,
    RefinementStatus,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

LEGACY_RELATIONS = {
    "depends_on": EdgeRelation.dependency,
    "belongs_to": EdgeRelation.refinement_of,
    "relates_to": EdgeRelation.related_workflow,
    "requires": EdgeRelation.prerequisite,
    "discovered_in": EdgeRelation.derived_from,
    "similar_to": EdgeRelation.related_workflow,
    "supersedes": EdgeRelation.replacement,
}


def iter_entries(graph: KnowDoGraph, *, page_size: int = 200) -> Iterable[Entry]:
    offset = 0
    while True:
        page = graph.list(limit=page_size, offset=offset)
        yield from page
        if len(page) < page_size:
            return
        offset += page_size


def find_entry(
    graph: KnowDoGraph,
    title: str,
    *,
    entry_types: Iterable[EntryType] | None = None,
    similarity_threshold: float = 0.9,
) -> Entry | None:
    allowed = set(entry_types or EntryType)
    folded = title.strip().casefold()
    best: tuple[float, Entry] | None = None
    for candidate in iter_entries(graph):
        if candidate.entry_type not in allowed:
            continue
        ratio = difflib.SequenceMatcher(None, folded, candidate.title.casefold()).ratio()
        if ratio >= similarity_threshold and (best is None or ratio > best[0]):
            best = (ratio, candidate)
    return best[1] if best else None


def upsert_entry(
    graph: KnowDoGraph,
    *,
    title: str,
    content: str,
    entry_type: EntryType,
    tags: Iterable[str] = (),
    aliases: Iterable[str] = (),
    metadata: EntryMetadata | None = None,
    similarity_threshold: float = 0.9,
) -> tuple[Entry, bool]:
    title = title.strip()
    if not title:
        raise ValueError("entry title must not be empty")
    match = find_entry(
        graph,
        title,
        entry_types=[entry_type],
        similarity_threshold=similarity_threshold,
    )
    if match is None:
        return (
            graph.add(
                title,
                content=content,
                entry_type=entry_type,
                tags=list(dict.fromkeys(tags)),
                aliases=list(dict.fromkeys(aliases)),
                metadata=metadata,
            ),
            True,
        )

    changes: dict[str, Any] = {}
    merged_tags = list(dict.fromkeys([*match.tags, *tags]))
    merged_aliases = list(dict.fromkeys([*match.aliases, *aliases]))
    if merged_tags != match.tags:
        changes["tags"] = merged_tags
    if merged_aliases != match.aliases:
        changes["aliases"] = merged_aliases
    if content and content != match.content:
        changes["content"] = content
    if metadata is not None:
        current = match.metadata.model_copy(deep=True)
        changes["metadata"] = current.model_copy(
            update={
                "source_provenance": metadata.source_provenance or current.source_provenance,
                "extraction_method": metadata.extraction_method or current.extraction_method,
                "refinement_status": metadata.refinement_status,
                "trust_score": (
                    metadata.trust_score
                    if metadata.trust_score is not None
                    else current.trust_score
                ),
                "verification_status": metadata.verification_status,
                "custom": {**current.custom, **metadata.custom},
            }
        )
    return (graph.update(match.id, **changes) if changes else match), False


def connect_once(
    graph: KnowDoGraph,
    source_id: str,
    target_id: str,
    *,
    relation: EdgeRelation,
    weight: float = 1.0,
    metadata: dict[str, Any] | None = None,
) -> bool:
    related = graph.related(source_id, depth=1, relation=relation)
    if any(entry.id == target_id for entry in related):
        return False
    graph.connect(source_id, target_id, relation=relation, weight=weight, metadata=metadata)
    return True


def increment_usage(graph: KnowDoGraph, entry: Entry) -> Entry:
    metadata = entry.metadata.model_copy(deep=True)
    metadata.usage_count += 1
    return graph.update(entry.id, metadata=metadata)


def add_memory(
    graph: KnowDoGraph,
    session_id: str,
    content: str,
    *,
    tags: Iterable[str] = (),
    source_entry_ids: Iterable[str] = (),
    success: bool | None = None,
) -> MemEntry:
    return graph.memory(session_id).add(
        content,
        tags=list(dict.fromkeys(tags)),
        source_entry_ids=list(dict.fromkeys(source_entry_ids)),
        success=success,
    )


def iter_memory(graph: KnowDoGraph, *, include_promoted: bool = True) -> Iterable[MemEntry]:
    sessions = {
        entry.metadata.custom.get("memory", {}).get("session_id")
        for entry in graph.search(
            entry_type=EntryType.memory,
            limit=100_000,
            mode="keyword",
        )
    }
    for session_id in sorted(session for session in sessions if session):
        for memory in graph.memory(session_id).list():
            if include_promoted or not memory.promoted:
                yield memory


def _legacy_rows(path: Path, category: str) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if not path.exists():
        return [], []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "kg_nodes" not in tables:
            return [], []
        columns = {row[1] for row in conn.execute("PRAGMA table_info(kg_nodes)")}
        category_expr = (
            "COALESCE(category, type, 'memory')"
            if "category" in columns
            else "COALESCE(type, 'memory')"
        )
        nodes = conn.execute(
            "SELECT * FROM kg_nodes WHERE " + category_expr + " = ?",
            (category,),
        ).fetchall()
        edges = conn.execute("SELECT * FROM kg_edges").fetchall() if "kg_edges" in tables else []
    return nodes, edges


def migrate_legacy_graphs(
    graph: KnowDoGraph,
    *,
    skill_db: Path,
    memory_db: Path,
) -> dict[str, int]:
    """Copy legacy skill nodes to KDG and legacy memories to MemGraph."""
    stats = {"know_do_nodes": 0, "memory_entries": 0, "edges": 0}
    id_map: dict[str, str] = {}

    skill_nodes, skill_edges = _legacy_rows(skill_db, "skill")
    for row in skill_nodes:
        custom = {"legacy_node_id": row["id"], "managed_by": "matcreator"}
        metadata = EntryMetadata(
            source_provenance="legacy-skill-graph",
            refinement_status=RefinementStatus.validated,
            verification_status=VerificationStatus.peer_reviewed,
            usage_count=row["reference_count"] or 0,
            trust_score=row["confidence"],
            custom=custom,
        )
        entry, created = upsert_entry(
            graph,
            title=row["name"],
            content=row["description"] or "",
            entry_type=EntryType.capability,
            tags=["matcreator-skill", "managed", "legacy"],
            metadata=metadata,
        )
        id_map[row["id"]] = entry.id
        stats["know_do_nodes"] += int(created)

    for row in skill_edges:
        source_id = id_map.get(row["source_id"])
        target_id = id_map.get(row["target_id"])
        relation = LEGACY_RELATIONS.get(row["edge_type"])
        if source_id and target_id and relation and connect_once(
            graph,
            source_id,
            target_id,
            relation=relation,
            weight=row["weight"] or 1.0,
            metadata={"legacy_edge_type": row["edge_type"]},
        ):
            stats["edges"] += 1

    memory_nodes, _ = _legacy_rows(memory_db, "memory")
    migration_memory = graph.memory("legacy-memory-graph")
    existing_tags = {tag for entry in migration_memory.list() for tag in entry.tags}
    for row in memory_nodes:
        legacy_tag = f"legacy-id:{row['id']}"
        if legacy_tag in existing_tags:
            continue
        content = row["description"] or row["name"]
        migration_memory.add(
            content,
            tags=["legacy", "migrated", legacy_tag],
            success=None,
        )
        existing_tags.add(legacy_tag)
        stats["memory_entries"] += 1

    # Migrate KDG entries created by the previous partial integration.
    has_kdg_entries = False
    if memory_db.exists():
        with sqlite3.connect(memory_db) as conn:
            has_kdg_entries = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entries'"
            ).fetchone() is not None
    if has_kdg_entries:
        try:
            old_graph = KnowDoGraph(memory_db, initialize=False)
            for entry in old_graph.list(limit=10_000):
                legacy_tag = f"legacy-kdg-id:{entry.id}"
                if legacy_tag in existing_tags:
                    continue
                migration_memory.add(
                    entry.content or entry.title,
                    tags=["legacy", "migrated", "previous-kdg", legacy_tag],
                    success=None,
                )
                existing_tags.add(legacy_tag)
                stats["memory_entries"] += 1
            old_graph.close()
        except Exception:
            logger.exception("Failed to migrate previous KDG memory entries")

    return stats


def migrate_kdg_database(graph: KnowDoGraph, source_path: Path) -> dict[str, int]:
    """Idempotently copy a previous KnowDoGraph database into ``graph``."""
    if not source_path.exists() or source_path.resolve() == graph.path.resolve():
        return {"nodes": 0, "edges": 0}
    with sqlite3.connect(source_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "entries" not in tables:
            return {"nodes": 0, "edges": 0}
        conn.row_factory = sqlite3.Row
        edge_rows = conn.execute(
            "SELECT source_id, target_id, relation, weight, metadata_json FROM edges"
        ).fetchall() if "edges" in tables else []

    source = KnowDoGraph(source_path, initialize=False)
    created_nodes = 0
    for entry in source.list(limit=100_000):
        if graph.get(entry.id) is not None:
            continue
        graph.add(
            entry.title,
            id=entry.id,
            content=entry.content,
            entry_type=entry.entry_type,
            tags=entry.tags,
            aliases=entry.aliases,
            metadata=entry.metadata,
            internal_refs=entry.internal_refs,
            scripts=entry.scripts,
            assets=entry.assets,
        )
        created_nodes += 1
    source.close()

    created_edges = 0
    for row in edge_rows:
        if graph.get(row["source_id"]) is None or graph.get(row["target_id"]) is None:
            continue
        metadata = {}
        if row["metadata_json"]:
            try:
                metadata = json.loads(row["metadata_json"])
            except json.JSONDecodeError:
                pass
        if connect_once(
            graph,
            row["source_id"],
            row["target_id"],
            relation=EdgeRelation(row["relation"]),
            weight=row["weight"] or 1.0,
            metadata=metadata,
        ):
            created_edges += 1
    graph.refresh()
    return {"nodes": created_nodes, "edges": created_edges}


def migrate_legacy_memory_json(graph: KnowDoGraph, source_dir: Path) -> int:
    """Import JSON traces created by pre-unification MemGraph releases."""
    if not source_dir.exists():
        return 0
    created = 0
    for path in sorted(source_dir.glob("*.json")):
        session_id = path.stem
        target = graph.memory(session_id)
        existing_tags = {tag for entry in target.list() for tag in entry.tags}
        try:
            raw_entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read legacy memory file %s", path)
            continue
        for raw in raw_entries.values():
            memory = MemEntry(**raw)
            migration_tag = f"migrated-memory-id:{memory.id}"
            if migration_tag in existing_tags:
                continue
            copied = target.add(
                memory.content,
                tags=[*memory.tags, migration_tag],
                source_entry_ids=memory.source_entry_ids,
                success=memory.success,
            )
            if memory.promoted and memory.promotion_target_id:
                target.mark_promoted(copied.id, memory.promotion_target_id)
            existing_tags.add(migration_tag)
            created += 1
    return created


def promote_memory(
    graph: KnowDoGraph,
    memory: MemEntry,
    *,
    title: str,
    content: str,
    entry_type: EntryType = EntryType.heuristic,
) -> tuple[Entry, bool]:
    """Refine one native memory node into durable Know-Do knowledge."""
    metadata = EntryMetadata(
        source_provenance="matcreator-memory-distillation",
        extraction_method="mem_promotion",
        refinement_status=RefinementStatus.refined,
        verification_status=VerificationStatus.self_tested,
        trust_score=0.8,
        custom={
            "distilled_from_memory_id": memory.id,
            "distilled_from_session": memory.session_id,
        },
    )
    entry, created = upsert_entry(
        graph,
        title=title,
        content=content,
        entry_type=entry_type,
        tags=["matcreator-distilled"],
        metadata=metadata,
        similarity_threshold=0.85,
    )
    connect_once(
        graph,
        memory.id,
        entry.id,
        relation=EdgeRelation.refinement_of,
        metadata={"source": "memory_promotion"},
    )
    graph.memory(memory.session_id).mark_promoted(memory.id, entry.id)
    return entry, created
