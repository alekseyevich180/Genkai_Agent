#!/usr/bin/env python3
"""Audit ASE-readable UMA fine-tuning data before LMDB conversion."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from ase.io import read


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate energy/force/stress labels and detect exact cross-split "
            "duplicates before UMA fine-tuning."
        )
    )
    parser.add_argument("--train-dir", required=True, type=Path)
    parser.add_argument("--val-dir", required=True, type=Path)
    parser.add_argument(
        "--test-dir",
        type=Path,
        help=(
            "Optional untouched test split to audit for labels and exact "
            "cross-split leakage. It is never passed to the UMA converter."
        ),
    )
    parser.add_argument(
        "--regression-tasks",
        required=True,
        choices=("e", "ef", "efs"),
        help="Labels to require: energy; energy+forces; or energy+forces+stress.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("uma_finetune_data_audit.json"),
    )
    parser.add_argument(
        "--min-distance",
        type=float,
        default=0.6,
        help="Warn when an interatomic distance is below this value in angstrom.",
    )
    parser.add_argument(
        "--reject-distance",
        type=float,
        default=0.4,
        help=(
            "Fail when an interatomic distance is below this value in angstrom. "
            "Set no higher than --min-distance."
        ),
    )
    return parser.parse_args()


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
) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]], dict[str, list[str]]]:
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
        except Exception as exc:  # ASE supports many readers with varied errors.
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
                errors.append(
                    {"location": location, "message": "positions contain NaN or Inf"}
                )
            if not finite_array(atoms.cell.array):
                errors.append({"location": location, "message": "cell contains NaN or Inf"})

            results = getattr(getattr(atoms, "calc", None), "results", {})
            energy = results.get("energy")
            if energy is None:
                errors.append({"location": location, "message": "missing energy label"})
            elif not finite_array(energy):
                errors.append(
                    {"location": location, "message": "energy contains NaN or Inf"}
                )

            if regression_tasks in {"ef", "efs"}:
                forces = results.get("forces")
                if forces is None:
                    errors.append({"location": location, "message": "missing forces label"})
                elif np.asarray(forces).shape != (len(atoms), 3):
                    errors.append(
                        {
                            "location": location,
                            "message": (
                                "forces shape is "
                                f"{np.asarray(forces).shape}, expected {(len(atoms), 3)}"
                            ),
                        }
                    )
                elif not finite_array(forces):
                    errors.append(
                        {"location": location, "message": "forces contain NaN or Inf"}
                    )

            if regression_tasks == "efs":
                stress = results.get("stress")
                if stress is None:
                    errors.append({"location": location, "message": "missing stress label"})
                elif np.asarray(stress).size not in {6, 9}:
                    errors.append(
                        {
                            "location": location,
                            "message": (
                                f"stress has {np.asarray(stress).size} values; expected 6 or 9"
                            ),
                        }
                    )
                elif not finite_array(stress):
                    errors.append(
                        {"location": location, "message": "stress contains NaN or Inf"}
                    )

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

            fingerprint = structure_fingerprint(atoms)
            fingerprints.setdefault(fingerprint, []).append(location)

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


def main() -> int:
    args = parse_args()
    if args.reject_distance <= 0 or args.min_distance <= 0:
        raise SystemExit("ERROR: distance thresholds must be positive")
    if args.reject_distance > args.min_distance:
        raise SystemExit(
            "ERROR: --reject-distance must be no higher than --min-distance"
        )

    split_results: dict[str, dict[str, Any]] = {}
    all_errors: list[dict[str, str]] = []
    all_warnings: list[dict[str, str]] = []
    split_fingerprints: dict[str, dict[str, list[str]]] = {}

    split_dirs = [("train", args.train_dir), ("val", args.val_dir)]
    if args.test_dir is not None:
        split_dirs.append(("test", args.test_dir))

    for split, directory in split_dirs:
        summary, errors, warnings, fingerprints = audit_split(
            split,
            directory.resolve(),
            args.regression_tasks,
            args.min_distance,
            args.reject_distance,
        )
        split_results[split] = summary
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        split_fingerprints[split] = fingerprints

    cross_split_duplicates = 0
    split_names = list(split_fingerprints)
    for left_index, left in enumerate(split_names):
        for right in split_names[left_index + 1 :]:
            shared = sorted(
                set(split_fingerprints[left]).intersection(split_fingerprints[right])
            )
            cross_split_duplicates += len(shared)
            for fingerprint in shared:
                all_errors.append(
                    {
                        "location": f"{left}/{right}",
                        "message": (
                            "exact structure appears in both splits: "
                            + ", ".join(split_fingerprints[left][fingerprint])
                            + " <> "
                            + ", ".join(split_fingerprints[right][fingerprint])
                        ),
                    }
                )

    report = {
        "status": "PASS" if not all_errors else "FAIL",
        "regression_tasks": args.regression_tasks,
        "minimum_distance_warning_angstrom": args.min_distance,
        "minimum_distance_rejection_angstrom": args.reject_distance,
        "splits": split_results,
        "cross_split_exact_duplicates": cross_split_duplicates,
        "errors": all_errors,
        "warnings": all_warnings,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("UMA fine-tuning data audit")
    for split in split_results:
        summary = split_results[split]
        print(
            f"  {split}: files={summary['files']} "
            f"structures={summary['structures']} atoms={summary['atoms']}"
        )
    print(f"  errors   : {len(all_errors)}")
    print(f"  warnings : {len(all_warnings)}")
    print(f"  report   : {args.report.resolve()}")
    print(f"AUDIT {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
