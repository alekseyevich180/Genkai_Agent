"""UMA fine-tuning command preparation."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

import hashlib

from genkai.contracts.artifacts import (
    DatasetArtifact,
    ExternalResourceRef,
    ModelArtifact,
)
from genkai.contracts.validation import ValidationIssue
from genkai.workflow.stage import StageResult

from .protocol import (
    RunMode,
    _route_issue,
    artifact_integrity_gate,
    resolve_executable,
    training_dataset_gate,
)


class UmaAdapter:
    """Prepare UMA fine-tuning with dataset-specific safety gates."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = executable

    def prepare_finetuning(
        self,
        dataset: DatasetArtifact,
        base_model: ModelArtifact | ExternalResourceRef,
        run_root: Path,
        mode: RunMode,
    ) -> StageResult:
        report = training_dataset_gate(dataset, run_root, mode)
        metadata = dataset.metadata
        if int(metadata.get("test_count", 0)) <= 0:
            _route_issue(
                ValidationIssue(
                    code="uma_test_split_required",
                    message="UMA fine-tuning requires an independent test split",
                ),
                mode,
                report.errors,
                report.warnings,
            )
        if int(metadata.get("cross_split_leakage", 0)) != 0:
            _route_issue(
                ValidationIssue(
                    code="uma_split_leakage",
                    message="UMA fine-tuning rejects cross-split structure leakage",
                ),
                mode,
                report.errors,
                report.warnings,
            )
        if metadata.get("lmdb_readback") is not True:
            _route_issue(
                ValidationIssue(
                    code="uma_lmdb_readback_required",
                    message="UMA fine-tuning requires successful ASE-LMDB readback",
                ),
                mode,
                report.errors,
                report.warnings,
            )
        if isinstance(base_model, ExternalResourceRef):
            if not base_model.version or not base_model.sha256:
                _route_issue(
                    ValidationIssue(
                        code="uma_base_model_identity_required",
                        message=(
                            "UMA production requires base checkpoint version and SHA-256"
                        ),
                        path=base_model.uri,
                    ),
                    mode,
                    report.errors,
                    report.warnings,
                )
            parsed = urlparse(base_model.uri)
            if parsed.scheme == "file":
                checkpoint = Path(unquote(parsed.path))
                if not checkpoint.is_file():
                    _route_issue(
                        ValidationIssue(
                            code="uma_base_model_missing",
                            message="UMA base checkpoint file does not exist",
                            path=str(checkpoint),
                        ),
                        mode,
                        report.errors,
                        report.warnings,
                    )
                elif (
                    base_model.sha256
                    and hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                    != base_model.sha256
                ):
                    _route_issue(
                        ValidationIssue(
                            code="uma_base_model_hash_mismatch",
                            message="UMA base checkpoint SHA-256 does not match",
                            path=str(checkpoint),
                        ),
                        mode,
                        report.errors,
                        report.warnings,
                    )
        else:
            model_report = artifact_integrity_gate(base_model, run_root, mode)
            report.errors.extend(model_report.errors)
            report.warnings.extend(model_report.warnings)
        executable = resolve_executable(
            self.executable,
            "GENKAI_UMA_EXECUTABLE",
            mode,
            report.errors,
            report.warnings,
        )
        if executable is None:
            return StageResult(validation=report)
        base_uri = (
            base_model.uri
            if isinstance(base_model, ExternalResourceRef)
            else str(Path(run_root) / base_model.path)
        )
        return StageResult(
            validation=report,
            command=[
                executable,
                "--dataset",
                str(Path(run_root) / dataset.path),
                "--base-model",
                base_uri,
                "--output-dir",
                str(Path(run_root) / "stages" / "06_mlip" / "uma"),
                "--mode",
                mode.value,
            ],
        )
