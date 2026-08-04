from pathlib import Path

import pytest
from pydantic import ValidationError

from genkai.contracts.artifacts import (
    ARTIFACT_ADAPTER,
    ArtifactRef,
    EvidenceLevel,
    ExecutionState,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.provenance import Provenance
from genkai.contracts.validation import ValidationIssue, ValidationReport


SHA256 = "a" * 64


def test_structure_set_round_trip_preserves_identity_and_relative_path() -> None:
    artifact = StructureSetArtifact(
        artifact_id="structure-1",
        path="artifacts/structures.extxyz",
        sha256=SHA256,
        producer="surface-modeling",
        parent_ids=["plan-1"],
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.HEURISTIC,
        validation_status=ValidationStatus.PASSED,
        provenance=Provenance(parameters={"facet": "111"}),
    )

    restored = ARTIFACT_ADAPTER.validate_json(artifact.model_dump_json())

    assert isinstance(restored, StructureSetArtifact)
    assert restored.artifact_id == "structure-1"
    assert restored.parent_ids == ["plan-1"]
    assert restored.evidence_level is EvidenceLevel.HEURISTIC
    assert restored.path == Path("artifacts/structures.extxyz")


@pytest.mark.parametrize("path", ["/tmp/output.extxyz", "../output.extxyz", "a/../../b"])
def test_artifact_rejects_paths_outside_run(path: str) -> None:
    with pytest.raises(ValidationError):
        StructureSetArtifact(
            artifact_id="structure-1",
            path=path,
            sha256=SHA256,
            producer="surface-modeling",
        )


def test_artifact_rejects_noncanonical_sha256() -> None:
    with pytest.raises(ValidationError):
        StructureSetArtifact(
            artifact_id="structure-1",
            path="artifacts/structures.extxyz",
            sha256="A" * 64,
            producer="surface-modeling",
        )


def test_all_stable_artifact_kinds_are_discriminated() -> None:
    expected = [
        "paper",
        "extraction",
        "modeling-plan",
        "structure-set",
        "calculation-input",
        "calculation-result",
        "dataset",
        "model",
        "evaluation",
    ]
    actual = []
    for index, artifact_type in enumerate(expected):
        artifact = ARTIFACT_ADAPTER.validate_python(
            {
                "artifact_type": artifact_type,
                "artifact_id": f"artifact-{index}",
                "path": f"artifacts/{index}.json",
                "sha256": SHA256,
                "producer": "test",
                "validation_status": "needs_review",
            }
        )
        actual.append(artifact.artifact_type)
    assert actual == expected


def test_validation_report_passes_only_without_errors() -> None:
    clean = ValidationReport(
        checks=[ValidationIssue(code="path_exists", message="artifact exists")]
    )
    failed = ValidationReport(
        errors=[ValidationIssue(code="invalid_hash", message="hash mismatch")]
    )

    assert clean.passed is True
    assert failed.passed is False
