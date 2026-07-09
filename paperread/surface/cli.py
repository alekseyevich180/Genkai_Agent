from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .catalog import render_surface_tool_catalog
    from .collect_experience import collect_experience
    from .ingest_pdf import ingest_pdf
    from .parameter_registry import build_surface_parameter_registry
    from .ptomodel import generate_ptomodel_output
    from .run_surface_pipeline import run_pipeline, run_pipeline_from_pdf
    from .standardize_surface_time import standardize_time
    from .summarize_surface_outputs import write_summary
except ImportError:  # pragma: no cover - direct script execution fallback
    from catalog import render_surface_tool_catalog
    from collect_experience import collect_experience
    from ingest_pdf import ingest_pdf
    from parameter_registry import build_surface_parameter_registry
    from ptomodel import generate_ptomodel_output
    from run_surface_pipeline import run_pipeline, run_pipeline_from_pdf
    from standardize_surface_time import standardize_time
    from summarize_surface_outputs import write_summary


def _add_common_pipeline_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", default="paperread/surface/output", help="Directory for generated outputs.")
    parser.add_argument("--model", default=None, help="Optional model override.")
    parser.add_argument("--save-raw", action="store_true", help="Save raw extraction responses where supported.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified command line entrypoint for surface paperread tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_tools = subparsers.add_parser("list-tools", help="Show grouped surface tooling by category.")
    list_tools.add_argument("--category", default=None, help="Optional category filter.")

    ingest = subparsers.add_parser("ingest", help="Run PDF ingestion only.")
    ingest.add_argument("input_pdf", help="Input PDF file.")
    ingest.add_argument("--output-dir", required=True, help="Output directory for ingestion artifacts.")

    run = subparsers.add_parser("run", help="Run the full surface pipeline.")
    run.add_argument("input_source", help="JSON or PDF input source.")
    run.add_argument("--input-format", choices=["auto", "json", "pdf"], default="auto")
    run.add_argument("--skip-conditions", action="store_true")
    run.add_argument("--skip-relations", action="store_true")
    run.add_argument("--keep-intermediate", action="store_true")
    run.add_argument("--collect-experience", action="store_true")
    _add_common_pipeline_args(run)

    conditions = subparsers.add_parser("conditions", help="Extract conditions table from JSON input.")
    conditions.add_argument("input_json", help="JSON input for condition extraction.")
    conditions.add_argument("--prefix", required=True, help="Output prefix.")
    _add_common_pipeline_args(conditions)

    relations = subparsers.add_parser("relations", help="Extract relations JSONL from JSON input.")
    relations.add_argument("input_json", help="JSON input for relation extraction.")
    relations.add_argument("--output", required=True, help="Output JSONL path.")
    _add_common_pipeline_args(relations)

    time_parser = subparsers.add_parser("time", help="Standardize a time table.")
    time_parser.add_argument("input_csv", help="Input CSV with a Time column.")
    time_parser.add_argument("output_csv", help="Output standardized CSV.")
    _add_common_pipeline_args(time_parser)

    summary = subparsers.add_parser("summary", help="Write a human-readable summary.")
    summary.add_argument("table_csv", help="Conditions table CSV.")
    summary.add_argument("relations_jsonl", help="Relations JSONL.")
    summary.add_argument("output_txt", help="Output summary text file.")

    ptomodel = subparsers.add_parser("ptomodel", help="Generate ptomodel JSON from extracted surface outputs.")
    ptomodel.add_argument("relations_jsonl", help="Relations JSONL.")
    ptomodel.add_argument("--table-csv", default=None)
    ptomodel.add_argument("--summary-txt", default=None)
    ptomodel.add_argument("--time-csv", default=None)
    ptomodel.add_argument("--output-dir", required=True)
    ptomodel.add_argument("--stem", default="surface")

    experience = subparsers.add_parser("experience", help="Collect surface experience and unknown terms.")
    experience.add_argument("--relations", default=None)
    experience.add_argument("--table", default=None)
    experience.add_argument("--output-dir", default="agents/Agent/skills/paperread/experience")
    experience.add_argument("--stem", default="surface_experience")

    registry = subparsers.add_parser("registry", help="Build or refresh the surface parameter registry.")
    registry.add_argument("--material-class-dir", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list-tools":
        print(render_surface_tool_catalog(args.category))
        return 0

    if args.command == "ingest":
        result = ingest_pdf(args.input_pdf, args.output_dir)
        for path in result.values():
            print(path)
        return 0

    if args.command == "run":
        source_path = Path(args.input_source)
        input_format = args.input_format
        if input_format == "auto":
            input_format = "pdf" if source_path.suffix.lower() == ".pdf" else "json"
        if input_format == "pdf":
            outputs = run_pipeline_from_pdf(
                args.input_source,
                args.output_dir,
                model=args.model,
                skip_conditions=args.skip_conditions,
                skip_relations=args.skip_relations,
                keep_intermediate=args.keep_intermediate,
                save_raw=args.save_raw,
                collect_experience_output=args.collect_experience,
            )
        else:
            outputs = run_pipeline(
                args.input_source,
                args.output_dir,
                model=args.model,
                skip_conditions=args.skip_conditions,
                skip_relations=args.skip_relations,
                save_raw=args.save_raw,
                collect_experience_output=args.collect_experience,
            )
        for path in outputs.values():
            print(path)
        return 0

    if args.command == "conditions":
        try:
            from .extract_surface_conditions import extract_conditions
        except ImportError:  # pragma: no cover - direct script execution fallback
            from extract_surface_conditions import extract_conditions

        raw_path, table_path = extract_conditions(args.input_json, args.prefix, model=args.model, save_raw=args.save_raw)
        if raw_path:
            print(raw_path)
        print(table_path)
        return 0

    if args.command == "relations":
        try:
            from .extract_surface_relations import extract_relations
        except ImportError:  # pragma: no cover - direct script execution fallback
            from extract_surface_relations import extract_relations

        print(extract_relations(args.input_json, args.output, model=args.model))
        return 0

    if args.command == "time":
        print(standardize_time(args.input_csv, args.output_csv, time_column="Time", model=args.model))
        return 0

    if args.command == "summary":
        print(write_summary(args.table_csv, args.relations_jsonl, args.output_txt))
        return 0

    if args.command == "ptomodel":
        print(
            generate_ptomodel_output(
                relations_jsonl=args.relations_jsonl,
                output_dir=args.output_dir,
                stem=args.stem,
                table_csv=args.table_csv,
                summary_txt=args.summary_txt,
                time_csv=args.time_csv,
            )["ptomodel_json"]
        )
        return 0

    if args.command == "experience":
        result = collect_experience(args.relations, args.table, args.output_dir, stem=args.stem)
        if result.get("json_path"):
            print(result["json_path"])
        if result.get("markdown_path"):
            print(result["markdown_path"])
        return 0

    if args.command == "registry":
        material_class_dir = Path(args.material_class_dir) if args.material_class_dir else None
        registry = build_surface_parameter_registry(material_class_dir=material_class_dir)
        print(registry)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
