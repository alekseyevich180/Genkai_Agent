"""Shared protocol types for MLIP command preparation."""

from __future__ import annotations

import hashlib
import os
import shutil
from enum import Enum
from pathlib import Path
from typing import Any

from genkai.contracts.artifacts import (
    DatasetArtifact,
    EvidenceLevel,
    ExecutionState,
    ValidationStatus,
)
from genkai.contracts.validation import ValidationIssue, ValidationReport


class RunMode(str, Enum):
    DRY_RUN = "dry-run"
    PRODUCTION = "production"


def _route_issue(
    issue: ValidationIssue,
    mode: RunMode,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    (errors if mode is RunMode.PRODUCTION else warnings).append(issue)


def resolve_launcher(
    configured: str | Path | None,
    environment_variable: str,
    required_markers: tuple[str, ...],
    mode: RunMode,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> str | None:
    """Resolve a launcher and verify the environment protocol it implements."""

    candidate = str(configured or os.environ.get(environment_variable, "")).strip()
    resolved = shutil.which(candidate) if candidate else None
    if resolved is None:
        issue = ValidationIssue(
            code="runtime_executable_required",
            message=(
                f"configure an executable with {environment_variable}; "
                "the adapter will not guess an external runtime"
            ),
            path=candidate or None,
        )
        _route_issue(issue, mode, errors, warnings)
        return None
    launcher = Path(resolved)
    try:
        text = launcher.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        _route_issue(
            ValidationIssue(
                code="runtime_launcher_protocol_mismatch",
                message=(
                    "configured launcher does not implement required environment "
                    "variables: " + ", ".join(missing)
                ),
                path=str(launcher),
            ),
            mode,
            errors,
            warnings,
        )
        return None
    return str(launcher)


def artifact_integrity_gate(
    artifact: Any,
    run_root: str | Path,
    mode: RunMode,
) -> ValidationReport:
    """Verify a run-local artifact before it can unlock production work."""

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    root = Path(run_root).resolve()
    path = (root / artifact.path).resolve()
    if not path.is_relative_to(root):
        _route_issue(
            ValidationIssue(
                code="artifact_path_escape",
                message="artifact path escapes the authorized run root",
                path=str(path),
            ),
            mode,
            errors,
            warnings,
        )
    elif not path.is_file():
        _route_issue(
            ValidationIssue(
                code="artifact_file_missing",
                message="artifact file does not exist",
                path=str(path),
            ),
            mode,
            errors,
            warnings,
        )
    else:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != artifact.sha256:
            _route_issue(
                ValidationIssue(
                    code="artifact_hash_mismatch",
                    message="artifact SHA-256 does not match the manifest",
                    path=str(path),
                ),
                mode,
                errors,
                warnings,
            )
    if artifact.validation_status is not ValidationStatus.PASSED:
        _route_issue(
            ValidationIssue(
                code="artifact_not_validated",
                message="production inputs must have validation_status=passed",
                path=artifact.path.as_posix(),
            ),
            mode,
            errors,
            warnings,
        )
    if artifact.execution_state is not ExecutionState.SUCCEEDED:
        _route_issue(
            ValidationIssue(
                code="artifact_not_succeeded",
                message="production inputs must have execution_state=succeeded",
                path=artifact.path.as_posix(),
            ),
            mode,
            errors,
            warnings,
        )
    return ValidationReport(errors=errors, warnings=warnings)


def training_dataset_gate(
    dataset: DatasetArtifact,
    run_root: str | Path,
    mode: RunMode,
) -> ValidationReport:
    report = artifact_integrity_gate(dataset, run_root, mode)
    errors = report.errors
    warnings = report.warnings
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
    elif dataset.evidence_level not in {
        EvidenceLevel.DFT_CALCULATED,
        EvidenceLevel.EXPERIMENT_REPORTED,
    }:
        _route_issue(
            ValidationIssue(
                code="unsupported_training_evidence",
                message="training requires DFT-calculated or experiment-reported labels",
                path=dataset.path.as_posix(),
            ),
            mode,
            errors,
            warnings,
        )
    if dataset.metadata.get("audit_status") != "PASS":
        _route_issue(
            ValidationIssue(
                code="dataset_audit_required",
                message="production training requires a passed file-derived dataset audit",
                path=dataset.path.as_posix(),
            ),
            mode,
            errors,
            warnings,
        )
    inventory = dataset.metadata.get("split_inventory")
    if not isinstance(inventory, list) or not inventory:
        _route_issue(
            ValidationIssue(
                code="dataset_split_inventory_required",
                message="dataset requires a nonempty content-addressed split inventory",
                path=dataset.path.as_posix(),
            ),
            mode,
            errors,
            warnings,
        )
    else:
        root = Path(run_root).resolve()
        for item in inventory:
            if not isinstance(item, dict):
                _route_issue(
                    ValidationIssue(
                        code="invalid_dataset_split_inventory",
                        message="split inventory entries must be mappings",
                    ),
                    mode,
                    errors,
                    warnings,
                )
                continue
            raw_path = item.get("path")
            expected = item.get("sha256")
            path = (root / str(raw_path)).resolve()
            if (
                not isinstance(raw_path, str)
                or not path.is_relative_to(root)
                or not path.is_file()
            ):
                _route_issue(
                    ValidationIssue(
                        code="dataset_split_file_missing",
                        message="an inventoried dataset split file is missing",
                        path=str(path),
                    ),
                    mode,
                    errors,
                    warnings,
                )
            elif (
                not isinstance(expected, str)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                _route_issue(
                    ValidationIssue(
                        code="dataset_split_hash_mismatch",
                        message="an inventoried dataset split file changed after audit",
                        path=str(path),
                    ),
                    mode,
                    errors,
                    warnings,
                )
    for key in ("train_count", "validation_count"):
        if int(dataset.metadata.get(key, 0)) <= 0:
            _route_issue(
                ValidationIssue(
                    code=f"nonempty_{key}_required",
                    message=f"production training requires a nonempty {key}",
                    path=dataset.path.as_posix(),
                ),
                mode,
                errors,
                warnings,
            )
    return report
