from __future__ import annotations

from know_do_graph import EntryType, VerificationStatus

from agents.MatCreator.knowledge import query


class _RecordingGraph:
    def __init__(self) -> None:
        self.options: dict | None = None

    def auto_review(self, **options):
        self.options = options
        return object()

    def list(self, *, limit=50, offset=0):
        return []


def test_auto_review_uses_matcreator_policy(monkeypatch) -> None:
    graph = _RecordingGraph()
    monkeypatch.setenv("MATCREATOR_AUTO_REVIEW", "1")
    monkeypatch.setenv("MATCREATOR_REVIEW_TRIGGER_THRESHOLD", "12")
    monkeypatch.setenv("MATCREATOR_REVIEW_BATCH_SIZE", "7")
    monkeypatch.setenv("MATCREATOR_REVIEW_STRATEGY", "seed")
    monkeypatch.setenv("REVIEW_AGENT_MODEL", "review-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")

    query._configure_auto_review(graph)

    assert graph.options is not None
    policy = graph.options["policy"]
    assert graph.options["threshold"] == 12
    assert graph.options["batch_size"] == 7
    assert graph.options["strategy"] == "seed"
    assert graph.options["include_existing"] is True
    assert graph.options["model"] == "review-model"
    assert policy.exclude_types == frozenset({EntryType.memory})
    assert policy.protected_statuses == frozenset(
        {
            VerificationStatus.peer_reviewed,
            VerificationStatus.community_tested,
        }
    )
    assert policy.assignable_statuses == frozenset(
        {
            VerificationStatus.unverified,
            VerificationStatus.self_tested,
            VerificationStatus.bugged,
            VerificationStatus.deprecated,
        }
    )
    assert policy.allowed_actions == frozenset(
        {"modify", "delete", "distill", "merge_similar", "link"}
    )


def test_auto_review_can_be_disabled(monkeypatch) -> None:
    graph = _RecordingGraph()
    monkeypatch.setenv("MATCREATOR_AUTO_REVIEW", "false")

    query._configure_auto_review(graph)

    assert graph.options is None
