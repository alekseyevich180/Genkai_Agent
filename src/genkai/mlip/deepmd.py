"""DeepMD training command preparation."""

from __future__ import annotations

from pathlib import Path

from genkai.contracts.artifacts import DatasetArtifact
from genkai.workflow.stage import StageResult

from .protocol import RunMode, training_dataset_gate


class DeepMDAdapter:
    """Prepare DeepMD training; never perform pretrained inference routing."""

    def prepare_training(
        self,
        dataset: DatasetArtifact,
        run_root: Path,
        mode: RunMode,
    ) -> StageResult:
        report = training_dataset_gate(dataset, mode)
        return StageResult(
            validation=report,
            command=[
                "deepmd-train",
                "--dataset",
                str(Path(run_root) / dataset.path),
                "--output-dir",
                str(Path(run_root) / "stages" / "06_mlip" / "deepmd"),
                "--mode",
                mode.value,
            ],
        )
