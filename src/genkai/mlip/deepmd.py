"""DeepMD training command preparation."""

from __future__ import annotations

from pathlib import Path

from genkai.contracts.artifacts import DatasetArtifact
from genkai.workflow.stage import StageResult

from .protocol import RunMode, training_dataset_gate


class DeepMDAdapter:
    """Prepare DeepMD training; never perform pretrained inference routing."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = executable

    def prepare_training(
        self,
        dataset: DatasetArtifact,
        run_root: Path,
        mode: RunMode,
    ) -> StageResult:
        report = training_dataset_gate(dataset, run_root, mode)
        from .protocol import resolve_executable

        executable = resolve_executable(
            self.executable,
            "GENKAI_DEEPMD_EXECUTABLE",
            mode,
            report.errors,
            report.warnings,
        )
        if executable is None:
            return StageResult(validation=report)
        return StageResult(
            validation=report,
            command=[
                executable,
                "--dataset",
                str(Path(run_root) / dataset.path),
                "--output-dir",
                str(Path(run_root) / "stages" / "06_mlip" / "deepmd"),
                "--mode",
                mode.value,
            ],
        )
