"""UMA fine-tuning command preparation."""

from __future__ import annotations

from pathlib import Path

from genkai.contracts.artifacts import (
    DatasetArtifact,
    ExternalResourceRef,
    ModelArtifact,
)
from genkai.contracts.validation import ValidationIssue
from genkai.workflow.stage import StageResult

from .protocol import RunMode, training_dataset_gate


class UmaAdapter:
    """Prepare UMA fine-tuning with dataset-specific safety gates."""

    def prepare_finetuning(
        self,
        dataset: DatasetArtifact,
        base_model: ModelArtifact | ExternalResourceRef,
        run_root: Path,
        mode: RunMode,
    ) -> StageResult:
        report = training_dataset_gate(dataset, mode)
        metadata = dataset.metadata
        if int(metadata.get("test_count", 0)) <= 0:
            report.errors.append(
                ValidationIssue(
                    code="uma_test_split_required",
                    message="UMA fine-tuning requires an independent test split",
                )
            )
        if int(metadata.get("cross_split_leakage", 0)) != 0:
            report.errors.append(
                ValidationIssue(
                    code="uma_split_leakage",
                    message="UMA fine-tuning rejects cross-split structure leakage",
                )
            )
        if metadata.get("lmdb_readback") is not True:
            report.errors.append(
                ValidationIssue(
                    code="uma_lmdb_readback_required",
                    message="UMA fine-tuning requires successful ASE-LMDB readback",
                )
            )
        base_uri = (
            base_model.uri
            if isinstance(base_model, ExternalResourceRef)
            else str(Path(run_root) / base_model.path)
        )
        return StageResult(
            validation=report,
            command=[
                "uma-finetune",
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
