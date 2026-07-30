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


if __name__ == "__main__":
    main()
