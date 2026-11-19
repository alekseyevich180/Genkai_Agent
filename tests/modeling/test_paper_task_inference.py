"""Paper -> modeling-plan task inference for SAM, ALD-overlayer and amorphous surfaces (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genkai.literature.surface.core.surface_ontology import EXECUTABLE_TASKS, SUPPORTED_MODELING_TASKS
from genkai.literature.surface.extraction.extract_surface_relations import build_prompt
from genkai.modeling.checklist import build_modeling_checklist
from genkai.modeling.mapping import build_ptomodel_payload

SAM_PAPER = Path(__file__).resolve().parents[1] / "fixtures" / "surface_execution" / "sno2_sam_gas_relations.jsonl"


def _document(tmp_path: Path, extraction: dict) -> dict:
    path = tmp_path / "relations.jsonl"
    path.write_text(json.dumps({"id": "doc", "title": "t", "extraction": extraction}) + "\n", encoding="utf-8")
    return build_ptomodel_payload(str(path))["documents"][0]


def _binding(document: dict, task: str, parameter: str) -> tuple[str, object]:
    binding = document["task_argument_template"][task]["parameter_bindings"][parameter]
    return binding["status"], binding["value"]


def test_new_tasks_are_supported_and_executable() -> None:
    for task in ("sam_functionalization", "ald_overlayer", "amorphous_slab"):
        assert task in SUPPORTED_MODELING_TASKS and task in EXECUTABLE_TASKS
    # Generic termination states stay a deferred task.
    assert "surface_functionalization" in SUPPORTED_MODELING_TASKS
    assert "surface_functionalization" not in EXECUTABLE_TASKS


def test_sam_paper_yields_an_executable_sam_task_with_the_stated_anchor() -> None:
    document = build_ptomodel_payload(str(SAM_PAPER))["documents"][0]
    assert "sam_functionalization" in document["executable_tasks"]
    assert "surface_functionalization" not in document["recommended_modeling_tasks"]
    assert _binding(document, "sam_functionalization", "anchor_kind") == ("auto", "phosphonic")
    assert _binding(document, "sam_functionalization", "binding_mode")[0] == "needs_manual_decision"
    assert _binding(document, "sam_functionalization", "molecule")[0] == "needs_upstream_artifact"
    assert _binding(document, "sam_functionalization", "counts")[0] == "needs_manual_decision"
    # Only modifiers named inside a SAM phrase are SAM molecules (not "O2 plasma activation").
    assert document["task_inputs"]["sam_functionalization"]["sam_molecules"] == ["PAC12IMI", "PAC10CA", "PAG3"]
    review = {(item["task"], item["parameter"]) for item in build_modeling_checklist({"documents": [document]})["review_items"]}
    assert ("sam_functionalization", "binding_mode") in review


def test_stated_binding_mode_is_taken_from_the_sam_wording(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        {"materials": ["ZnO"], "surfaces": ["ZnO surface"], "sam_molecules": ["octylphosphonic acid SAM, tridentate binding"]},
    )
    assert _binding(document, "sam_functionalization", "binding_mode") == ("auto", "tridentate")
    assert _binding(document, "sam_functionalization", "anchor_kind") == ("auto", "phosphonic")


def test_generic_terminations_stay_deferred(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        {"materials": ["CeO2"], "surfaces": ["CeO2(111)"], "surface_terminations": ["reduced surface", "hydroxylated"]},
    )
    assert document["deferred_tasks"] == ["surface_functionalization"]
    assert "sam_functionalization" not in document["recommended_modeling_tasks"]


@pytest.mark.parametrize(
    ("overlayer", "coverage", "thickness"),
    [
        ("ALD Al2O3 overlayer of 2 nm (20 ALD cycles), conformal", ("auto", "full"), ("auto", 20.0)),
        ("ALD TiO2 islands, 10 cycles", ("auto", "partial"), ("alternative_not_selected", None)),
        ("ALD TiO2 film, 5 nm", ("auto", "full"), ("needs_manual_decision", None)),  # too thick to model as stated
        ("ALD ZnO overlayer", ("needs_manual_decision", None), ("needs_manual_decision", None)),
    ],
)
def test_ald_overlayer_coverage_and_thickness(tmp_path: Path, overlayer: str, coverage: tuple, thickness: tuple) -> None:
    document = _document(tmp_path, {"materials": ["SnO2"], "surfaces": ["SnO2(110) surface"], "overlayers": [overlayer]})
    assert "ald_overlayer" in document["executable_tasks"]
    assert "amorphous_slab" not in document["recommended_modeling_tasks"]
    assert _binding(document, "ald_overlayer", "coverage") == coverage
    assert _binding(document, "ald_overlayer", "thickness") == thickness
    assert _binding(document, "ald_overlayer", "amorphous")[0] == "needs_upstream_artifact"


def test_ald_cycles_without_thickness_are_reported_not_converted(tmp_path: Path) -> None:
    document = _document(tmp_path, {"surfaces": ["SnO2 surface"], "overlayers": ["ALD Al2O3 coating, 50 cycles"]})
    status, value = _binding(document, "ald_overlayer", "thickness")
    reason = document["task_argument_template"]["ald_overlayer"]["parameter_bindings"]["thickness"]["reason"]
    assert (status, value) == ("needs_manual_decision", None) and "[50]" in reason
    assert document["task_inputs"]["ald_overlayer"]["overlayer_formula"] == "Al2O3"


def test_fabrication_coating_is_not_an_overlayer(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        {"materials": ["SnO2 film"], "surfaces": ["SnO2 surface"], "material_parameters": ["drop-coated on Au electrode", "spin-coated SnO2 film"]},
    )
    assert "ald_overlayer" not in document["recommended_modeling_tasks"]


def test_amorphous_material_is_an_amorphous_slab_and_film_thickness_is_context_only(tmp_path: Path) -> None:
    document = _document(
        tmp_path,
        {"materials": ["amorphous SnO2 film"], "surfaces": ["a-SnO2 surface"], "material_parameters": ["amorphous layer 8 nm thick"]},
    )
    assert "amorphous_slab" in document["executable_tasks"]
    assert document["task_inputs"]["amorphous_slab"]["amorphous_formula"] == "SnO2"
    status, value = _binding(document, "amorphous_slab", "thickness")
    reason = document["task_argument_template"]["amorphous_slab"]["parameter_bindings"]["thickness"]["reason"]
    assert (status, value) == ("needs_manual_decision", None)
    assert "80 A film" in reason


def test_extraction_prompt_asks_for_overlayers_and_sam_molecules() -> None:
    prompt = build_prompt("title", "text")
    for token in ('"overlayers"', '"sam_molecules"', "sam_functionalization", "ald_overlayer", "amorphous_slab"):
        assert token in prompt
