from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

from know_do_graph import EntryMetadata, EntryType, KnowDoGraph


def _load_helpers():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "agents"
        / "MatCreator"
        / "knowledge"
        / "kdg_memory.py"
    )
    spec = importlib.util.spec_from_file_location("matcreator_kdg_helpers_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_db(path: Path, category: str, node_id: str, name: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE kg_nodes (
              id TEXT PRIMARY KEY, category TEXT, type TEXT, name TEXT,
              description TEXT, content TEXT, source_session TEXT,
              created_at TEXT, updated_at TEXT, reference_count INTEGER,
              confidence REAL, immutable INTEGER, embedding TEXT
            );
            CREATE TABLE kg_edges (
              id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
              edge_type TEXT, weight REAL, properties TEXT, created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO kg_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                node_id,
                category,
                category,
                name,
                f"{name} description",
                None,
                "session-1",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                3,
                0.8,
                int(category == "skill"),
                None,
            ),
        )


def test_durable_upsert_preserves_usage(tmp_path: Path) -> None:
    helpers = _load_helpers()
    graph = KnowDoGraph(tmp_path / "know-do.db", memory_dir=tmp_path / "memory")
    first, created = helpers.upsert_entry(
        graph,
        title="VASP relaxation",
        content="Relax structures with VASP.",
        entry_type=EntryType.capability,
        tags=["matcreator-skill"],
        metadata=EntryMetadata(custom={"managed_by": "matcreator"}),
    )
    helpers.increment_usage(graph, first)
    second, created_again = helpers.upsert_entry(
        graph,
        title="VASP relaxation",
        content="Updated description.",
        entry_type=EntryType.capability,
        tags=["managed"],
        metadata=EntryMetadata(custom={"kind": "skill"}),
    )

    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert second.metadata.usage_count == 1
    assert set(second.tags) == {"matcreator-skill", "managed"}
    assert second.metadata.custom == {"managed_by": "matcreator", "kind": "skill"}
    graph.close()


def test_legacy_graph_migration_is_idempotent(tmp_path: Path) -> None:
    helpers = _load_helpers()
    skill_db = tmp_path / "skill.db"
    memory_db = tmp_path / "memory.db"
    _legacy_db(skill_db, "skill", "s1", "VASP relaxation")
    _legacy_db(memory_db, "memory", "m1", "FIRE converges reliably")

    graph = KnowDoGraph(tmp_path / "know-do.db", memory_dir=tmp_path / "memory-files")
    first = helpers.migrate_legacy_graphs(
        graph,
        skill_db=skill_db,
        memory_db=memory_db,
    )
    second = helpers.migrate_legacy_graphs(
        graph,
        skill_db=skill_db,
        memory_db=memory_db,
    )

    assert first["know_do_nodes"] == 1
    assert first["memory_entries"] == 1
    assert second == {"know_do_nodes": 0, "memory_entries": 0, "edges": 0}
    migrated = graph.search(
        "VASP relaxation",
        entry_type=EntryType.capability,
        mode="keyword",
    )
    assert migrated[0].entry_type == EntryType.capability
    memories = graph.memory("legacy-memory-graph").list()
    assert len(memories) == 1
    assert memories[0].promoted is False
    graph.close()


def test_native_memory_promotion_creates_refinement_edge(tmp_path: Path) -> None:
    helpers = _load_helpers()
    graph = KnowDoGraph(tmp_path / "know-do.db", memory_dir=tmp_path / "memory")
    memory = graph.memory("session-1").add(
        "FIRE is reliable for rough relaxation before tightening fmax.",
        success=True,
    )
    follow_up = graph.memory("session-1").add(
        "The result reproduced on another structure.",
        success=True,
    )
    edge = graph.memory("session-1").connect(memory.id, follow_up.id)

    durable, created = helpers.promote_memory(
        graph,
        memory,
        title="FIRE rough relaxation",
        content=memory.content,
    )

    assert created is True
    assert durable.entry_type == EntryType.heuristic
    assert durable.metadata.verification_status.value == "self_tested"
    assert graph.get(memory.id).entry_type == EntryType.memory
    assert graph.get(follow_up.id).entry_type == EntryType.memory
    assert edge.relation.value == "related_memory"
    assert not (tmp_path / "memory" / "session-1.json").exists()
    saved = graph.memory(memory.session_id).get(memory.id)
    assert saved.promoted is True
    assert saved.promotion_target_id == durable.id
    assert durable.id in {
        entry.id
        for entry in graph.related(memory.id, relation="refinement_of")
    }
    graph.close()


def test_unified_store_and_memgraph_migration(tmp_path: Path) -> None:
    helpers = _load_helpers()
    old_graph = KnowDoGraph(tmp_path / "old.db", memory_dir=tmp_path / "old-memory")
    source = old_graph.add(
        "ASE structure building",
        content="Build structures with ASE.",
        entry_type=EntryType.capability,
    )
    target = old_graph.add(
        "Validate structures",
        content="Run structural checks.",
        entry_type=EntryType.procedure,
    )
    old_graph.connect(source.id, target.id, relation="dependency")
    old_graph.memory("session-1").add("ASE built the structure.", success=True)
    old_graph.close()

    graph = KnowDoGraph(tmp_path / "new.db", memory_dir=tmp_path / "new-memory")
    first_graph = helpers.migrate_kdg_database(graph, tmp_path / "old.db")
    second_graph = helpers.migrate_kdg_database(graph, tmp_path / "old.db")

    assert first_graph == {"nodes": 3, "edges": 1}
    assert second_graph == {"nodes": 0, "edges": 0}
    copied = graph.memory("session-1").list()
    assert copied[0].content == "ASE built the structure."
    assert copied[0].success is True
    assert graph.get(copied[0].id).entry_type == EntryType.memory
    graph.close()


def test_synthesizer_distills_repeated_success(tmp_path: Path, monkeypatch) -> None:
    from agents.MatCreator.knowledge import synthesizer

    graph = KnowDoGraph(tmp_path / "know-do.db", memory_dir=tmp_path / "memory")
    for index in range(3):
        graph.memory(f"session-{index}").add(
            "FIRE rough relaxation works reliably before tightening fmax.",
            success=True,
        )
    monkeypatch.setattr(synthesizer, "_get_kg", lambda: graph)

    result = synthesizer.run_knowledge_synthesizer(
        stale_days=30,
        min_insights_for_workflow=3,
    )

    assert result["promoted"] == 1
    durable = graph.search(
        "FIRE rough relaxation",
        entry_type=EntryType.heuristic,
        mode="keyword",
    )
    assert len(durable) == 1
    assert all(
        entry.promoted
        for index in range(3)
        for entry in graph.memory(f"session-{index}").list()
    )
    graph.close()
