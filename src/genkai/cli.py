"""Command-line interface for artifact-aware Genkai workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import click
from click.core import ParameterSource

from genkai.mlip.protocol import RunMode
from genkai.workflow.store import load_manifest


def _surface_execution_options(command):
    """One set of reviewed-input options for init, surface run and execute."""
    options = [
        click.option("--surface", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Reviewed slab file; skips slab generation."),
        click.option("--bulk", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Local bulk crystal used to cut the slab."),
        click.option("--surface-formula", help="Bulk formula for the Materials Project route (overrides the plan)."),
        click.option("--surface-facet", help="Confirmed exposed facet in the conventional cell, e.g. (110)."),
        click.option("--use-facet-registry", is_flag=True, help="Accept the reviewed stable-facet registry when the paper gives no exposed facet."),
        click.option("--allow-materials-project", is_flag=True, help="Allow downloading the bulk from Materials Project (network, MP_API_KEY)."),
        click.option("--molecule", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Adsorbate structure file."),
        click.option("--molecule-name", help="Built-in gas molecule, e.g. NO2, NH3, H2S, CO, H2, acetone, ethanol."),
        click.option("--coverage-counts", help="Comma-separated adsorbate counts, e.g. 1,2."),
        click.option("--site-symbols", help="Comma-separated adsorption-site elements, e.g. Sn."),
        click.option("--patterns", help="Comma-separated coverage patterns (uniform, clustered, stripe, island, random)."),
        click.option("--random-repeats", type=int, help="Structures per coverage for the random pattern."),
        click.option("--document-id", help="Plan document to execute when the plan has several."),
        click.option("--tasks", help="Comma-separated plan tasks to execute (default: all executable)."),
        click.option("--seed", type=int, default=42, show_default=True),
        click.option(
            "--chain",
            is_flag=True,
            help="Build each task on the previous task's first structure "
            "(vacancy -> ALD -> SAM -> cluster -> adsorbate) instead of all on the clean surface.",
        ),
        click.option(
            "--accept-defaults",
            is_flag=True,
            help="Fill unresolved numeric choices (counts 1,2; cluster 13 atoms; ALD full film 5 A or 30-atom "
            "island; amorphous slab 10 A) and record them. Structure files and the SAM binding mode stay required.",
        ),
        click.option("--vacancy-counts", help="O vacancies per cell, comma-separated, e.g. 1,2."),
        click.option("--vacancy-samples", type=int, help="Vacancy configurations per count (default 3)."),
        click.option("--cluster-element", help="Metal of the supported cluster, e.g. Pt."),
        click.option("--cluster-atoms", type=int, help="Atoms per cluster, e.g. 13."),
        click.option("--cluster-structures", help="Comma-separated cluster lattices: fcc, hcp, bcc."),
        click.option("--sam-molecule", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="3D structure of the SAM molecule."),
        click.option("--binding-mode", help="SAM binding: monodentate|bidentate|tridentate (phosphonic), monodentate|bidentate (carboxylic), top|bridge|hollow|fcc|hcp (thiol)."),
        click.option("--sam-counts", help="SAM molecules per cell, comma-separated, e.g. 1,2."),
        click.option("--anchor-kind", type=click.Choice(["phosphonic", "carboxylic", "thiol"]), help="SAM anchoring group when the molecule has several."),
        click.option("--amorphous", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Periodic amorphous bulk cell (ALD overlayer or amorphous slab)."),
        click.option("--ald-coverage", type=click.Choice(["full", "partial"]), help="ALD continuous film (full) or island (partial)."),
        click.option("--ald-thickness", type=float, help="ALD film thickness in angstrom (full coverage)."),
        click.option("--island-atoms", type=int, help="ALD island size in atoms (partial coverage)."),
        click.option("--amorphous-thickness", type=float, help="Pure amorphous slab thickness in angstrom."),
    ]
    for option in reversed(options):
        command = option(command)
    return command


def _surface_overrides(options: dict[str, Any]):
    from genkai.modeling.surface.executor import SurfaceExecutionOverrides

    values = dict(options)
    for key in ("coverage_counts", "vacancy_counts", "sam_counts"):
        try:
            values[key] = tuple(int(item) for item in _split_csv(values[key]) or ()) or None
        except ValueError as exc:
            raise click.BadParameter("use integers such as 1,2", param_hint=f"--{key.replace('_', '-')}") from exc
    for key in ("site_symbols", "patterns", "tasks", "cluster_structures"):
        values[key] = _split_csv(values[key])
    return SurfaceExecutionOverrides(**values)


def _modeling_overrides(modeling_mode: str, options: dict[str, Any]):
    if modeling_mode == "prepare":
        context = click.get_current_context()
        if any(
            context.get_parameter_source(key) not in (None, ParameterSource.DEFAULT)
            for key in options
        ):
            raise click.UsageError("Modeling input options require --modeling-mode structure-only.")
        return None
    return _surface_overrides(options)


def _with_surface_errors(
    operation: Callable[[], Any], run_root: Path, *, enabled: bool = True,
):
    if not enabled:
        return operation()
    from genkai.modeling.surface.executor import SurfaceExecutionBlocked

    try:
        return operation()
    except SurfaceExecutionBlocked as exc:
        click.echo("Blocked: these inputs must be supplied or confirmed:", err=True)
        for key, reason in exc.missing.items():
            click.echo(f"  - {key}: {reason}", err=True)
        click.echo(
            "Deselect tasks with --tasks; numeric choices can take recorded defaults with --accept-defaults.",
            err=True,
        )
        if (run_root / "modeling" / "plan.json").is_file():
            click.echo(f"Plan retained: {run_root / 'modeling' / 'plan.json'}", err=True)
            click.echo("Resume with `genkai-workflow surface execute --run-root RUN` and reviewed inputs.", err=True)
        raise click.exceptions.Exit(2) from exc


def _print_structures(run_root: Path) -> None:
    manifest = load_manifest(run_root)
    artifact = next(
        item for item in reversed(manifest.artifacts) if item.artifact_type == "structure-set"
    )
    click.echo(f"structures: {run_root / artifact.path}")
    click.echo(f"report: {run_root / artifact.metadata['execution_report']}")
    click.echo(
        f"frames: {artifact.metadata['structure_count']} {artifact.metadata['roles']} "
        f"validation={artifact.validation_status.value}"
    )
    for task, reason in artifact.metadata.get("skipped_tasks", {}).items():
        click.echo(f"Skipped {task}: {reason}", err=True)


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
@click.option(
    "--conditions",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Saved experimental-condition CSV to include in the modeling plan.",
)
@click.option("--mock-labels", type=click.Path(exists=True, path_type=Path))
@click.option("--base-model-uri")
@click.option("--base-model-version")
@click.option("--base-model-sha256")
@click.option("--modeling-mode", type=click.Choice(["prepare", "structure-only"]), default="prepare", show_default=True)
@_surface_execution_options
def init_command(
    run_root: Path,
    relations: Path,
    conditions: Path | None,
    mock_labels: Path | None,
    base_model_uri: str | None,
    base_model_version: str | None,
    base_model_sha256: str | None,
    modeling_mode: str,
    **execution_options,
) -> None:
    """Initialize saved extraction; optionally generate reviewed structures offline."""

    overrides = _modeling_overrides(modeling_mode, execution_options)

    from genkai.workflows.paper_to_mlip import initialize_paper_to_mlip_run

    _with_surface_errors(
        lambda: initialize_paper_to_mlip_run(
            run_root,
            relations,
            conditions_csv=conditions,
            modeling_mode=modeling_mode,
            modeling_overrides=overrides,
            mock_labels=mock_labels,
            base_model_uri=base_model_uri,
            base_model_version=base_model_version,
            base_model_sha256=base_model_sha256,
        ),
        run_root,
        enabled=modeling_mode == "structure-only",
    )
    click.echo(str(run_root / "manifest.json"))
    if modeling_mode == "structure-only":
        _print_structures(run_root)


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
@click.option("--modeling-mode", type=click.Choice(["prepare", "structure-only"]), default="prepare", show_default=True)
@_surface_execution_options
def surface_run(
    input_source: Path,
    run_root: Path,
    input_format: str,
    model: str | None,
    save_raw: bool,
    collect_experience: bool,
    modeling_mode: str,
    **execution_options,
) -> None:
    """Extract PDF/JSON paper text, then prepare or execute a modeling plan."""

    overrides = _modeling_overrides(modeling_mode, execution_options)

    from genkai.workflows.surface_paper import initialize_surface_paper_run

    outputs = _with_surface_errors(
        lambda: initialize_surface_paper_run(
            input_source,
            run_root,
            input_format=input_format,  # type: ignore[arg-type]
            model=model,
            save_raw=save_raw,
            collect_experience_output=collect_experience,
            modeling_mode=modeling_mode,
            modeling_overrides=overrides,
        ),
        run_root,
        enabled=modeling_mode == "structure-only",
    )
    for key, path in outputs.items():
        if key not in ("structures_extxyz", "execution_report"):
            click.echo(path)
    if modeling_mode == "structure-only":
        _print_structures(run_root)


def _split_csv(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    return tuple(item.strip() for item in value.split(",") if item.strip())


@surface_group.command("execute")
@click.option("--run-root", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@_surface_execution_options
def surface_execute(
    run_root: Path,
    **execution_options,
) -> None:
    """Generate structures for a run's modeling plan (structure-only, no energy model)."""

    from genkai.modeling.surface.executor import execute_surface_plan

    manifest = load_manifest(run_root)
    plan = next(
        (artifact for artifact in reversed(manifest.artifacts) if artifact.artifact_type == "modeling-plan"),
        None,
    )
    if plan is None:
        raise click.ClickException("The run has no modeling-plan artifact; run `genkai-workflow init` first.")
    overrides = _surface_overrides(execution_options)
    _with_surface_errors(lambda: execute_surface_plan(plan, run_root, overrides), run_root)
    _print_structures(run_root)


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
