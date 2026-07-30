"""MACE inference and relaxation command preparation."""

from __future__ import annotations

from pathlib import Path

import hashlib
from ase.io import read

from genkai.contracts.artifacts import StructureSetArtifact
from genkai.contracts.validation import ValidationIssue, ValidationReport
from genkai.workflow.stage import StageResult

from .protocol import (
    RunMode,
    _route_issue,
    artifact_integrity_gate,
    resolve_launcher,
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
        root = Path(run_root).resolve()
        raw_inventory = structures.metadata.get("structure_inventory")
        inventory = (
            raw_inventory
            if isinstance(raw_inventory, list) and raw_inventory
            else [
                {
                    "path": structures.path.as_posix(),
                    "sha256": structures.sha256,
                }
            ]
        )
        actual_count = 0
        verified_paths: list[Path] = []
        for item in inventory:
            raw_path = item.get("path") if isinstance(item, dict) else None
            expected = item.get("sha256") if isinstance(item, dict) else None
            path = (root / str(raw_path)).resolve()
            if (
                not isinstance(raw_path, str)
                or not path.is_relative_to(root)
                or not path.is_file()
            ):
                _route_issue(
                    ValidationIssue(
                        code="mace_structure_file_missing",
                        message="an inventoried structure file is missing",
                        path=str(path),
                    ),
                    mode,
                    report.errors,
                    report.warnings,
                )
                continue
            if (
                not isinstance(expected, str)
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected
            ):
                _route_issue(
                    ValidationIssue(
                        code="mace_structure_hash_mismatch",
                        message="an inventoried structure file changed",
                        path=str(path),
                    ),
                    mode,
                    report.errors,
                    report.warnings,
                )
                continue
            try:
                frames = read(path, index=":")
            except Exception as exc:
                _route_issue(
                    ValidationIssue(
                        code="mace_structure_read_failed",
                        message=f"ASE could not read structure file: {exc}",
                        path=str(path),
                    ),
                    mode,
                    report.errors,
                    report.warnings,
                )
                continue
            actual_count += len(frames) if isinstance(frames, list) else 1
            verified_paths.append(path)
        if actual_count <= 0:
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
        if len(verified_paths) != 1:
            _route_issue(
                ValidationIssue(
                    code="mace_single_input_required",
                    message=(
                        "the established MACE launcher accepts exactly one "
                        "ASE-readable input file per command"
                    ),
                    path=structures.path.as_posix(),
                ),
                mode,
                report.errors,
                report.warnings,
            )
        declared_count = int(structures.metadata.get("structure_count", 0))
        if declared_count != actual_count:
            _route_issue(
                ValidationIssue(
                    code="structure_count_mismatch",
                    message=(
                        f"declared structure_count={declared_count}, "
                        f"but ASE read {actual_count}"
                    ),
                    path=structures.path.as_posix(),
                ),
                mode,
                report.errors,
                report.warnings,
            )
        executable = resolve_launcher(
            self.executable,
            "GENKAI_MACE_LAUNCHER",
            ("MACE_WORK_DIR", "MACE_PYTHON_ARGS", "MACE_DRY_RUN"),
            mode,
            report.errors,
            report.warnings,
        )
        if executable is None:
            return StageResult(validation=report)
        structure_path = str(
            verified_paths[0]
            if verified_paths
            else (Path(run_root) / structures.path).resolve()
        )
        output_dir = str((Path(run_root) / "stages" / "06_mlip" / "mace").resolve())
        report.checks.append(
            ValidationIssue(
                code="mace_structure_input_valid",
                message="MACE inference consumes a verified structure-set artifact",
            )
        )
        return StageResult(
            validation=report,
            command=[executable],
            environment={
                "MACE_WORK_DIR": str(Path(run_root).resolve()),
                "MACE_PYTHON_ARGS": (
                    f"--input {structure_path} --output-dir {output_dir}"
                ),
                "MACE_DRY_RUN": "1" if mode is RunMode.DRY_RUN else "0",
            },
        )
