#!/usr/bin/env python3
"""Audit ASE-readable UMA fine-tuning data before LMDB conversion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from genkai.datasets.ase import audit_dataset_splits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate energy/force/stress labels and detect exact cross-split "
            "duplicates before UMA fine-tuning."
        )
    )
    parser.add_argument("--train-dir", required=True, type=Path)
    parser.add_argument("--val-dir", required=True, type=Path)
    parser.add_argument("--test-dir", type=Path)
    parser.add_argument(
        "--regression-tasks",
        required=True,
        choices=("e", "ef", "efs"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("uma_finetune_data_audit.json"),
    )
    parser.add_argument("--min-distance", type=float, default=0.6)
    parser.add_argument("--reject-distance", type=float, default=0.4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    split_dirs = {"train": args.train_dir, "val": args.val_dir}
    if args.test_dir is not None:
        split_dirs["test"] = args.test_dir
    try:
        report = audit_dataset_splits(
            split_dirs,
            regression_tasks=args.regression_tasks,
            min_distance=args.min_distance,
            reject_distance=args.reject_distance,
        )
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("UMA fine-tuning data audit")
    for split, summary in report["splits"].items():
        print(
            f"  {split}: files={summary['files']} "
            f"structures={summary['structures']} atoms={summary['atoms']}"
        )
    print(f"  errors   : {len(report['errors'])}")
    print(f"  warnings : {len(report['warnings'])}")
    print(f"  report   : {args.report.resolve()}")
    print(f"AUDIT {report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
