from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .extract_surface_conditions import extract_conditions
    from .extract_surface_relations import extract_relations
    from .ingest_pdf import ingest_pdf
    from .standardize_surface_time import standardize_time
except ImportError:  # pragma: no cover - direct script execution
    from extract_surface_conditions import extract_conditions
    from extract_surface_relations import extract_relations
    from ingest_pdf import ingest_pdf
    from standardize_surface_time import standardize_time


def run_pipeline(
    input_json: str,
    output_dir: str,
    model: str | None = None,
    skip_conditions: bool = False,
    skip_relations: bool = False,
    conditions_input_json: str | None = None,
    relations_input_json: str | None = None,
) -> dict[str, str]:
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    stem = Path(input_json).stem
    results: dict[str, str] = {}
    conditions_source = conditions_input_json or input_json
    relations_source = relations_input_json or input_json

    if not skip_conditions:
        prefix = str(outdir / stem)
        raw_path, table_path = extract_conditions(conditions_source, prefix, model=model)
        time_path = str(outdir / f"{stem}_time.csv")
        standardize_time(table_path, time_path, time_column="Time", model=model)
        results["raw_csv"] = raw_path
        results["conditions_csv"] = table_path
        results["time_csv"] = time_path

    if not skip_relations:
        relations_path = str(outdir / f"{stem}_surface_relations.jsonl")
        extract_relations(relations_source, relations_path, model=model)
        results["relations_jsonl"] = relations_path

    return results


def run_pipeline_from_pdf(
    input_pdf: str,
    output_dir: str,
    model: str | None = None,
    skip_conditions: bool = False,
    skip_relations: bool = False,
) -> dict[str, str]:
    ingestion_outputs = ingest_pdf(input_pdf, output_dir)
    pipeline_outputs = run_pipeline(
        ingestion_outputs["conditions_input_json"],
        output_dir,
        model=model,
        skip_conditions=skip_conditions,
        skip_relations=skip_relations,
        conditions_input_json=ingestion_outputs["conditions_input_json"],
        relations_input_json=ingestion_outputs["relations_input_json"],
    )
    return {**ingestion_outputs, **pipeline_outputs}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the unified surface-material reaction extraction pipeline."
    )
    parser.add_argument("input_source", help="JSON or PDF input file.")
    parser.add_argument(
        "--output-dir",
        default="paperread/surface/output",
        help="Directory for generated outputs.",
    )
    parser.add_argument("--model", default=None, help="Optional model override.")
    parser.add_argument(
        "--skip-conditions",
        action="store_true",
        help="Skip conditions and time extraction.",
    )
    parser.add_argument(
        "--skip-relations",
        action="store_true",
        help="Skip relation extraction.",
    )
    parser.add_argument(
        "--input-format",
        choices=["auto", "json", "pdf"],
        default="auto",
        help="Interpret input source as JSON or PDF. Default: auto.",
    )
    args = parser.parse_args()

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
        )
    else:
        outputs = run_pipeline(
            args.input_source,
            args.output_dir,
            model=args.model,
            skip_conditions=args.skip_conditions,
            skip_relations=args.skip_relations,
        )
    for _, path in outputs.items():
        print(path)


if __name__ == "__main__":
    main()
