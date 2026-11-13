"""DeepMD training command preparation."""

from __future__ import annotations

import hashlib
from pathlib import Path

from genkai.contracts.artifacts import DatasetArtifact
from genkai.contracts.validation import ValidationIssue
from genkai.workflow.stage import StageResult

from .protocol import RunMode, _route_issue, training_dataset_gate
from .launchers import get_launcher_contract


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
        from .protocol import resolve_launcher
        contract = get_launcher_contract("deepmd")

        root = Path(run_root).resolve()
        config_value = dataset.metadata.get("deepmd_input_path")
        config_sha256 = dataset.metadata.get("deepmd_input_sha256")
        config_path = (
            (root / config_value).resolve()
            if isinstance(config_value, str)
            else None
        )
        if (
            config_path is None
            or not config_path.is_relative_to(root)
            or not config_path.is_file()
        ):
            _route_issue(
                ValidationIssue(
                    code="deepmd_input_required",
                    message="DeepMD training requires a run-local input JSON",
                    path=str(config_path) if config_path else None,
                ),
                mode,
                report.errors,
                report.warnings,
            )
        elif (
            not isinstance(config_sha256, str)
            or hashlib.sha256(config_path.read_bytes()).hexdigest()
            != config_sha256
        ):
            _route_issue(
                ValidationIssue(
                    code="deepmd_input_hash_mismatch",
                    message="DeepMD input JSON changed after dataset validation",
                    path=str(config_path),
                ),
                mode,
                report.errors,
                report.warnings,
            )
        executable = resolve_launcher(
            self.executable,
            contract.environment_variable,
            contract.required_markers,
            mode,
            report.errors,
            report.warnings,
        )
        if executable is None:
            return StageResult(validation=report)
        required_paths = [str((root / dataset.path).resolve())]
        inventory = dataset.metadata.get("split_inventory")
        if isinstance(inventory, list):
            required_paths.extend(
                str((root / item["path"]).resolve())
                for item in inventory
                if isinstance(item, dict) and isinstance(item.get("path"), str)
            )
        return StageResult(
            validation=report,
            command=[executable],
            environment={
                "DEEPMD_WORK_DIR": str(root),
                "DEEPMD_COMMAND": "train",
                "DEEPMD_ARGS": str(config_path or ""),
                "DEEPMD_REQUIRED_PATHS": " ".join(required_paths),
                "DEEPMD_DRY_RUN": "1" if mode is RunMode.DRY_RUN else "0",
            },
        )
