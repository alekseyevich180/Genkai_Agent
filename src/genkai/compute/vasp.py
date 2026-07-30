"""VASP preparation and collection adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from genkai.contracts.artifacts import (
    CalculationInputArtifact,
    CalculationResultArtifact,
    EvidenceLevel,
    ExecutionState,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.run import StageRecord
from genkai.workflow.store import load_manifest, save_manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_vasp_inputs(
    structures: StructureSetArtifact,
    run_root: str | Path,
) -> CalculationInputArtifact:
    """Write a VASP preparation specification without submitting a job."""

    root = Path(run_root)
    manifest = load_manifest(root)
    path = root / "stages" / "04_dft" / "input-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "execution_state": "prepared",
                "source_structure_set": structures.path.as_posix(),
                "calculation": "vasp",
                "submission": None,
                "note": "Input preparation only; VASP and scheduler were not run.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact = CalculationInputArtifact(
        artifact_id=f"{manifest.run_id}:vasp-input",
        path=path.relative_to(root),
        sha256=_sha256(path),
        producer="genkai.compute.vasp",
        parent_ids=[structures.artifact_id],
        execution_state=ExecutionState.PREPARED,
        evidence_level=EvidenceLevel.HEURISTIC,
        validation_status=ValidationStatus.NEEDS_REVIEW,
        metadata={"scheduler_submitted": False},
    )
    manifest.register_artifact(artifact)
    manifest.append_stage(
        StageRecord(
            stage_id="04_dft_prepare",
            adapter="genkai.compute.vasp",
            execution_state=ExecutionState.PREPARED,
            input_artifact_ids=[structures.artifact_id],
            output_artifact_ids=[artifact.artifact_id],
        )
    )
    save_manifest(root, manifest)
    return artifact


def collect_vasp_results(
    input_artifact: CalculationInputArtifact,
    run_root: str | Path,
) -> CalculationResultArtifact:
    """Collect real OUTCAR labels; importing dpdata is deferred to this call."""

    try:
        import dpdata  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "VASP result collection requires optional dependency 'dpdata'; "
            "install it in the collection runtime"
        ) from exc
    root = Path(run_root)
    result_path = root / "stages" / "04_dft" / "results.extxyz"
    if not result_path.is_file():
        raise FileNotFoundError(
            f"no collected VASP result exists at {result_path}; run collection first"
        )
    manifest = load_manifest(root)
    artifact = CalculationResultArtifact(
        artifact_id=f"{manifest.run_id}:vasp-result",
        path=result_path.relative_to(root),
        sha256=_sha256(result_path),
        producer="genkai.compute.vasp",
        parent_ids=[input_artifact.artifact_id],
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.DFT_CALCULATED,
        validation_status=ValidationStatus.NEEDS_REVIEW,
        metadata={"label_source": "VASP OUTCAR"},
    )
    manifest.register_artifact(artifact)
    save_manifest(root, manifest)
    return artifact
