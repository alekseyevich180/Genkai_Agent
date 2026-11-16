"""The modeling smoke script: case registry integrity and one end-to-end case."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_modeling_smoke.py"


def _load():
    spec = importlib.util.spec_from_file_location("run_modeling_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def test_every_case_uses_existing_repository_structures_and_entry_points() -> None:
    smoke = _load()
    ids = [case.case_id for case in smoke.CASES]
    assert len(ids) == len(set(ids))
    for key, (path, _) in smoke.INPUTS.items():
        assert path.is_file(), f"{key}: {path} is missing"
    methods = {case.method for case in smoke.CASES}
    assert methods == {
        "slab_generation",
        "vacancy_landscape",
        "adsorbate_landscape",
        "surface_cluster_builder",
        "cluster_search",
        "surface_execute",
        "sam",
        "ald_overlayer",
        "amorphous_slab",
    }
    ctx = smoke.Context(profile="local", device="cpu", uma_model="uma-s-1p2", enabled=set())
    for case in smoke.CASES:
        for command in case.commands(ctx, ROOT / "unused"):
            entry = command[1]
            assert entry == "-m" or Path(entry).is_file(), f"{case.case_id}: entry point {entry} not found"
            if not case.requires:
                assert "uma" not in command, f"{case.case_id}: local profile must not request UMA"


def test_one_case_runs_end_to_end_and_gated_cases_are_skipped(tmp_path) -> None:
    smoke = _load()
    code = smoke.main(["--only", "slab_sno2_101,slab_sno2_materials_project", "--output-dir", str(tmp_path)])
    assert code == 0
    report = json.loads((tmp_path / "smoke_report.json").read_text(encoding="utf-8"))
    status = {case["case_id"]: case["status"] for case in report["cases"]}
    assert status == {"slab_sno2_101": "PASS", "slab_sno2_materials_project": "SKIP"}
    assert report["scientific_calculation"] is False
    # Cases left out by --only/--skip are recorded, so a partial table is not mistaken for a full run.
    selection = report["selection"]
    assert selection["selected"] == 2 and selection["total"] == len(smoke.CASES)
    assert "ald_full_asno2_on_sno2" in selection["not_selected"]
    frame = report["cases"][0]["structures"]["frames"][0]
    assert frame["n_fixed"] > 0 and frame["vacuum_gap_A"] >= 5.0
