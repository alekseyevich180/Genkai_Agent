import json
from pathlib import Path

from genkai.literature.surface import run_surface_extraction
from genkai.modeling.ptomodel import build_modeling_plan
from genkai.modeling.surface import build_surface_candidates
from genkai.workflow.store import load_manifest


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "surface_facade"
    / "minimal_surface_relations.jsonl"
)


def test_saved_surface_extraction_builds_artifact_chain_without_network(
    tmp_path: Path,
) -> None:
    extraction = run_surface_extraction(FIXTURE, tmp_path)
    plan = build_modeling_plan(extraction, tmp_path)
    structures = build_surface_candidates(plan, tmp_path, mode="dry-run")

    manifest = load_manifest(tmp_path)
    plan_payload = json.loads((tmp_path / plan.path).read_text())
    candidates = json.loads((tmp_path / structures.path).read_text())

    assert extraction.artifact_type == "extraction"
    assert plan.parent_ids == [extraction.artifact_id]
    assert structures.parent_ids == [plan.artifact_id]
    assert plan_payload["documents"][0]["normalized_mapping"]["facet_set"] == [
        "(111)"
    ]
    assert plan_payload["documents"][0]["selected_information"]["adsorbates"] == [
        "*OH"
    ]
    assert candidates["execution_mode"] == "dry-run"
    assert candidates["manual_decisions"]
    assert [item.artifact_type for item in manifest.artifacts] == [
        "paper",
        "extraction",
        "modeling-plan",
        "structure-set",
    ]
    assert (tmp_path / "article.json").is_file()
    assert (tmp_path / "modeling" / "checklist.json").is_file()
