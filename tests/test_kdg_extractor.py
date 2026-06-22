from __future__ import annotations

import json
from types import SimpleNamespace

from agents.MatCreator.knowledge import extractor


class _MemoryStore:
    def __init__(self) -> None:
        self.entries = []

    def list(self):
        return list(self.entries)


class _Graph:
    def __init__(self) -> None:
        self.store = _MemoryStore()

    def memory(self, session_id):
        return self.store

    def search(self, *args, **kwargs):
        return []


def _trajectory_line(step: int, summary: str) -> str:
    return json.dumps(
        {
            "step_index": step,
            "active_skill": "test-skill",
            "concise_summary": summary,
        }
    )


def test_extractor_skips_unchanged_session_and_processes_only_delta(
    tmp_path,
    monkeypatch,
) -> None:
    session_id = "session-1"
    trajectory_dir = tmp_path / "trajectories"
    trajectory_dir.mkdir()
    trajectory_path = trajectory_dir / f"{session_id}.jsonl"
    trajectory_path.write_text(_trajectory_line(1, "first result") + "\n")

    graph = _Graph()
    cursor = {session_id: 0}
    prompts = []

    monkeypatch.setattr(extractor, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(extractor, "_get_kg", lambda: graph)
    monkeypatch.setattr(
        extractor,
        "get_extraction_cursor",
        lambda sid: cursor.get(sid, 0),
    )
    monkeypatch.setattr(
        extractor,
        "has_extraction_record",
        lambda sid: sid in cursor and cursor[sid] > 0,
    )
    monkeypatch.setattr(
        extractor,
        "record_extraction",
        lambda sid, lines: cursor.__setitem__(sid, lines),
    )

    def call_llm(prompt):
        prompts.append(prompt)
        return json.dumps(
            [
                {
                    "name": "Result",
                    "description": "Reusable finding",
                    "relations": [],
                }
            ]
        )

    monkeypatch.setattr(extractor, "_call_llm", call_llm)

    def add_memory(graph_arg, sid, content, **kwargs):
        memory = SimpleNamespace(id=f"m{len(graph.store.entries) + 1}", content=content)
        graph.store.entries.append(memory)
        return memory

    monkeypatch.setattr(extractor, "add_memory", add_memory)

    first = extractor.run_knowledge_extractor(session_id)
    repeated = extractor.run_knowledge_extractor(session_id)
    trajectory_path.write_text(
        _trajectory_line(1, "first result")
        + "\n"
        + _trajectory_line(2, "second result")
        + "\n"
    )
    incremental = extractor.run_knowledge_extractor(session_id)

    assert first["nodes_created"] == 1
    assert repeated["status"] == "skipped"
    assert incremental["nodes_created"] == 0
    assert len(prompts) == 2
    assert "first result" in prompts[0]
    assert "first result" not in prompts[1]
    assert "second result" in prompts[1]
    assert cursor[session_id] == 2
    assert len(graph.store.entries) == 1


def test_extractor_advances_cursor_for_empty_valid_response(tmp_path, monkeypatch) -> None:
    session_id = "session-2"
    trajectory_dir = tmp_path / "trajectories"
    trajectory_dir.mkdir()
    (trajectory_dir / f"{session_id}.jsonl").write_text(
        _trajectory_line(1, "nothing reusable") + "\n"
    )
    cursor = {session_id: 0}

    monkeypatch.setattr(extractor, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(
        extractor,
        "get_extraction_cursor",
        lambda sid: cursor.get(sid, 0),
    )
    monkeypatch.setattr(
        extractor,
        "has_extraction_record",
        lambda sid: sid in cursor and cursor[sid] > 0,
    )
    monkeypatch.setattr(
        extractor,
        "record_extraction",
        lambda sid, lines: cursor.__setitem__(sid, lines),
    )
    monkeypatch.setattr(extractor, "_call_llm", lambda prompt: "[]")

    first = extractor.run_knowledge_extractor(session_id)
    repeated = extractor.run_knowledge_extractor(session_id)

    assert first["status"] == "ok"
    assert repeated["status"] == "skipped"
    assert cursor[session_id] == 1


def test_extractor_migrates_legacy_extracted_session(tmp_path, monkeypatch) -> None:
    session_id = "session-legacy"
    trajectory_dir = tmp_path / "trajectories"
    trajectory_dir.mkdir()
    (trajectory_dir / f"{session_id}.jsonl").write_text(
        _trajectory_line(1, "already extracted") + "\n"
    )
    graph = _Graph()
    graph.store.entries.append(
        SimpleNamespace(
            id="old-memory",
            content="Existing memory",
            tags=["extracted", "successful-execution"],
        )
    )
    cursor = {}

    monkeypatch.setattr(extractor, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(extractor, "_get_kg", lambda: graph)
    monkeypatch.setattr(extractor, "get_extraction_cursor", lambda sid: 0)
    monkeypatch.setattr(extractor, "has_extraction_record", lambda sid: False)
    monkeypatch.setattr(
        extractor,
        "record_extraction",
        lambda sid, lines: cursor.__setitem__(sid, lines),
    )
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        lambda prompt: (_ for _ in ()).throw(AssertionError("LLM should not run")),
    )

    result = extractor.run_knowledge_extractor(session_id)

    assert result["status"] == "skipped"
    assert cursor[session_id] == 1
