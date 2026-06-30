#!/usr/bin/env python3
"""Wrapper script for the paperread surface pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from paperread.surface.collect_experience import main as collect_experience_main
from paperread.surface.run_surface_pipeline import main as run_surface_pipeline_main


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run paperread surface extraction workflows."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pipeline = subparsers.add_parser(
        "surface-pipeline",
        help="Run the unified paperread surface pipeline on a PDF or JSON input.",
    )
    pipeline.add_argument("--input", required=True, help="Path to a PDF or JSON input file.")
    pipeline.add_argument(
        "--output-dir",
        default="paperread_output",
        help="Directory for pipeline outputs. Defaults to ./paperread_output",
    )
    pipeline.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep intermediate text/section/json files for debugging.",
    )
    pipeline.add_argument(
        "--save-raw",
        action="store_true",
        help="Preserve raw condition extraction CSV output.",
    )
    pipeline.add_argument(
        "--collect-experience",
        action="store_true",
        help="Collect material/modeling experience after extraction.",
    )

    collect = subparsers.add_parser(
        "collect-experience",
        help="Collect experience from existing paperread output files.",
    )
    collect.add_argument("--relations", help="Path to *_surface_relations.jsonl")
    collect.add_argument("--table", help="Path to *_table.csv")
    collect.add_argument(
        "--output-dir",
        default="paperread/surface/experience",
        help="Experience output directory. Defaults to paperread/surface/experience",
    )
    collect.add_argument(
        "--write-run-file",
        action="store_true",
        help="Write a per-run JSON aggregate file.",
    )
    collect.add_argument(
        "--write-markdown",
        action="store_true",
        help="Write a human-readable markdown report.",
    )

    init_classes = subparsers.add_parser(
        "init-material-classes",
        help="Initialize the default material-class experience store.",
    )
    init_classes.add_argument(
        "--output-dir",
        default="paperread/surface/experience",
        help="Directory where material class files should be initialized.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "surface-pipeline":
        cmd = [args.input, "--output-dir", args.output_dir]
        if args.keep_intermediate:
            cmd.append("--keep-intermediate")
        if args.save_raw:
            cmd.append("--save-raw")
        if args.collect_experience:
            cmd.append("--collect-experience")
        return int(run_surface_pipeline_main(cmd) or 0)

    if args.command == "collect-experience":
        cmd: list[str] = ["--output-dir", args.output_dir]
        if args.relations:
            cmd.extend(["--relations", args.relations])
        if args.table:
            cmd.extend(["--table", args.table])
        if args.write_run_file:
            cmd.append("--write-run-file")
        if args.write_markdown:
            cmd.append("--write-markdown")
        return int(collect_experience_main(cmd) or 0)

    if args.command == "init-material-classes":
        return int(
            collect_experience_main(
                ["--init-material-classes", "--output-dir", args.output_dir]
            )
            or 0
        )

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
