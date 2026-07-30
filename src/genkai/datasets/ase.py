"""ASE-readable dataset auditing shared by library and UMA compatibility CLI."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from ase.io import read

from genkai.contracts.artifacts import (
    CalculationResultArtifact,
    DatasetArtifact,
    EvidenceLevel,
    ExecutionState,
    ValidationStatus,
)
from genkai.contracts.run import StageRecord
from genkai.workflow.store import load_manifest, save_manifest

from .splits import find_cross_split_duplicates


def finite_array(value: Any) -> bool:
    try:
        return bool(np.isfinite(np.asarray(value, dtype=float)).all())
    except (TypeError, ValueError):
        return False


def structure_fingerprint(atoms: Any) -> str:
    digest = hashlib.sha256()
    for value in (
        np.asarray(atoms.numbers, dtype=np.int16),
        np.round(np.asarray(atoms.positions, dtype=np.float64), decimals=8),
        np.round(np.asarray(atoms.cell.array, dtype=np.float64), decimals=8),
        np.asarray(atoms.pbc, dtype=np.uint8),
    ):
        digest.update(np.ascontiguousarray(value).tobytes())
    return digest.hexdigest()


def minimum_distance(atoms: Any) -> float | None:
    if len(atoms) < 2:
        return None
    distances = atoms.get_all_distances(mic=bool(np.asarray(atoms.pbc).any()))
    np.fill_diagonal(distances, np.inf)
    value = float(np.min(distances))
    return value if math.isfinite(value) else None


def discover_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file())


def audit_split(
    split: str,
    directory: Path,
    regression_tasks: str,
    min_distance: float,
    reject_distance: float,
) -> tuple[
    dict[str, Any],
    list[dict[str, str]],
    list[dict[str, str]],
    dict[str, list[str]],
]:
    summary: dict[str, Any] = {
        "directory": str(directory),
        "files": 0,
        "structures": 0,
        "atoms": 0,
        "elements": Counter(),
    }
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    fingerprints: dict[str, list[str]] = {}
    if not directory.is_dir():
        errors.append({"location": str(directory), "message": "directory does not exist"})
        return summary, errors, warnings, fingerprints
    files = discover_files(directory)
    summary["files"] = len(files)
    if not files:
        errors.append({"location": str(directory), "message": "directory contains no files"})
        return summary, errors, warnings, fingerprints

    for path in files:
        try:
            frames = read(path, index=":")
        except Exception as exc:
            errors.append(
                {
                    "location": str(path),
                    "message": f"ASE read failed: {type(exc).__name__}: {exc}",
                }
            )
            continue
        if not isinstance(frames, list):
            frames = [frames]
        if not frames:
            errors.append({"location": str(path), "message": "file contains no structures"})
            continue

        for index, atoms in enumerate(frames):
            location = f"{path}:{index}"
            summary["structures"] += 1
            summary["atoms"] += len(atoms)
            summary["elements"].update(atoms.get_chemical_symbols())
            if len(atoms) == 0:
                errors.append({"location": location, "message": "structure has no atoms"})
                continue
            if not finite_array(atoms.positions):
                errors.append({"location": location, "message": "positions contain NaN or Inf"})
            if not finite_array(atoms.cell.array):
                errors.append({"location": location, "message": "cell contains NaN or Inf"})

            results = getattr(getattr(atoms, "calc", None), "results", {})
            energy = results.get("energy")
            if energy is None:
                errors.append({"location": location, "message": "missing energy label"})
            elif not finite_array(energy):
                errors.append({"location": location, "message": "energy contains NaN or Inf"})
            if regression_tasks in {"ef", "efs"}:
                forces = results.get("forces")
                if forces is None:
                    errors.append({"location": location, "message": "missing forces label"})
                elif np.asarray(forces).shape != (len(atoms), 3):
                    errors.append(
                        {
                            "location": location,
                            "message": (
                                f"forces shape is {np.asarray(forces).shape}, "
                                f"expected {(len(atoms), 3)}"
                            ),
                        }
                    )
                elif not finite_array(forces):
                    errors.append({"location": location, "message": "forces contain NaN or Inf"})
            if regression_tasks == "efs":
                stress = results.get("stress")
                if stress is None:
                    errors.append({"location": location, "message": "missing stress label"})
                elif np.asarray(stress).size not in {6, 9}:
                    errors.append(
                        {
                            "location": location,
                            "message": (
                                f"stress has {np.asarray(stress).size} values; "
                                "expected 6 or 9"
                            ),
                        }
                    )
                elif not finite_array(stress):
                    errors.append({"location": location, "message": "stress contains NaN or Inf"})

            try:
                distance = minimum_distance(atoms)
            except Exception as exc:
                warnings.append(
                    {
                        "location": location,
                        "message": (
                            "minimum-distance check failed: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                    }
                )
            else:
                if distance is not None and distance < reject_distance:
                    errors.append(
                        {
                            "location": location,
                            "message": (
                                f"minimum interatomic distance {distance:.6f} A is below "
                                f"hard rejection threshold {reject_distance:.6f} A"
                            ),
                        }
                    )
                elif distance is not None and distance < min_distance:
                    warnings.append(
                        {
                            "location": location,
                            "message": (
                                f"minimum interatomic distance {distance:.6f} A is below "
                                f"{min_distance:.6f} A"
                            ),
                        }
                    )
            fingerprints.setdefault(structure_fingerprint(atoms), []).append(location)

    duplicate_count = 0
    for locations in fingerprints.values():
        if len(locations) > 1:
            duplicate_count += len(locations) - 1
            warnings.append(
                {
                    "location": split,
                    "message": "exact duplicate structures: " + ", ".join(locations),
                }
            )
    summary["exact_duplicates_within_split"] = duplicate_count
    summary["elements"] = dict(sorted(summary["elements"].items()))
    return summary, errors, warnings, fingerprints


def audit_dataset_splits(
    split_dirs: dict[str, Path],
    *,
    regression_tasks: str,
    min_distance: float = 0.6,
    reject_distance: float = 0.4,
) -> dict[str, Any]:
    if regression_tasks not in {"e", "ef", "efs"}:
        raise ValueError("regression_tasks must be one of e, ef, or efs")
    if reject_distance <= 0 or min_distance <= 0:
        raise ValueError("distance thresholds must be positive")
    if reject_distance > min_distance:
        raise ValueError("reject_distance cannot exceed min_distance")

    split_results: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    split_fingerprints: dict[str, dict[str, list[str]]] = {}
    for split, directory in split_dirs.items():
        summary, split_errors, split_warnings, fingerprints = audit_split(
            split,
            Path(directory).resolve(),
            regression_tasks,
            min_distance,
            reject_distance,
        )
        split_results[split] = summary
        errors.extend(split_errors)
        warnings.extend(split_warnings)
        split_fingerprints[split] = fingerprints

    leakage = find_cross_split_duplicates(split_fingerprints)
    for duplicate in leakage:
        left, right = duplicate["splits"]
        errors.append(
            {
                "location": f"{left}/{right}",
                "message": (
                    "exact structure appears in both splits: "
                    + ", ".join(duplicate["left_locations"])
                    + " <> "
                    + ", ".join(duplicate["right_locations"])
                ),
            }
        )
    return {
        "status": "PASS" if not errors else "FAIL",
        "regression_tasks": regression_tasks,
        "minimum_distance_warning_angstrom": min_distance,
        "minimum_distance_rejection_angstrom": reject_distance,
        "splits": split_results,
        "cross_split_exact_duplicates": len(leakage),
        "errors": errors,
        "warnings": warnings,
    }


def build_dataset(
    results: CalculationResultArtifact,
    split_policy: dict[str, Any],
    run_root: str | Path,
) -> DatasetArtifact:
    """Audit on-disk splits and preserve the source label evidence level."""

    root = Path(run_root).resolve()
    manifest = load_manifest(root)
    source_path = (root / results.path).resolve()
    source_valid = (
        source_path.is_relative_to(root)
        and source_path.is_file()
        and hashlib.sha256(source_path.read_bytes()).hexdigest() == results.sha256
        and results.execution_state is ExecutionState.SUCCEEDED
    )
    raw_split_dirs = split_policy.get("split_directories")
    metadata = {
        key: value
        for key, value in split_policy.items()
        if key != "split_directories"
    }
    metadata.update(
        {
            "train_count": 0,
            "validation_count": 0,
            "test_count": 0,
            "cross_split_leakage": 0,
            "lmdb_readback": False,
            "audit_status": "NOT_RUN",
            "source_integrity_verified": source_valid,
        }
    )
    audit: dict[str, Any] | None = None
    is_mock = results.evidence_level is EvidenceLevel.MOCK
    if not is_mock and source_valid and isinstance(raw_split_dirs, dict):
        required_splits = {"train", "validation", "test"}
        if required_splits.issubset(raw_split_dirs):
            resolved_dirs = {
                name: Path(raw_split_dirs[name])
                for name in sorted(required_splits)
            }
            audit = audit_dataset_splits(
                resolved_dirs,
                regression_tasks=str(split_policy.get("regression_tasks", "ef")),
            )
            metadata["audit_status"] = audit["status"]
            metadata["cross_split_leakage"] = audit[
                "cross_split_exact_duplicates"
            ]
            for name in required_splits:
                key = "validation_count" if name == "validation" else f"{name}_count"
                metadata[key] = int(audit["splits"][name]["structures"])
            audited_files = [
                file
                for directory in resolved_dirs.values()
                for file in discover_files(directory)
            ]
            metadata["lmdb_readback"] = bool(audited_files) and all(
                file.suffix == ".lmdb" for file in audited_files
            )
    path = root / "stages" / "05_dataset" / "dataset.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "source_result": results.path.as_posix(),
        "evidence_level": results.evidence_level.value,
        "metadata": metadata,
        "audit": audit,
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    audit_passed = (
        not is_mock
        and source_valid
        and audit is not None
        and audit["status"] == "PASS"
        and results.validation_status is ValidationStatus.PASSED
    )
    artifact = DatasetArtifact(
        artifact_id=f"{manifest.run_id}:dataset",
        path=path.relative_to(root),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        producer="genkai.datasets.ase",
        parent_ids=[results.artifact_id],
        execution_state=(
            ExecutionState.SUCCEEDED if audit_passed else ExecutionState.PREPARED
        ),
        evidence_level=results.evidence_level,
        validation_status=(
            ValidationStatus.PASSED
            if audit_passed
            else ValidationStatus.NEEDS_REVIEW
        ),
        metadata=metadata,
    )
    manifest.register_artifact(artifact)
    manifest.append_stage(
        StageRecord(
            stage_id="05_dataset",
            adapter="genkai.datasets.ase",
            execution_state=ExecutionState.PREPARED,
            input_artifact_ids=[results.artifact_id],
            output_artifact_ids=[artifact.artifact_id],
        )
    )
    save_manifest(root, manifest)
    return artifact
