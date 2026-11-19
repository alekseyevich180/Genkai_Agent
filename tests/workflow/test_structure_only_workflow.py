"""Paper/replay -> plan -> real geometry, with no network or energy model."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest
from ase.io import read
from click.testing import CliRunner
from pymatgen.core import Lattice, Structure

from genkai.cli import main
from genkai.modeling.surface import executor
from genkai.modeling.surface.executor import SurfaceExecutionOverrides
from genkai.workflow.store import load_manifest
from genkai.workflows.paper_to_mlip import initialize_paper_to_mlip_run
from genkai.workflows.surface_paper import initialize_surface_paper_run


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/surface_execution/sno2_sam_gas_relations.jsonl"


@pytest.fixture
def bulk_file(tmp_path):
    path = tmp_path / "SnO2.cif"
    Structure.from_spacegroup(
        "P4_2/mnm", Lattice.tetragonal(4.737, 3.186),
        ["Sn", "O"], [[0, 0, 0], [0.3057, 0.3057, 0]],
    ).to(filename=str(path))
    return path


@pytest.fixture
def mock_paper_replies(monkeypatch, tmp_path):
    """Only substitute provider replies and the PDF text-conversion boundary."""
    conditions = importlib.import_module("genkai.literature.surface.extraction.extract_surface_conditions")
    relations = importlib.import_module("genkai.literature.surface.extraction.extract_surface_relations")
    times = importlib.import_module("genkai.literature.surface.extraction.standardize_surface_time")
    runner = importlib.import_module("genkai.literature.surface.pipeline.runner")
    from genkai.literature.surface.extraction.ingest_pdf import build_surface_inputs_from_sections

    values = {"Material": "SnO2", "Surface/Support": "SnO2 surface", "Facet": "(110)", "Time": "2 h"}
    table = "\n".join([
        "| " + " | ".join(conditions.COLUMNS) + " |",
        "| " + " | ".join("---" for _ in conditions.COLUMNS) + " |",
        "| " + " | ".join(values.get(column, "N/A") for column in conditions.COLUMNS) + " |",
    ])
    monkeypatch.setattr(conditions, "chat_completion", lambda *a, **k: table)
    monkeypatch.setattr(relations, "chat_completion", lambda *a, **k: '{"adsorbates":["NO2"]}')
    monkeypatch.setattr(times, "chat_completion", lambda *a, **k: '| Index | Time |\n|---|---|\n| paper_1 | 120 minutes |')
    conditions_payload, relations_payload = build_surface_inputs_from_sections(
        "SnO2 sensor", {"methods": "SnO2 exposed (110) surface, 2 h.", "abstract": "NO2 adsorption."},
    )
    monkeypatch.setattr(runner, "ingest_pdf_payloads", lambda *a, **k: {
        "conditions_payload": conditions_payload, "relations_payload": relations_payload,
    })
    source = tmp_path / "paper.json"
    source.write_text(json.dumps({"paper": {"Title": "SnO2 sensor", "Text": "NO2 adsorption."}}), encoding="utf-8")
    return source


def assert_real_structures(root):
    manifest = load_manifest(root)
    assert [a.artifact_type for a in manifest.artifacts] == [
        "paper", "extraction", "modeling-plan", "structure-set",
    ]
    plan, structures = manifest.artifacts[-2:]
    assert structures.execution_state.value == "succeeded"
    assert structures.parent_ids == [plan.artifact_id]
    assert structures.evidence_level.value == "heuristic"
    assert structures.metadata["calculator"] == "none"
    assert structures.metadata["scientific_calculation_started"] is False
    assert structures.sha256 == hashlib.sha256((root / structures.path).read_bytes()).hexdigest()
    assert all(stage.execution_state.value == "succeeded" for stage in manifest.stages)
    assert not (root / "stages/03_surface_modeling/candidates.json").exists()
    frames = read(root / structures.path, index=":")
    assert len(frames) == structures.metadata["structure_count"] >= 1
    assert all(frame.calc is None and "energy" not in frame.info for frame in frames)
    return structures, frames


def test_saved_relations_can_generate_structures_in_one_call(tmp_path, bulk_file):
    root = tmp_path / "run"
    initialize_paper_to_mlip_run(
        root, FIXTURE, modeling_mode="structure-only",
        modeling_overrides=SurfaceExecutionOverrides(
            bulk=bulk_file, surface_facet="(110)", molecule_name="NO2",
            coverage_counts=(1,), patterns=("uniform",), tasks=("slab_generation", "adsorbate_landscape"),
        ),
    )
    structures, frames = assert_real_structures(root)
    assert len(frames) > 1
    assert "adsorbate_landscape" in structures.metadata["source_tasks"]


@pytest.mark.parametrize("input_format", ["json", "pdf"])
def test_paper_pipeline_returns_structure_outputs_and_preserves_conditions(
    tmp_path, bulk_file, mock_paper_replies, input_format,
):
    root = tmp_path / "run"
    outputs = initialize_surface_paper_run(
        mock_paper_replies, root, input_format=input_format,
        modeling_mode="structure-only",
        modeling_overrides=SurfaceExecutionOverrides(
            bulk=bulk_file, surface_facet="(110)", tasks=("slab_generation",),
        ),
    )
    structures, _ = assert_real_structures(root)
    assert Path(outputs["structures_extxyz"]) == root / structures.path
    assert Path(outputs["execution_report"]).is_file()
    assert (root / "stages/01_paperread/conditions.csv").is_file()
    plan = json.loads((root / "modeling/plan.json").read_text(encoding="utf-8"))
    assert plan["documents"][0]["selected_information"]["materials"] == ["SnO2"]


@pytest.mark.parametrize("api", ["replay", "paper"])
@pytest.mark.parametrize("mode,overrides", [
    ("production", None), ("", None), ("prepare", SurfaceExecutionOverrides(molecule_name="NO2")),
])
def test_invalid_modeling_request_has_no_extraction_or_files(tmp_path, monkeypatch, api, mode, overrides):
    def forbidden(*a, **k):
        pytest.fail("invalid request must be rejected before extraction")

    surface_paper = importlib.import_module("genkai.workflows.surface_paper")
    monkeypatch.setattr(surface_paper, "run_literature_pipeline", forbidden)
    monkeypatch.setattr(surface_paper, "run_literature_pipeline_from_pdf", forbidden)
    root = tmp_path / "run"
    with pytest.raises(ValueError, match="modeling"):
        if api == "replay":
            initialize_paper_to_mlip_run(root, tmp_path / "missing.jsonl", modeling_mode=mode, modeling_overrides=overrides)
        else:
            initialize_surface_paper_run(tmp_path / "missing.pdf", root, modeling_mode=mode, modeling_overrides=overrides)
    assert not root.exists()


def test_default_replay_remains_prepare_only(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        pytest.fail("default prepare mode must not execute geometry")
    monkeypatch.setattr(executor, "execute_surface_plan", forbidden)
    root = tmp_path / "run"
    initialize_paper_to_mlip_run(root, FIXTURE)
    artifact = load_manifest(root).artifacts[-1]
    assert artifact.execution_state.value == "prepared"
    assert artifact.metadata["structure_count"] == 0


def test_cli_blocked_run_keeps_plan_and_can_resume_without_extraction(tmp_path, bulk_file):
    root = tmp_path / "run"
    runner = CliRunner()
    blocked = runner.invoke(main, ["init", str(root), "--relations", str(FIXTURE), "--modeling-mode", "structure-only"])
    assert blocked.exit_code == 2, blocked.output
    assert "Blocked" in blocked.output and "coverage_counts" in blocked.output
    manifest = load_manifest(root)
    assert [a.artifact_type for a in manifest.artifacts] == ["paper", "extraction", "modeling-plan"]
    before = (root / "modeling/plan.json").read_bytes()
    result = runner.invoke(main, [
        "surface", "execute", "--run-root", str(root), "--bulk", str(bulk_file),
        "--surface-facet", "110", "--tasks", "slab_generation",
    ])
    assert result.exit_code == 0, result.output
    assert (root / "modeling/plan.json").read_bytes() == before
    assert_real_structures(root)


@pytest.mark.parametrize("entry", ["init", "surface-run"])
def test_cli_structure_only_forwards_reviewed_parameters(
    tmp_path, bulk_file, mock_paper_replies, entry,
):
    root = tmp_path / "run"
    prefix = (["init", str(root), "--relations", str(FIXTURE)] if entry == "init" else
              ["surface", "run", str(mock_paper_replies), "--run-root", str(root)])
    result = CliRunner().invoke(main, [
        *prefix, "--modeling-mode", "structure-only", "--bulk", str(bulk_file),
        "--surface-facet", "110", "--tasks", "slab_generation", "--seed", "9",
    ])
    assert result.exit_code == 0, result.output
    artifact, _ = assert_real_structures(root)
    assert artifact.provenance.parameters["seed"] == 9
    assert "structures:" in result.output


@pytest.mark.parametrize("extra", [["--seed", "42"], ["--coverage-counts", "1,2"]])
@pytest.mark.parametrize("entry", ["init", "surface-run"])
def test_cli_rejects_ignored_overrides_in_prepare_mode(tmp_path, mock_paper_replies, extra, entry):
    root = tmp_path / "run"
    prefix = (["init", str(root), "--relations", str(FIXTURE)] if entry == "init" else
              ["surface", "run", str(mock_paper_replies), "--run-root", str(root)])
    result = CliRunner().invoke(main, [*prefix, *extra])
    assert result.exit_code == 2
    assert "--modeling-mode structure-only" in result.output
    assert not root.exists()


def test_runtime_failure_does_not_fall_back_to_prepared_structure_artifact(tmp_path, bulk_file, monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("deliberate geometry failure")
    monkeypatch.setattr(executor, "_run_adsorbate_landscape", fail)
    root = tmp_path / "run"
    with pytest.raises(RuntimeError, match="deliberate geometry failure"):
        initialize_paper_to_mlip_run(
            root, FIXTURE, modeling_mode="structure-only",
            modeling_overrides=SurfaceExecutionOverrides(
                bulk=bulk_file, surface_facet="(110)", molecule_name="NO2", coverage_counts=(1,),
                tasks=("slab_generation", "adsorbate_landscape"),
            ),
        )
    manifest = load_manifest(root)
    assert manifest.stages[-1].execution_state.value == "failed"
    assert not any(a.artifact_type == "structure-set" for a in manifest.artifacts)
