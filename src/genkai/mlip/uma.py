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
    resolve_launcher,
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
                _route_issue(
                    ValidationIssue(
                        code="uma_base_model_file_required",
                        message=(
                            "the established UMA launcher requires a verified "
                            "local checkpoint file"
                        ),
                        path=base_model.uri,
                    ),
                    mode,
                    report.errors,
                    report.warnings,
                )
        else:
            model_report = artifact_integrity_gate(base_model, run_root, mode)
            report.errors.extend(model_report.errors)
            report.warnings.extend(model_report.warnings)
        config_path = metadata.get("uma_config_path")
        config_sha256 = metadata.get("uma_config_sha256")
        resolved_config: Path | None = None
        if isinstance(config_path, str):
            resolved_config = (Path(run_root).resolve() / config_path).resolve()
        if (
            resolved_config is None
            or not resolved_config.is_relative_to(Path(run_root).resolve())
            or not resolved_config.is_file()
        ):
            _route_issue(
                ValidationIssue(
                    code="uma_config_required",
                    message="UMA fine-tuning requires a run-local Hydra config",
                    path=str(resolved_config) if resolved_config else None,
                ),
                mode,
                report.errors,
                report.warnings,
            )
        elif (
            not isinstance(config_sha256, str)
            or hashlib.sha256(resolved_config.read_bytes()).hexdigest()
            != config_sha256
        ):
            _route_issue(
                ValidationIssue(
                    code="uma_config_hash_mismatch",
                    message="UMA fine-tuning config changed after dataset validation",
                    path=str(resolved_config),
                ),
                mode,
                report.errors,
                report.warnings,
            )
        executable = resolve_launcher(
            self.executable,
            "GENKAI_UMA_LAUNCHER",
            (
                "UMA_FINETUNE_WORK_DIR",
                "UMA_FINETUNE_CONFIG",
                "UMA_FINETUNE_DRY_RUN",
                "UMA_FINETUNE_BASE_MODEL_PATH",
                "UMA_FINETUNE_BASE_MODEL_SHA256",
            ),
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
        base_path = (
            Path(unquote(urlparse(base_uri).path))
            if isinstance(base_model, ExternalResourceRef)
            else (Path(run_root) / base_model.path).resolve()
        )
        base_sha256 = base_model.sha256 or ""
        return StageResult(
            validation=report,
            command=[executable],
            environment={
                "UMA_FINETUNE_WORK_DIR": str(Path(run_root).resolve()),
                "UMA_FINETUNE_CONFIG": str(resolved_config or ""),
                "UMA_FINETUNE_DRY_RUN": (
                    "1" if mode is RunMode.DRY_RUN else "0"
                ),
                "UMA_FINETUNE_BASE_MODEL_PATH": str(base_path),
                "UMA_FINETUNE_BASE_MODEL_SHA256": base_sha256,
            },
        )
