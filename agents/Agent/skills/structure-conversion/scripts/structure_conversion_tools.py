#!/usr/bin/env python3
"""CLI helpers for structure format conversion.

All commands print a JSON object to stdout and exit 0 on success, 1 on error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ase.io import read, write


def convert_structure(
    input_file: str,
    output_path: str,
    output_format: Optional[str] = None,
) -> Dict[str, Any]:
    input_path = Path(input_file).expanduser().resolve()
    target_path = Path(output_path).expanduser().resolve()

    if not input_path.exists():
        raise ValueError(f"Input file does not exist: {input_path}")

    input_suffix = input_path.suffix.lower()
    if input_suffix not in {".extxyz", ".xyz", ".cif"}:
        raise ValueError(f"Unsupported input format: {input_suffix}")

    normalized_output_format = (output_format or "").strip().lower()
    if not normalized_output_format:
        suffix = target_path.suffix.lower()
        if suffix == ".cif":
            normalized_output_format = "cif"
        elif suffix in {".extxyz", ".xyz"}:
            normalized_output_format = "extxyz"
        else:
            raise ValueError(
                "Could not infer output format from output_path. "
                "Specify --output-format as 'cif' or 'extxyz'."
            )

    if normalized_output_format not in {"cif", "extxyz"}:
        raise ValueError(f"Unsupported output format: {normalized_output_format}")

    if input_suffix == ".cif" and normalized_output_format == "extxyz":
        atoms = read(str(input_path))
        target_path.parent.mkdir(parents=True, exist_ok=True)
        write(str(target_path), atoms, format="extxyz")
        resolved = str(target_path.resolve())
        return {
            "status": "success",
            "message": "Structure conversion completed successfully.",
            "output_mode": "single_file",
            "output_format": "extxyz",
            "frame_count": 1,
            "output_path": resolved,
            "output_paths": [resolved],
        }

    if input_suffix in {".extxyz", ".xyz"} and normalized_output_format == "cif":
        atoms_list = read(str(input_path), ":")
        if not isinstance(atoms_list, list):
            atoms_list = [atoms_list]
        if not atoms_list:
            raise ValueError(f"No structures found in input file: {input_path}")

        if len(atoms_list) == 1:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            write(str(target_path), atoms_list[0], format="cif")
            resolved = str(target_path.resolve())
            return {
                "status": "success",
                "message": "Structure conversion completed successfully.",
                "output_mode": "single_file",
                "output_format": "cif",
                "frame_count": 1,
                "output_path": resolved,
                "output_paths": [resolved],
            }

        output_dir = (
            target_path
            if target_path.suffix.lower() != ".cif"
            else target_path.with_suffix("")
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        output_paths: List[str] = []
        for idx, atoms in enumerate(atoms_list, start=1):
            cif_path = output_dir / f"frame_{idx:06d}.cif"
            write(str(cif_path), atoms, format="cif")
            output_paths.append(str(cif_path.resolve()))

        return {
            "status": "success",
            "message": "Structure conversion completed successfully.",
            "output_mode": "directory",
            "output_format": "cif",
            "frame_count": len(output_paths),
            "output_path": str(output_dir.resolve()),
            "output_paths": output_paths,
        }

    if input_suffix in {".extxyz", ".xyz"} and normalized_output_format == "extxyz":
        atoms_list = read(str(input_path), ":")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        write(str(target_path), atoms_list, format="extxyz")
        frame_count = len(atoms_list) if isinstance(atoms_list, list) else 1
        resolved = str(target_path.resolve())
        return {
            "status": "success",
            "message": "Structure conversion completed successfully.",
            "output_mode": "single_file",
            "output_format": "extxyz",
            "frame_count": frame_count,
            "output_path": resolved,
            "output_paths": [resolved],
        }

    raise ValueError(
        f"Unsupported conversion: input={input_suffix}, output_format={normalized_output_format}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Structure conversion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert_parser = subparsers.add_parser(
        "convert", help="Convert between extxyz and CIF formats."
    )
    convert_parser.add_argument("input_file", help="Input structure path")
    convert_parser.add_argument("output_path", help="Output file path or directory")
    convert_parser.add_argument(
        "--output-format",
        choices=["cif", "extxyz"],
        default=None,
        help="Explicit output format. If omitted, infer from output_path.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "convert":
            result = convert_structure(
                input_file=args.input_file,
                output_path=args.output_path,
                output_format=args.output_format,
            )
        else:
            raise ValueError(f"Unsupported command: {args.command}")

        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": str(exc),
                    "output_mode": None,
                    "output_format": getattr(args, "output_format", None),
                    "frame_count": 0,
                    "output_path": None,
                    "output_paths": [],
                },
                ensure_ascii=True,
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
