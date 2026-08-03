from __future__ import annotations

import argparse
from pathlib import Path

from genkai.literature.surface.experience.collect_experience import collect_experience
from genkai.literature.surface.extraction.extract_surface_conditions import (
    extract_conditions,
)
from genkai.literature.surface.extraction.extract_surface_relations import (
    extract_relations,
)
from genkai.literature.surface.extraction.ingest_pdf import (
    ingest_pdf,
    ingest_pdf_payloads,
    write_temp_surface_inputs,
)
from genkai.literature.surface.extraction.standardize_surface_time import (
    standardize_time,
)
from genkai.literature.surface.extraction.summarize_surface_outputs import (
    write_summary,
)
from paperread.surface.modeling.job_bundle import write_compact_job_bundle
from paperread.surface.modeling.ptomodel import generate_ptomodel_output


def run_pipeline(
    input_json: str,
    output_dir: str,
    model: str | None = None,
    skip_conditions: bool = False,
    skip_relations: bool = False,
    conditions_input_json: str | None = None,
    relations_input_json: str | None = None,
    save_raw: bool = False,
    collect_experience_output: bool = False,
) -> dict[str, str]:
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    stem = Path(input_json).stem
    results: dict[str, str] = {}
    conditions_source = conditions_input_json or input_json
    relations_source = relations_input_json or input_json

    if not skip_conditions:
        prefix = str(outdir / stem)
        raw_path, table_path = extract_conditions(
            conditions_source,
            prefix,
            model=model,
            save_raw=save_raw,
        )
        time_path = str(outdir / f"{stem}_time.csv")
        standardize_time(table_path, time_path, time_column="Time", model=model)
        if raw_path:
            results["raw_csv"] = raw_path
        results["conditions_csv"] = table_path
        results["time_csv"] = time_path

    if not skip_relations:
        relations_path = str(outdir / f"{stem}_surface_relations.jsonl")
        extract_relations(relations_source, relations_path, model=model)
        results["relations_jsonl"] = relations_path

    if "conditions_csv" in results and "relations_jsonl" in results:
        summary_path = str(outdir / f"{stem}_summary.txt")
        write_summary(results["conditions_csv"], results["relations_jsonl"], summary_path)
        results["summary_txt"] = summary_path
        results.update(
            generate_ptomodel_output(
                relations_jsonl=results["relations_jsonl"],
                table_csv=results["conditions_csv"],
                summary_txt=results["summary_txt"],
                time_csv=results.get("time_csv"),
                output_dir=str(outdir),
                stem=stem,
            )
        )

    if collect_experience_output:
        experience_result = collect_experience(
            results.get("relations_jsonl"),
            results.get("conditions_csv"),
            str(outdir),
            stem=f"{stem}_experience",
        )
        if experience_result.get("json_path"):
            results["experience_json"] = str(experience_result["json_path"])
        if experience_result.get("markdown_path"):
            results["experience_md"] = str(experience_result["markdown_path"])
        results["experience_material_classes_dir"] = str(outdir / "material_classes")

    return results


def run_pipeline_from_pdf(
    input_pdf: str,
    output_dir: str,
    model: str | None = None,
    skip_conditions: bool = False,
    skip_relations: bool = False,
    keep_intermediate: bool = False,
    save_raw: bool = False,
    collect_experience_output: bool = False,
    compact_output: bool = False,
) -> dict[str, str]:
    if compact_output and keep_intermediate:
        raise ValueError("compact_output and keep_intermediate are mutually exclusive.")
    if keep_intermediate:
        ingestion_outputs = ingest_pdf(input_pdf, output_dir)
        pipeline_outputs = run_pipeline(
            ingestion_outputs["conditions_input_json"],
            output_dir,
            model=model,
            skip_conditions=skip_conditions,
            skip_relations=skip_relations,
            conditions_input_json=ingestion_outputs["conditions_input_json"],
            relations_input_json=ingestion_outputs["relations_input_json"],
            save_raw=save_raw,
            collect_experience_output=collect_experience_output,
        )
        return {**ingestion_outputs, **pipeline_outputs}

    payloads = ingest_pdf_payloads(input_pdf)
    tempdir, conditions_path, relations_path = write_temp_surface_inputs(
        payloads["conditions_payload"],
        payloads["relations_payload"],
    )
    try:
        pipeline_outputs = run_pipeline(
            conditions_path,
            output_dir,
            model=model,
            skip_conditions=skip_conditions,
            skip_relations=skip_relations,
            conditions_input_json=conditions_path,
            relations_input_json=relations_path,
            save_raw=save_raw,
            collect_experience_output=collect_experience_output,
        )
        if compact_output:
            return write_compact_job_bundle(
                output_dir=output_dir,
                outputs=pipeline_outputs,
                source_path=input_pdf,
                cleanup_generated=True,
            )
        return pipeline_outputs
    finally:
        tempdir.cleanup()


def main(argv: list[str] | None = None) -> int:
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
    parser.add_argument(
        "--keep-intermediate",
        action="store_true",
        help="Keep PDF text, section splits, and generated JSON inputs on disk.",
    )
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Also save raw LLM responses from condition extraction.",
    )
    parser.add_argument(
        "--collect-experience",
        action="store_true",
        help="Also collect useful and unknown extraction experience into aggregated JSON output.",
    )
    parser.add_argument(
        "--compact-output",
        action="store_true",
        help="Consolidate paper information, modeling plan, and checklist into one compact job folder.",
    )
    parser.add_argument(
        "--expanded-output",
        action="store_true",
        help="Keep the legacy set of separate extraction files.",
    )
    args = parser.parse_args(argv)

    source_path = Path(args.input_source)
    input_format = args.input_format
    if input_format == "auto":
        input_format = "pdf" if source_path.suffix.lower() == ".pdf" else "json"

    if input_format == "pdf":
        compact_output = args.compact_output or (not args.expanded_output and not args.keep_intermediate)
        outputs = run_pipeline_from_pdf(
            args.input_source,
            args.output_dir,
            model=args.model,
            skip_conditions=args.skip_conditions,
            skip_relations=args.skip_relations,
            keep_intermediate=args.keep_intermediate,
            save_raw=args.save_raw,
            collect_experience_output=args.collect_experience,
            compact_output=compact_output,
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
    for _, path in outputs.items():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
