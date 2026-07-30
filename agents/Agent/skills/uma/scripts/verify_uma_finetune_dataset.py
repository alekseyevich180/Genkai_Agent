#!/usr/bin/env python3
"""Verify converted UMA ASE-LMDB data and its generated Hydra configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from hydra import compose, initialize_config_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reject non-empty converter failure logs, read back train/val LMDB, "
            "and compose the generated UMA fine-tuning configuration."
        )
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--uma-task", required=True)
    parser.add_argument(
        "--regression-tasks", required=True, choices=("e", "ef", "efs")
    )
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--report", required=True, type=Path)
    return parser.parse_args()


def add_error(errors: list[dict[str, str]], location: Any, message: str) -> None:
    errors.append({"location": str(location), "message": message})


def main() -> int:
    args = parse_args()
    # Import after argument parsing so --help does not initialize fairchem caches.
    from fairchem.core.datasets import AseDBDataset

    output_dir = args.output_dir.resolve()
    errors: list[dict[str, str]] = []
    summaries: dict[str, dict[str, Any]] = {}

    nonempty_failed = sorted(
        path for path in output_dir.rglob("*.failed") if path.stat().st_size > 0
    )
    for path in nonempty_failed:
        add_error(errors, path, "converter failure log is non-empty")

    for split in ("train", "val"):
        split_dir = output_dir / split
        summary: dict[str, Any] = {"directory": str(split_dir), "structures": 0}
        summaries[split] = summary
        try:
            dataset = AseDBDataset({"src": str(split_dir)})
            summary["structures"] = len(dataset)
            if len(dataset) == 0:
                raise ValueError("dataset is empty")
            atoms = dataset.get_atoms(0)
            energy = atoms.get_potential_energy()
            if not np.isfinite(energy):
                raise ValueError("first-frame energy is not finite")
            summary["first_frame_atoms"] = len(atoms)
            summary["first_frame_energy_ev"] = float(energy)
            if args.regression_tasks in {"ef", "efs"}:
                forces = atoms.get_forces()
                if forces.shape != (len(atoms), 3) or not np.isfinite(forces).all():
                    raise ValueError("first-frame forces are missing, malformed, or non-finite")
                summary["first_frame_forces_shape"] = list(forces.shape)
            if args.regression_tasks == "efs":
                stress = atoms.get_stress()
                if stress.size not in {6, 9} or not np.isfinite(stress).all():
                    raise ValueError("first-frame stress is missing, malformed, or non-finite")
                summary["first_frame_stress_size"] = int(stress.size)
        except Exception as exc:
            add_error(
                errors,
                split_dir,
                f"ASE-LMDB readback failed: {type(exc).__name__}: {exc}",
            )

    config_path = output_dir / "uma_sm_finetune_template.yaml"
    config_summary: dict[str, Any] = {"path": str(config_path)}
    try:
        with initialize_config_dir(version_base=None, config_dir=str(output_dir)):
            cfg = compose(config_name="uma_sm_finetune_template")
        train_tasks = sorted(cfg.train_dataset.dataset_configs.keys())
        val_tasks = sorted(cfg.val_dataset.dataset_configs.keys())
        config_summary.update(
            {
                "base_model_name": str(cfg.base_model_name),
                "train_tasks": train_tasks,
                "val_tasks": val_tasks,
                "train_src": str(cfg.data.train_dataset.splits.train.src),
                "val_src": str(cfg.data.val_dataset.splits.val.src),
                "epochs": cfg.epochs,
                "steps": cfg.steps,
            }
        )
        if str(cfg.base_model_name) != args.base_model:
            raise ValueError(
                f"base model {cfg.base_model_name!s} does not match {args.base_model}"
            )
        if train_tasks != [args.uma_task] or val_tasks != [args.uma_task]:
            raise ValueError(
                f"dataset task mismatch: train={train_tasks}, val={val_tasks}, "
                f"expected={[args.uma_task]}"
            )
        if Path(str(cfg.data.train_dataset.splits.train.src)).resolve() != (
            output_dir / "train"
        ):
            raise ValueError("generated train source does not point to output/train")
        if Path(str(cfg.data.val_dataset.splits.val.src)).resolve() != (
            output_dir / "val"
        ):
            raise ValueError("generated val source does not point to output/val")
        if (cfg.epochs is None) == (cfg.steps is None):
            raise ValueError("exactly one of epochs or steps must be non-null")
    except Exception as exc:
        add_error(
            errors,
            config_path,
            f"Hydra configuration check failed: {type(exc).__name__}: {exc}",
        )

    report = {
        "status": "PASS" if not errors else "FAIL",
        "output_dir": str(output_dir),
        "uma_task": args.uma_task,
        "regression_tasks": args.regression_tasks,
        "base_model": args.base_model,
        "nonempty_failed_logs": [str(path) for path in nonempty_failed],
        "splits": summaries,
        "config": config_summary,
        "errors": errors,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("UMA fine-tuning converted-dataset verification")
    for split, summary in summaries.items():
        print(f"  {split}: structures={summary['structures']}")
    print(f"  nonempty *.failed : {len(nonempty_failed)}")
    print(f"  errors            : {len(errors)}")
    print(f"  report            : {args.report.resolve()}")
    print(f"VERIFY {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
