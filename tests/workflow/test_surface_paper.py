from __future__ import annotations

import inspect
import csv
import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from genkai.cli import main
from genkai.literature.surface.pipeline import runner as literature_runner
from genkai.workflows import surface_paper
from genkai.workflow.store import load_manifest


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


def test_real_extraction_outputs_reach_prepare_plan_with_conditions(monkeypatch, tmp_path):
    """Only LLM replies are mocked; the writer, workflow and artifacts are real."""
    conditions_module = importlib.import_module("genkai.literature.surface.extraction.extract_surface_conditions")
    relations_module = importlib.import_module("genkai.literature.surface.extraction.extract_surface_relations")
    time_module = importlib.import_module("genkai.literature.surface.extraction.standardize_surface_time")
    columns = conditions_module.COLUMNS
    values = {"Material": "CeO2", "Surface/Support": "CeO2", "Facet": "(111)", "Time": "2 h"}
    table = "\n".join([
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        "| " + " | ".join(values.get(column, "N/A") for column in columns) + " |",
    ])
    monkeypatch.setattr(conditions_module, "chat_completion", lambda *a, **k: table)
    monkeypatch.setattr(relations_module, "chat_completion", lambda *a, **k: '{"adsorbates":["CO"]}')
    monkeypatch.setattr(time_module, "chat_completion", lambda *a, **k: '| Index | Time |\n|---|---|\n| paper_1 | 120 minutes |')
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"paper": {"Title": "CO on ceria", "Text": "CeO2(111), 2 h."}}), encoding="utf-8")
    root = tmp_path / "run"
    surface_paper.initialize_surface_paper_run(source, root)

    manifest = load_manifest(root)
    plan = json.loads((root / "modeling/plan.json").read_text(encoding="utf-8"))
    assert plan["documents"][0]["selected_information"]["materials"] == ["CeO2"]
    assert plan["documents"][0]["normalized_mapping"]["facet_set"] == ["(111)"]
    assert manifest.artifacts[-1].execution_state.value == "prepared"
    assert manifest.artifacts[-1].metadata["structure_count"] == 0
    extraction = next(a for a in manifest.artifacts if a.artifact_type == "extraction")
    with (root / extraction.metadata["conditions_table"]["path"]).open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle))[0]["Material"] == "CeO2"
