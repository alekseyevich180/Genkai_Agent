"""VASP preparation and collection adapters."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import write

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
        metadata={"scheduler_submitted": False, "calculation_dirs": []},
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
    """Parse converged OUTCAR files and register their finite labels."""

    root = Path(run_root).resolve()
    raw_directories = input_artifact.metadata.get("calculation_dirs")
    if not isinstance(raw_directories, list) or not raw_directories:
        raise ValueError("input artifact metadata requires nonempty calculation_dirs")
    outcars: list[Path] = []
    for raw in raw_directories:
        directory = (root / str(raw)).resolve()
        if not directory.is_relative_to(root):
            raise ValueError(f"calculation directory escapes run root: {raw}")
        outcar = directory / "OUTCAR"
        if not outcar.is_file():
            raise FileNotFoundError(f"VASP OUTCAR does not exist: {outcar}")
        text = outcar.read_text(encoding="utf-8", errors="ignore")
        convergence_markers = (
            "aborting loop because EDIFF is reached",
            "reached required accuracy",
        )
        if not any(marker in text for marker in convergence_markers):
            raise ValueError(f"VASP OUTCAR has no convergence marker: {outcar}")
        outcars.append(outcar)
    try:
        import dpdata
    except ImportError as exc:
        raise RuntimeError(
            "VASP result collection requires optional dependency 'dpdata'; "
            "install it in the collection runtime"
        ) from exc
    frames: list[Atoms] = []
    for outcar in outcars:
        system = dpdata.LabeledSystem(str(outcar), fmt="vasp/outcar")
        data = system.data
        coordinates = np.asarray(data.get("coords"), dtype=float)
        cells = np.asarray(data.get("cells"), dtype=float)
        energies = np.asarray(data.get("energies"), dtype=float)
        forces = np.asarray(data.get("forces"), dtype=float)
        raw_atom_names = data.get("atom_names")
        atom_names = list(
            raw_atom_names
            if raw_atom_names is not None
            else system.get_atom_names()
        )
        atom_types = np.asarray(
            data.get("atom_types")
            if data.get("atom_types") is not None
            else system.get_atom_types(),
            dtype=int,
        )
        if (
            coordinates.ndim != 3
            or cells.shape != (len(coordinates), 3, 3)
            or energies.shape != (len(coordinates),)
            or forces.shape
            != (len(coordinates), len(atom_types), 3)
            or len(coordinates) == 0
        ):
            raise ValueError(f"dpdata returned incomplete labels for {outcar}")
        if not all(
            np.isfinite(values).all()
            for values in (coordinates, cells, energies, forces)
        ):
            raise ValueError(f"dpdata returned NaN or Inf labels for {outcar}")
        symbols = [atom_names[index] for index in atom_types]
        for index in range(len(coordinates)):
            atoms = Atoms(
                symbols=symbols,
                positions=coordinates[index],
                cell=cells[index],
                pbc=True,
            )
            atoms.calc = SinglePointCalculator(
                atoms,
                energy=float(energies[index]),
                forces=forces[index],
            )
            frames.append(atoms)
    if not frames:
        raise ValueError("no converged VASP frames were collected")
    result_path = root / "stages" / "04_dft" / "results.extxyz"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = result_path.with_suffix(".extxyz.tmp")
    write(temporary, frames, format="extxyz")
    temporary.replace(result_path)
    manifest = load_manifest(root)
    artifact = CalculationResultArtifact(
        artifact_id=f"{manifest.run_id}:vasp-result",
        path=result_path.relative_to(root),
        sha256=_sha256(result_path),
        producer="genkai.compute.vasp",
        parent_ids=[input_artifact.artifact_id],
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.DFT_CALCULATED,
        validation_status=ValidationStatus.PASSED,
        metadata={
            "label_source": "VASP OUTCAR",
            "calculation_count": len(outcars),
            "structure_count": len(frames),
            "convergence_checked": True,
            "finite_labels_checked": True,
        },
    )
    manifest.register_artifact(artifact)
    manifest.append_stage(
        StageRecord(
            stage_id="04_dft_collect",
            adapter="genkai.compute.vasp",
            execution_state=ExecutionState.SUCCEEDED,
            input_artifact_ids=[input_artifact.artifact_id],
            output_artifact_ids=[artifact.artifact_id],
        )
    )
    save_manifest(root, manifest)
    return artifact
