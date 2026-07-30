"""Shared protocol types for MLIP command preparation."""

from __future__ import annotations

from enum import Enum

from genkai.contracts.artifacts import DatasetArtifact, EvidenceLevel
from genkai.contracts.validation import ValidationIssue, ValidationReport


class RunMode(str, Enum):
    DRY_RUN = "dry-run"
    PRODUCTION = "production"


def training_dataset_gate(
    dataset: DatasetArtifact,
    mode: RunMode,
) -> ValidationReport:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    if dataset.evidence_level is EvidenceLevel.MOCK:
        issue = ValidationIssue(
            code="mock_labels_not_trainable",
            message="mock labels cannot be used for production model training",
            path=dataset.path.as_posix(),
        )
        if mode is RunMode.PRODUCTION:
            errors.append(issue)
        else:
            warnings.append(issue)
    return ValidationReport(errors=errors, warnings=warnings)
