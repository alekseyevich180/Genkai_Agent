"""MACE inference and relaxation command preparation."""

from __future__ import annotations

from pathlib import Path

from genkai.contracts.artifacts import StructureSetArtifact
from genkai.contracts.validation import ValidationIssue, ValidationReport
from genkai.workflow.stage import StageResult

from .protocol import RunMode


class MaceAdapter:
    """Prepare pretrained MACE inference; never train a model."""

    def prepare_inference(
        self,
        structures: StructureSetArtifact,
        run_root: Path,
        mode: RunMode,
    ) -> StageResult:
        report = ValidationReport(
            checks=[
                ValidationIssue(
                    code="mace_structure_input_valid",
                    message="MACE inference consumes a structure-set artifact",
                )
            ]
        )
        return StageResult(
            validation=report,
            command=[
                "mace-inference",
                "--structures",
                str(Path(run_root) / structures.path),
                "--output-dir",
                str(Path(run_root) / "stages" / "06_mlip" / "mace"),
                "--mode",
                mode.value,
            ],
        )
