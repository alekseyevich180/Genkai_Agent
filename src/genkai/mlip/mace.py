"""MACE inference and relaxation command preparation."""

from __future__ import annotations

from pathlib import Path

from genkai.contracts.artifacts import StructureSetArtifact
from genkai.contracts.validation import ValidationIssue, ValidationReport
from genkai.workflow.stage import StageResult

from .protocol import (
    RunMode,
    _route_issue,
    artifact_integrity_gate,
    resolve_executable,
)


class MaceAdapter:
    """Prepare pretrained MACE inference; never train a model."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = executable

    def prepare_inference(
        self,
        structures: StructureSetArtifact,
        run_root: Path,
        mode: RunMode,
    ) -> StageResult:
        report = artifact_integrity_gate(structures, run_root, mode)
        if int(structures.metadata.get("structure_count", 0)) <= 0:
            _route_issue(
                ValidationIssue(
                    code="empty_structure_set",
                    message="MACE inference requires at least one structure",
                    path=structures.path.as_posix(),
                ),
                mode,
                report.errors,
                report.warnings,
            )
        executable = resolve_executable(
            self.executable,
            "GENKAI_MACE_EXECUTABLE",
            mode,
            report.errors,
            report.warnings,
        )
        if executable is None:
            return StageResult(validation=report)
        report.checks.append(
            ValidationIssue(
                code="mace_structure_input_valid",
                message="MACE inference consumes a verified structure-set artifact",
            )
        )
        return StageResult(
            validation=report,
            command=[
                executable,
                "--structures",
                str(Path(run_root) / structures.path),
                "--output-dir",
                str(Path(run_root) / "stages" / "06_mlip" / "mace"),
                "--mode",
                mode.value,
            ],
        )
