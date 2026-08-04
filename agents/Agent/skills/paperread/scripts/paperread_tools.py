#!/usr/bin/env python3
"""Wrapper script for the paperread surface pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from genkai.literature.surface.experience.collect_experience import (
    main as collect_experience_main,
)
from genkai.literature.surface.experience.parameter_registry import (
    DEFAULT_MATERIAL_CLASS_DIR,
    DEFAULT_REGISTRY_MARKDOWN_PATH,
    DEFAULT_REGISTRY_PATH,
    build_surface_parameter_registry,
)
from genkai.literature.surface.pipeline.runner import main as run_surface_pipeline_main
from genkai.literature.surface.experience.unknown_terms import (
    reclassify_material_class_store,
    write_unknown_term_statistics,
)

from genkai.literature.surface.experience.export_unknown_terms import (
    cmd_add_term as export_add_term,
    cmd_export as export_unknown_terms,
)


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
        default="src/genkai/literature/surface/experience",
        help=(
            "Experience output directory. Defaults to "
            "src/genkai/literature/surface/experience"
        ),
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
        default="src/genkai/literature/surface/experience",
        help="Directory where material class files should be initialized.",
    )

    registry = subparsers.add_parser(
        "build-parameter-registry",
        help="Build a reusable parameter registry from paperread material-class experience files.",
    )
    registry.add_argument(
        "--material-class-dir",
        default=str(DEFAULT_MATERIAL_CLASS_DIR),
        help="Directory containing material_classes/*.json files.",
    )
    registry.add_argument(
        "--output-json",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Output JSON registry path.",
    )
    registry.add_argument(
        "--output-md",
        default=str(DEFAULT_REGISTRY_MARKDOWN_PATH),
        help="Output Markdown registry path.",
    )

    export_terms = subparsers.add_parser(
        "export-unknown-terms",
        help="Export unfamiliar or unmapped terms from paperread outputs.",
    )
    export_terms.add_argument("--relations", required=True, help="Path to *_surface_relations.jsonl")
    export_terms.add_argument("--table", default=None, help="Optional path to *_table.csv")
    export_terms.add_argument(
        "--output-dir",
        default="agents/Agent/skills/paperread/experience",
        help="Experience output directory. Defaults to agents/Agent/skills/paperread/experience",
    )
    export_terms.add_argument("--dry-run", action="store_true", help="Print records without writing files.")

    add_term = subparsers.add_parser(
        "add-term",
        help="Add one manually observed unfamiliar surface-paper term.",
    )
    add_term.add_argument("--term", required=True, help="Unfamiliar term.")
    add_term.add_argument("--category", default="manual", help="Term category.")
    add_term.add_argument("--context", default="", help="Short source/context note.")
    add_term.add_argument("--source", default="manual", help="Source path, DOI, or manual.")
    add_term.add_argument("--suggested-action", default="", help="Suggested follow-up action.")
    add_term.add_argument(
        "--output-dir",
        default="agents/Agent/skills/paperread/experience",
        help="Experience output directory. Defaults to agents/Agent/skills/paperread/experience",
    )
    add_term.add_argument("--dry-run", action="store_true", help="Print record without writing files.")

    reclassify = subparsers.add_parser(
        "reclassify-material-classes",
        help="Reapply ontology known-term rules to material_class experience files.",
    )
    reclassify.add_argument(
        "--material-class-dir",
        default=str(DEFAULT_MATERIAL_CLASS_DIR),
        help="Directory containing material_classes/*.json files.",
    )

    unknown_stats = subparsers.add_parser(
        "summarize-unknown-terms",
        help="Write unknown-term statistics from material_class experience files.",
    )
    unknown_stats.add_argument(
        "--material-class-dir",
        default=str(DEFAULT_MATERIAL_CLASS_DIR),
        help="Directory containing material_classes/*.json files.",
    )
    unknown_stats.add_argument(
        "--output-dir",
        default="agents/Agent/skills/paperread/experience",
        help="Output directory for unknown_term_statistics_*.{json,md}.",
    )
    unknown_stats.add_argument(
        "--date-slug",
        default=None,
        help="Date slug for output filenames, for example 2026_07_08.",
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

    if args.command == "build-parameter-registry":
        build_surface_parameter_registry(
            material_class_dir=Path(args.material_class_dir),
            output_json_path=Path(args.output_json),
            output_markdown_path=Path(args.output_md),
        )
        print(args.output_json)
        print(args.output_md)
        return 0

    if args.command == "export-unknown-terms":
        result = export_unknown_terms(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "add-term":
        result = export_add_term(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "reclassify-material-classes":
        result = reclassify_material_class_store(Path(args.material_class_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "summarize-unknown-terms":
        result = write_unknown_term_statistics(
            material_class_dir=Path(args.material_class_dir),
            output_dir=Path(args.output_dir),
            date_slug=args.date_slug,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
