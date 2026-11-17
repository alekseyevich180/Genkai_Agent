import csv
import hashlib
import json

import pytest

from genkai.literature.surface.artifacts import run_surface_extraction
from genkai.modeling.checklist import build_modeling_checklist
from genkai.modeling.mapping import build_ptomodel_payload
from genkai.modeling.ptomodel import build_modeling_plan


def write_conditions(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Index", "Material", "Facet", "Temperature"])
        writer.writeheader()
        writer.writerows(rows)


def write_relations(path, ids):
    path.write_text("".join(json.dumps({
        "id": key, "title": key, "extraction": {"adsorbates": ["CO"]},
    }) + "\n" for key in ids), encoding="utf-8")


def test_conditions_are_snapshotted_hashed_and_used_after_original_is_removed(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["paper"])
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [{"Index": "paper_1", "Material": "CeO2", "Facet": "(111)"}])
    original_hash = hashlib.sha256(conditions.read_bytes()).hexdigest()
    root = tmp_path / "run"
    extraction = run_surface_extraction(relations, root, conditions_csv=conditions)
    ref = extraction.metadata["conditions_table"]
    assert ref["path"] == "stages/01_paperread/conditions.csv"
    assert ref["sha256"] == original_hash
    conditions.unlink()

    plan = build_modeling_plan(extraction, root)
    payload = json.loads((root / plan.path).read_text(encoding="utf-8"))
    assert payload["documents"][0]["selected_information"]["materials"] == ["CeO2"]
    assert payload["documents"][0]["normalized_mapping"]["facet_set"] == ["(111)"]
    assert payload["sources"]["table_csv"] == ref["path"]
    assert plan.metadata["conditions_table"] == ref


def test_changed_condition_snapshot_is_rejected_before_planning(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["paper"])
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [{"Index": "paper_1", "Material": "CeO2"}])
    root = tmp_path / "run"
    extraction = run_surface_extraction(relations, root, conditions_csv=conditions)
    (root / extraction.metadata["conditions_table"]["path"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="[Hh]ash|SHA-256|sha256"):
        build_modeling_plan(extraction, root)
    assert not (root / "modeling" / "plan.json").exists()


def test_conditions_match_document_ids_not_csv_row_order(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["a", "b", "c"])
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [
        {"Index": "b_1", "Material": "SnO2"},
        {"Index": "a_1", "Material": "CeO2"},
    ])
    payload = build_ptomodel_payload(str(relations), str(conditions))
    assert [doc["selected_information"]["materials"] for doc in payload["documents"]] == [
        ["CeO2"], ["SnO2"], [],
    ]


def test_multiple_conditions_preserve_rows_and_do_not_choose_conflicting_values(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["surface_relations"])
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [
        {"Index": "surface_conditions_1", "Material": "CeO2", "Facet": "(111)", "Temperature": "100 C"},
        {"Index": "surface_conditions_1", "Material": "CeO2", "Facet": "(110)", "Temperature": "200 C"},
    ])
    payload = build_ptomodel_payload(str(relations), str(conditions))
    doc = payload["documents"][0]
    assert doc["selected_information"]["materials"] == ["CeO2"]
    assert doc["normalized_mapping"]["facet_set"] == []
    assert len(doc["condition_rows"]) == 2
    assert doc["condition_conflicts"]["Facet"] == ["(111)", "(110)"]
    checklist = build_modeling_checklist(payload)
    assert any(item["parameter"] == "Facet" and item["task"] == "conditions" for item in checklist["review_items"])


def test_explicit_relation_values_keep_priority_over_conditions(tmp_path):
    relations = tmp_path / "relations.jsonl"
    relations.write_text(json.dumps({"id": "a", "extraction": {"materials": ["SnO2"]}}), encoding="utf-8")
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [{"Index": "a_1", "Material": "CeO2"}])
    payload = build_ptomodel_payload(str(relations), str(conditions))
    assert payload["documents"][0]["selected_information"]["materials"] == ["SnO2"]


def test_unrelated_document_id_is_not_used_even_for_a_single_document(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["paper_a"])
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [{"Index": "paper_b_1", "Material": "CeO2"}])
    payload = build_ptomodel_payload(str(relations), str(conditions))
    assert payload["documents"][0]["selected_information"]["materials"] == []
    assert any(item["parameter"] == "document_id" for item in build_modeling_checklist(payload)["review_items"])


def test_missing_condition_file_does_not_leave_a_partial_run(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["paper"])
    root = tmp_path / "run"
    with pytest.raises(FileNotFoundError):
        run_surface_extraction(relations, root, conditions_csv=tmp_path / "missing.csv")
    assert not root.exists()


def test_condition_artifact_path_cannot_escape_run_root(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["paper"])
    root = tmp_path / "run"
    extraction = run_surface_extraction(relations, root)
    extraction.metadata["conditions_table"] = {"path": "../outside.csv", "sha256": "0" * 64}
    with pytest.raises(ValueError, match="inside the run root"):
        build_modeling_plan(extraction, root)
    assert not (root / "modeling/plan.json").exists()


def test_ambiguous_exact_and_paragraph_ids_require_review(tmp_path):
    relations = tmp_path / "relations.jsonl"
    write_relations(relations, ["sample", "sample_1"])
    conditions = tmp_path / "table.csv"
    write_conditions(conditions, [{"Index": "sample_1", "Material": "CeO2"}])
    payload = build_ptomodel_payload(str(relations), str(conditions))
    # It could be sample's first paragraph or an exact ID for sample_1.
    assert all(doc["selected_information"]["materials"] == [] for doc in payload["documents"])
    assert all(doc["conditions_unmatched"] for doc in payload["documents"])
