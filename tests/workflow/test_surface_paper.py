from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from click.testing import CliRunner

from genkai.cli import main
from genkai.literature.surface.pipeline import runner as literature_runner
from genkai.workflows import surface_paper


def test_literature_pipeline_stops_before_modeling(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def extract_conditions(source, prefix, **kwargs):
        table = Path(f"{prefix}_table.csv")
        table.write_text("Index,Time\n1,2 h\n", encoding="utf-8")
        return None, str(table)

    def standardize_time(table, output, **kwargs):
        Path(output).write_text("Index,Time\n1,120 minutes\n", encoding="utf-8")
        return output

    def extract_relations(source, output, **kwargs):
        Path(output).write_text(
            '{"title":"demo","extraction":{"materials":["CeO2"]}}\n',
            encoding="utf-8",
        )
        return output

    def write_summary(table, relations, output):
        Path(output).write_text("summary\n", encoding="utf-8")
        return output

    monkeypatch.setattr(literature_runner, "extract_conditions", extract_conditions)
    monkeypatch.setattr(literature_runner, "standardize_time", standardize_time)
    monkeypatch.setattr(literature_runner, "extract_relations", extract_relations)
    monkeypatch.setattr(literature_runner, "write_summary", write_summary)

    outputs = literature_runner.run_literature_pipeline(
        "input.json",
        tmp_path,
    )

    assert set(outputs) == {
        "conditions_csv",
        "time_csv",
        "relations_jsonl",
        "summary_txt",
    }
    source = inspect.getsource(literature_runner)
    assert "genkai.modeling" not in source
    assert "paperread" not in source


def test_surface_workflow_initializes_artifact_chain_from_relations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed = {}
    relations = tmp_path / "demo_surface_relations.jsonl"
    monkeypatch.setattr(
        surface_paper,
        "run_literature_pipeline",
        lambda *args, **kwargs: {"relations_jsonl": str(relations)},
    )

    def initialize(run_root, relations_path, **kwargs):
        observed.update(
            run_root=Path(run_root),
            relations=Path(relations_path),
        )

    monkeypatch.setattr(
        surface_paper,
        "initialize_paper_to_mlip_run",
        initialize,
    )

    outputs = surface_paper.initialize_surface_paper_run(
        "input.json",
        tmp_path,
    )

    assert observed == {"run_root": tmp_path, "relations": relations}
    assert outputs["manifest"] == str(tmp_path / "manifest.json")


def test_surface_workflow_requires_relation_extraction(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        surface_paper,
        "run_literature_pipeline",
        lambda *args, **kwargs: {"conditions_csv": "conditions.csv"},
    )

    with pytest.raises(
        ValueError,
        match="surface workflow requires relation extraction",
    ):
        surface_paper.initialize_surface_paper_run("input.json", tmp_path)


def test_surface_cli_lists_new_commands_without_legacy_ptomodel() -> None:
    runner = CliRunner()

    help_result = runner.invoke(main, ["surface", "--help"])
    catalog_result = runner.invoke(main, ["surface", "list-tools"])

    assert help_result.exit_code == 0, help_result.output
    for command in (
        "list-tools",
        "ingest",
        "run",
        "conditions",
        "relations",
        "time",
        "summary",
        "experience",
        "registry",
    ):
        assert command in help_result.output
    assert "ptomodel" not in help_result.output
    assert catalog_result.exit_code == 0, catalog_result.output
    assert "Surface tooling catalog" in catalog_result.output
