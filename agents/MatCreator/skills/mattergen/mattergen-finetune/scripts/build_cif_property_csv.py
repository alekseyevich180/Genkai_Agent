#!/usr/bin/env python3
"""Build a MatterGen-style CSV with inline CIF text from numbered CIF files.

Input expectations:
- a directory containing CIF files such as ``0.cif`` and ``11.cif``
- a CSV file with at least three columns:
  1. structure identifier
  2. placeholder column, often ``0``
  3. target property value

Output format:
- ``material_id,<property_name>,cif``

Optionally writes train/val/test CSV splits.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replace a placeholder CSV column with CIF contents."
    )
    parser.add_argument(
        "data_dir",
        help="Directory containing numbered CIF files such as 0.cif and 11.cif.",
    )
    parser.add_argument(
        "input_csv",
        help="Input CSV path with id, placeholder, property columns.",
    )
    parser.add_argument(
        "property_name",
        help="Header name for the property column, such as dft_band_gap.",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Optional output CSV path. Default: <data_dir>/mattergen_property.csv.",
    )
    parser.add_argument(
        "--split-dir",
        default=None,
        help="Optional directory for train.csv and val.csv. Default: <data_dir>/<output_stem>_csvs.",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.1,
        help="Validation split ratio in (0, 1). Default: 0.1.",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.1,
        help="Test split ratio in (0, 1). Default: 0.1.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for train/val splitting. Default: 42.",
    )
    return parser


def _read_cif_text(data_dir: Path, material_id: str) -> str:
    cif_path = data_dir / f"{material_id}.cif"
    if not cif_path.exists():
        raise FileNotFoundError(f"CIF file not found for id '{material_id}': {cif_path}")
    return cif_path.read_text(encoding="utf-8")


def _write_rows(output_csv: Path, property_name: str, rows: list[list[str]]) -> None:
    with output_csv.open("w", encoding="utf-8", newline="") as f_out:
        writer = csv.writer(f_out, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["material_id", property_name, "cif"])
        writer.writerows(rows)


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    data_dir = Path(args.data_dir).expanduser().resolve()
    input_csv = Path(args.input_csv).expanduser().resolve()
    if not data_dir.is_dir():
        raise NotADirectoryError(f"data_dir does not exist: {data_dir}")
    if not input_csv.exists():
        raise FileNotFoundError(f"input_csv does not exist: {input_csv}")
    if args.output_csv:
        output_csv = Path(args.output_csv).expanduser().resolve()
    else:
        output_csv = data_dir / "mattergen_property.csv"

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if args.split_dir:
        split_dir = Path(args.split_dir).expanduser().resolve()
    else:
        split_dir = data_dir / f"{output_csv.stem}_csvs"
    split_dir.mkdir(parents=True, exist_ok=True)
    train_csv = split_dir / "train.csv"
    val_csv = split_dir / "val.csv"
    test_csv = split_dir / "test.csv"

    if not 0 < args.val_ratio < 1:
        raise ValueError("--val-ratio must be in (0, 1).")
    if not 0 < args.test_ratio < 1:
        raise ValueError("--test-ratio must be in (0, 1).")
    if args.val_ratio + args.test_ratio >= 1:
        raise ValueError("--val-ratio + --test-ratio must be < 1.")

    rows: list[list[str]] = []
    with input_csv.open("r", encoding="utf-8", newline="") as f_in:
        reader = csv.reader(f_in)

        for line_no, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue

            if len(row) < 3:
                raise ValueError(
                    f"Row {line_no} has only {len(row)} columns, but at least 3 are required."
                )

            material_id = row[0].strip()
            property_value = row[2].strip()
            cif_text = _read_cif_text(data_dir, material_id)
            rows.append([material_id, property_value, cif_text])

    rng = random.Random(args.seed)
    shuffled_rows = rows[:]
    rng.shuffle(shuffled_rows)

    if len(shuffled_rows) < 3:
        raise ValueError(
            "At least 3 rows are required to create non-empty train/val/test splits."
        )

    val_count = int(len(shuffled_rows) * args.val_ratio)
    test_count = int(len(shuffled_rows) * args.test_ratio)
    if val_count == 0 or test_count == 0:
        raise ValueError(
            "Dataset is too small for the requested split ratios: both validation and test "
            "splits must contain at least 1 row."
        )
    val_rows = shuffled_rows[:val_count]
    test_rows = shuffled_rows[val_count:val_count + test_count]
    train_rows = shuffled_rows[val_count + test_count:]

    if not train_rows:
        raise ValueError(
            "Dataset is too small for the requested split ratios: training split must contain at least 1 row."
        )

    _write_rows(output_csv, args.property_name, rows)
    _write_rows(train_csv, args.property_name, train_rows)
    _write_rows(val_csv, args.property_name, val_rows)
    _write_rows(test_csv, args.property_name, test_rows)

    print(
        json.dumps(
            {
                "status": "success",
                "data_dir": str(data_dir),
                "input_csv": str(input_csv),
                "output_csv": str(output_csv),
                "split_dir": str(split_dir),
                "train_csv": str(train_csv),
                "val_csv": str(val_csv),
                "test_csv": str(test_csv),
                "property_name": args.property_name,
                "rows_written": len(rows),
                "train_rows": len(train_rows),
                "val_rows": len(val_rows),
                "test_rows": len(test_rows),
                "val_ratio": args.val_ratio,
                "test_ratio": args.test_ratio,
                "seed": args.seed,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
