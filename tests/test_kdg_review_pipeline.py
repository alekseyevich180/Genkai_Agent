from __future__ import annotations

from types import SimpleNamespace

from know_do_graph import EntryType, VerificationStatus

from agents.MatCreator.knowledge.review import run_review_pipeline


def _entry(entry_type, *, reviewed=0, status=VerificationStatus.unverified, memory=None):
    return SimpleNamespace(
        entry_type=entry_type,
        metadata=SimpleNamespace(
            review_count=reviewed,
            verification_status=status,
            custom={"memory": memory or {}},
        ),
    )


class _ReviewSession:
    def __init__(self, graph, on_status):
        self.graph = graph
        self.on_status = on_status

    def review_memory(self):
        self.graph.calls.append("memory")
        if self.on_status:
            self.on_status(
                {
                    "status": "running",
                    "progress": {"completed": 0, "total": 1, "percent": 0},
                    "results": [],
                    "errors": [],
                    "summary": "",
                }
            )
        return {
            "status": "completed",
            "progress": {"completed": 1, "total": 1, "percent": 100},
            "results": [{"action": "promoted"}],
            "errors": [],
            "summary": "Memory reviewed.",
        }

    def review_nodes(self):
        self.graph.calls.append("graph")
        if self.on_status:
            self.on_status(
                {
                    "status": "running",
                    "progress": {"completed": 0, "total": 2, "percent": 0},
                    "results": [],
                    "errors": [],
                    "summary": "",
                }
            )
        return {
            "status": "completed",
            "progress": {"completed": 2, "total": 2, "percent": 100},
            "results": [{"action": "modify"}, {"action": "link"}],
            "errors": [],
            "summary": "Graph reviewed.",
        }


class _Graph:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def search(self, **kwargs):
        return [
            entry for entry in self.entries if entry.entry_type == EntryType.memory
        ]

    def list(self, *, limit=50, offset=0):
        return self.entries[offset : offset + limit]

    def chat(self, **kwargs):
        return _ReviewSession(self, kwargs.get("on_status"))

    def refresh(self):
        return {}


def test_pipeline_reviews_memory_before_graph() -> None:
    graph = _Graph(
        [
            _entry(EntryType.memory, memory={"promoted": False}),
            _entry(EntryType.heuristic),
            _entry(EntryType.procedure),
        ]
    )
    phases = []

    result = run_review_pipeline(
        graph,
        model="test-model",
        api_key="test-key",
        threshold=2,
        on_status=lambda phase, status: phases.append(phase),
    )

    assert graph.calls == ["memory", "graph"]
    assert phases == ["memory", "graph"]
    assert result["memory_review"] is not None
    assert result["graph_review"] is not None
    assert result["progress"] == {"completed": 3, "total": 3, "percent": 100}


def test_pipeline_runs_graph_without_memory_when_threshold_is_met() -> None:
    graph = _Graph([_entry(EntryType.heuristic), _entry(EntryType.procedure)])

    result = run_review_pipeline(
        graph,
        model="test-model",
        api_key="test-key",
        threshold=2,
    )

    assert graph.calls == ["graph"]
    assert result["memory_review"] is None
    assert result["graph_review"] is not None


def test_pipeline_skips_graph_below_threshold() -> None:
    graph = _Graph([_entry(EntryType.heuristic)])

    result = run_review_pipeline(
        graph,
        model="test-model",
        api_key="test-key",
        threshold=2,
    )

    assert graph.calls == []
    assert result["graph_review"] is None
    assert "threshold 2" in result["summary"]
