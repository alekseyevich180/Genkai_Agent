"""Command-line interface for artifact-aware Genkai workflows."""

from __future__ import annotations

import json
from pathlib import Path

import click

from genkai.mlip.protocol import RunMode
from genkai.workflow.store import load_manifest


def _print_report(report) -> None:
    payload = report.model_dump(mode="json")
    payload["passed"] = report.passed
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@click.group()
def main() -> None:
    """Inspect and preflight reproducible scientific workflow runs."""


@main.command("init")
@click.argument("run_root", type=click.Path(path_type=Path))
@click.option("--relations", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--mock-labels", type=click.Path(exists=True, path_type=Path))
@click.option("--base-model-uri")
@click.option("--base-model-version")
@click.option("--base-model-sha256")
def init_command(
    run_root: Path,
    relations: Path,
    mock_labels: Path | None,
    base_model_uri: str | None,
    base_model_version: str | None,
    base_model_sha256: str | None,
) -> None:
    """Initialize an offline run from saved extraction output."""

    from genkai.workflows.paper_to_mlip import initialize_paper_to_mlip_run

    initialize_paper_to_mlip_run(
        run_root,
        relations,
        mock_labels=mock_labels,
        base_model_uri=base_model_uri,
        base_model_version=base_model_version,
        base_model_sha256=base_model_sha256,
    )
    click.echo(str(run_root / "manifest.json"))


@main.command("inspect")
@click.option("--run-root", default=".", type=click.Path(path_type=Path))
def inspect_command(run_root: Path) -> None:
    """Print a run manifest."""

    click.echo(load_manifest(run_root).model_dump_json(indent=2))


def _preflight(run_root: Path, target: str, mode: str) -> None:
    from genkai.workflows.paper_to_mlip import preflight_paper_to_mlip

    report = preflight_paper_to_mlip(
        run_root,
        target,  # type: ignore[arg-type]
        RunMode(mode),
    )
    _print_report(report)
    if not report.passed:
        raise click.exceptions.Exit(1)


@main.command("preflight")
@click.option("--run-root", default=".", type=click.Path(path_type=Path))
@click.option("--target", required=True, type=click.Choice(["mace", "deepmd", "uma"]))
@click.option(
    "--mode",
    required=True,
    type=click.Choice([mode.value for mode in RunMode]),
)
def preflight_command(run_root: Path, target: str, mode: str) -> None:
    """Validate a target route without launching external work."""

    _preflight(run_root, target, mode)


@main.command("run")
@click.option("--run-root", default=".", type=click.Path(path_type=Path))
@click.option("--target", required=True, type=click.Choice(["mace", "deepmd", "uma"]))
@click.option("--mode", default="dry-run", type=click.Choice(["dry-run"]))
def run_command(run_root: Path, target: str, mode: str) -> None:
    """Run the reference workflow in dry-run mode only."""

    _preflight(run_root, target, mode)


@main.group("surface")
def surface_group() -> None:
    """Extract and organize surface-science literature."""


@surface_group.command("list-tools")
@click.option("--category")
def surface_list_tools(category: str | None) -> None:
    """Show surface-literature tools grouped by category."""

    from genkai.literature.surface import render_surface_tool_catalog

    click.echo(render_surface_tool_catalog(category), nl=False)


@surface_group.command("ingest")
@click.argument("input_pdf", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(path_type=Path),
)
def surface_ingest(input_pdf: Path, output_dir: Path) -> None:
    """Convert a PDF into routed literature-extraction inputs."""

    from genkai.literature.surface import ingest_pdf

    for path in ingest_pdf(str(input_pdf), str(output_dir)).values():
        click.echo(path)


@surface_group.command("run")
@click.argument("input_source", type=click.Path(exists=True, path_type=Path))
@click.option("--run-root", required=True, type=click.Path(path_type=Path))
@click.option(
    "--input-format",
    type=click.Choice(["auto", "json", "pdf"]),
    default="auto",
    show_default=True,
)
@click.option("--model")
@click.option("--save-raw", is_flag=True)
@click.option("--collect-experience", is_flag=True)
def surface_run(
    input_source: Path,
    run_root: Path,
    input_format: str,
    model: str | None,
    save_raw: bool,
    collect_experience: bool,
) -> None:
    """Run literature extraction and initialize the artifact workflow."""

    from genkai.workflows.surface_paper import initialize_surface_paper_run

    outputs = initialize_surface_paper_run(
        input_source,
        run_root,
        input_format=input_format,  # type: ignore[arg-type]
        model=model,
        save_raw=save_raw,
        collect_experience_output=collect_experience,
    )
    for path in outputs.values():
        click.echo(path)


@surface_group.command("conditions")
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
@click.option("--prefix", required=True, type=click.Path(path_type=Path))
@click.option("--model")
@click.option("--save-raw", is_flag=True)
def surface_conditions(
    input_json: Path,
    prefix: Path,
    model: str | None,
    save_raw: bool,
) -> None:
    """Extract a surface-conditions table from JSON input."""

    from genkai.literature.surface.extraction.extract_surface_conditions import (
        extract_conditions,
    )

    raw_path, table_path = extract_conditions(
        str(input_json),
        str(prefix),
        model=model,
        save_raw=save_raw,
    )
    if raw_path:
        click.echo(raw_path)
    click.echo(table_path)


@surface_group.command("relations")
@click.argument("input_json", type=click.Path(exists=True, path_type=Path))
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option("--model")
def surface_relations(
    input_json: Path,
    output: Path,
    model: str | None,
) -> None:
    """Extract surface relations as JSONL."""

    from genkai.literature.surface.extraction.extract_surface_relations import (
        extract_relations,
    )

    click.echo(extract_relations(str(input_json), str(output), model=model))


@surface_group.command("time")
@click.argument("input_csv", type=click.Path(exists=True, path_type=Path))
@click.argument("output_csv", type=click.Path(path_type=Path))
@click.option("--model")
def surface_time(
    input_csv: Path,
    output_csv: Path,
    model: str | None,
) -> None:
    """Normalize surface-research time expressions."""

    from genkai.literature.surface import standardize_time

    click.echo(
        standardize_time(
            str(input_csv),
            str(output_csv),
            time_column="Time",
            model=model,
        )
    )


@surface_group.command("summary")
@click.argument("table_csv", type=click.Path(exists=True, path_type=Path))
@click.argument("relations_jsonl", type=click.Path(exists=True, path_type=Path))
@click.argument("output_txt", type=click.Path(path_type=Path))
def surface_summary(
    table_csv: Path,
    relations_jsonl: Path,
    output_txt: Path,
) -> None:
    """Write a human-readable extraction summary."""

    from genkai.literature.surface import write_summary

    click.echo(write_summary(str(table_csv), str(relations_jsonl), str(output_txt)))


@surface_group.command("experience")
@click.option("--relations", type=click.Path(exists=True, path_type=Path))
@click.option("--table", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", required=True, type=click.Path(path_type=Path))
@click.option("--stem", default="surface_experience", show_default=True)
def surface_experience(
    relations: Path | None,
    table: Path | None,
    output_dir: Path,
    stem: str,
) -> None:
    """Collect reusable surface-literature experience."""

    from genkai.literature.surface import collect_experience

    result = collect_experience(
        str(relations) if relations else None,
        str(table) if table else None,
        str(output_dir),
        stem=stem,
    )
    for key in ("json_path", "markdown_path"):
        if result.get(key):
            click.echo(result[key])


@surface_group.command("registry")
@click.option(
    "--material-class-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def surface_registry(material_class_dir: Path | None) -> None:
    """Build the canonical surface parameter registry."""

    from genkai.literature.surface import build_surface_parameter_registry

    registry = build_surface_parameter_registry(
        material_class_dir=material_class_dir,
    )
    click.echo(json.dumps(registry, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
