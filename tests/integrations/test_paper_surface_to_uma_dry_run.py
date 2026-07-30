from pathlib import Path

from genkai.mlip.protocol import RunMode
from genkai.workflow.store import load_manifest
from genkai.workflows.paper_to_mlip import (
    initialize_paper_to_mlip_run,
    preflight_paper_to_mlip,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "paper_to_mlip"


def test_paper_surface_to_uma_dry_run_preserves_mock_evidence_boundary(
    tmp_path: Path,
) -> None:
    initialize_paper_to_mlip_run(
        tmp_path,
        FIXTURES / "minimal_surface_relations.jsonl",
        mock_labels=FIXTURES / "mock_labels.extxyz",
        base_model_uri="file:///shared/uma/checkpoint.pt",
    )
    production = preflight_paper_to_mlip(
        tmp_path, "uma", RunMode.PRODUCTION
    )
    dry_run = preflight_paper_to_mlip(tmp_path, "uma", RunMode.DRY_RUN)
    manifest = load_manifest(tmp_path)

    assert production.passed is False
    assert dry_run.passed is True
    assert [item.artifact_type for item in manifest.artifacts] == [
        "paper",
        "extraction",
        "modeling-plan",
        "structure-set",
        "calculation-input",
        "calculation-result",
        "dataset",
    ]
    result = next(
        item
        for item in manifest.artifacts
        if item.artifact_type == "calculation-result"
    )
    dataset = next(
        item for item in manifest.artifacts if item.artifact_type == "dataset"
    )
    assert result.evidence_level.value == "mock"
    assert dataset.evidence_level.value == "mock"
    assert result.evidence_level.value != "dft_calculated"
    assert manifest.external_resources[0].resource_type == "uma-checkpoint"
    assert "base_model_uri" not in manifest.metadata
    assert manifest.stages[-1].stage_id == "06_uma_preflight_dry_run"
    assert manifest.stages[-1].execution_state.value == "prepared"
