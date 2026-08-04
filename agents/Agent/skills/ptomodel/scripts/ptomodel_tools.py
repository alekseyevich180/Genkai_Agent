#!/usr/bin/env python3
"""Wrapper script for ptomodel JSON generation."""

from __future__ import annotations

import argparse
from pathlib import Path

from genkai.modeling.ptomodel import main as ptomodel_main


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ptomodel workflows on paperread surface outputs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build",
        help="Build ptomodel JSON from existing paperread output files.",
    )
    build.add_argument("--relations", required=True, help="Path to *_surface_relations.jsonl")
    build.add_argument("--table", default=None, help="Path to *_table.csv")
    build.add_argument("--summary", default=None, help="Path to *_summary.txt")
    build.add_argument("--time", default=None, help="Path to *_time.csv")
    build.add_argument(
        "--output-dir",
        default="paperread_output",
        help="Directory for ptomodel outputs. Defaults to ./paperread_output",
    )
    build.add_argument(
        "--stem",
        default=None,
        help="Optional output filename stem.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        cmd: list[str] = ["--relations", args.relations, "--output-dir", args.output_dir]
        if args.table:
            cmd.extend(["--table", args.table])
        if args.summary:
            cmd.extend(["--summary", args.summary])
        if args.time:
            cmd.extend(["--time", args.time])
        if args.stem:
            cmd.extend(["--stem", args.stem])
        return int(ptomodel_main(cmd) or 0)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
