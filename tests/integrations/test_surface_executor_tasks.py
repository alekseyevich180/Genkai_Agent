"""Paper plan -> structures for vacancy, cluster, SAM, ALD and amorphous tasks, independent and chained.

Structure-only and offline: no energy model, network or skill script is used.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ase.build import molecule
from ase.constraints import FixAtoms
from ase.io import read, write
from click.testing import CliRunner
from pymatgen.core import Lattice, Structure

from genkai.cli import main as cli_main
from genkai.modeling.surface.executor import SurfaceExecutionBlocked, SurfaceExecutionOverrides, execute_surface_plan
from genkai.workflow.store import load_manifest
from genkai.workflows.paper_to_mlip import initialize_paper_to_mlip_run
from tests.modeling.surface_builders_helpers import methylphosphonic_acid, rutile

ROOT = Path(__file__).resolve().parents[2]
SAM_PAPER = ROOT / "tests" / "fixtures" / "surface_execution" / "sno2_sam_gas_relations.jsonl"
A_SNO2 = ROOT / "tests" / "amorphous" / "SnO2"
A_TIO2 = ROOT / "tests" / "amorphous" / "TiO2.vasp"

PT_CEO2 = {
    "materials": ["Pt/CeO2"],
    "surfaces": ["CeO2(111)"],
    "facets": ["CeO2(111) exposed surface"],
    "defects": ["oxygen vacancy"],
    "adsorbates": ["CO"],
    "active_sites": ["Pt site", "Ce site"],
    "clusters": ["Pt13 cluster"],
    "recommended_modeling_tasks": ["vacancy_landscape", "adsorbate_landscape", "surface_cluster_builder"],
}


def _plan(tmp_path: Path, extraction: dict | None = None, relations: Path | None = None):
    root = tmp_path / "run"
    if relations is None:
        relations = tmp_path / "relations.jsonl"
        relations.write_text(json.dumps({"id": "doc", "title": "t", "extraction": extraction}) + "\n", encoding="utf-8")
    initialize_paper_to_mlip_run(root, relations)
    manifest = load_manifest(root)
    plan = next(item for item in reversed(manifest.artifacts) if item.artifact_type == "modeling-plan")
    return root, plan


def _ceo2_bulk(tmp_path: Path) -> Path:
    path = tmp_path / "CeO2.cif"
    Structure.from_spacegroup("Fm-3m", Lattice.cubic(5.411), ["Ce", "O"], [[0, 0, 0], [0.25, 0.25, 0.25]]).to(filename=str(path))
    return path


def _sno2_bulk(tmp_path: Path) -> Path:
    path = tmp_path / "SnO2.cif"
    rutile("SnO2").to(filename=str(path))
    return path


def _frames(root: Path, artifact) -> list:
    return read(root / artifact.path, index=":")


def _report(root: Path, artifact) -> dict:
    return json.loads((root / artifact.metadata["execution_report"]).read_text(encoding="utf-8"))


def _roles(frames) -> dict[str, int]:
    roles: dict[str, int] = {}
    for frame in frames:
        roles[frame.info["role"]] = roles.get(frame.info["role"], 0) + 1
    return roles


@pytest.fixture(autouse=True)
def _quiet_matplotlib(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / ".matplotlib"))


def _pt_ceo2_overrides(bulk: Path, **extra) -> SurfaceExecutionOverrides:
    return SurfaceExecutionOverrides(
        bulk=bulk, surface_facet="(111)", molecule_name="CO", coverage_counts=(1,), patterns=("uniform",),
        vacancy_counts=(1,), vacancy_samples=2, **extra,
    )


def test_plan_tasks_build_independently_on_the_clean_slab(tmp_path: Path) -> None:
    root, plan = _plan(tmp_path, PT_CEO2)
    artifact = execute_surface_plan(plan, root, _pt_ceo2_overrides(_ceo2_bulk(tmp_path)))

    frames = _frames(root, artifact)
    roles = _roles(frames)
    assert roles["clean_slab"] == 1 and roles["vacancy_slab"] == 2
    assert roles["cluster_on_slab"] == 1 and roles["adsorbate_on_slab"] >= 1
    clean = frames[0]
    n_o = clean.get_chemical_symbols().count("O")
    n_fixed = len(clean.constraints[0].get_indices())
    for frame in frames[1:]:
        assert frame.info["built_on"] == "clean_slab:0"  # independent mode
        assert isinstance(frame.constraints[0], FixAtoms) and len(frame.constraints[0].get_indices()) == n_fixed
    vacancy = [f for f in frames if f.info["role"] == "vacancy_slab"]
    assert all(f.get_chemical_symbols().count("O") == n_o - 1 for f in vacancy)
    cluster = next(f for f in frames if f.info["role"] == "cluster_on_slab")
    assert cluster.get_chemical_symbols().count("Pt") == 13 and cluster.info["cluster_structure"] == "fcc"
    assert set(cluster.get_tags()[len(clean):]) == {2}

    report = _report(root, artifact)
    assert report["chain"] == {"enabled": False, "steps": []}
    assert report["resolution"]["inputs"]["surface_cluster_builder"]["cluster_atoms"] == {"value": 13, "source": "plan"}
    assert report["resolution"]["inputs"]["surface_cluster_builder"]["cluster_structures"]["source"] == "element_reference_state"
    assert artifact.metadata["calculator"] == "none" and artifact.metadata["chain"] is False


def test_chained_tasks_build_on_the_previous_structure(tmp_path: Path) -> None:
    root, plan = _plan(tmp_path, PT_CEO2)
    artifact = execute_surface_plan(plan, root, _pt_ceo2_overrides(_ceo2_bulk(tmp_path), chain=True))

    frames = _frames(root, artifact)
    by_role = {role: [f for f in frames if f.info["role"] == role] for role in _roles(frames)}
    n_o = frames[0].get_chemical_symbols().count("O")
    assert all(f.info["built_on"] == "clean_slab:0" for f in by_role["vacancy_slab"])
    assert all(f.info["built_on"] == "vacancy_landscape:0" for f in by_role["cluster_on_slab"])
    for adsorbed in by_role["adsorbate_on_slab"]:
        assert adsorbed.info["built_on"] == "surface_cluster_builder:0"
        symbols = adsorbed.get_chemical_symbols()
        assert symbols.count("Pt") == 13 and "C" in symbols and symbols.count("O") == n_o - 1 + symbols.count("C")
    # On the chained surface the plan's Pt sites exist, so no site symbol is dropped.
    assert _report(root, artifact)["resolution"]["inputs"]["site_symbols"]["value"] == ["Pt", "Ce"]
    steps = _report(root, artifact)["chain"]["steps"]
    assert [step["task"] for step in steps] == ["vacancy_landscape", "surface_cluster_builder", "adsorbate_landscape"]
    assert steps[-1]["next_step_uses"] is None


def test_accept_defaults_fills_numeric_choices_and_records_them(tmp_path: Path) -> None:
    root, plan = _plan(tmp_path, PT_CEO2)
    bulk = _ceo2_bulk(tmp_path)
    base = {"bulk": bulk, "surface_facet": "(111)", "molecule_name": "CO", "tasks": ("slab_generation", "vacancy_landscape", "adsorbate_landscape")}
    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(plan, root, SurfaceExecutionOverrides(**base))
    assert {"vacancy_counts", "coverage_counts"} <= set(blocked.value.missing)
    assert "--accept-defaults" in blocked.value.missing["vacancy_counts"]

    artifact = execute_surface_plan(plan, root, SurfaceExecutionOverrides(accept_defaults=True, vacancy_samples=1, **base))
    assert set(artifact.metadata["defaults_used"]) == {"vacancy_counts", "coverage_counts"}
    inputs = _report(root, artifact)["resolution"]["inputs"]
    assert inputs["vacancy_landscape"]["vacancy_counts"] == {"value": [1, 2], "source": "default"}
    assert inputs["coverage_counts"] == {"value": [1, 2], "source": "default"}
    codes = [check["code"] for check in _report(root, artifact)["validation"]["checks"]]
    assert "defaults_used" in codes


def _phosphonic_acid(tmp_path: Path) -> Path:
    path = tmp_path / "methylphosphonic_acid.xyz"
    write(path, methylphosphonic_acid())
    return path


def test_sam_task_builds_the_paper_anchor_and_rejects_a_mismatched_molecule(tmp_path: Path) -> None:
    root, plan = _plan(tmp_path, relations=SAM_PAPER)
    bulk = _sno2_bulk(tmp_path)
    sam = {"bulk": bulk, "surface_facet": "(110)", "binding_mode": "bidentate", "sam_counts": (1,), "tasks": ("slab_generation", "sam_functionalization")}

    acetic = tmp_path / "acetic_acid.xyz"
    write(acetic, molecule("CH3COOH"))
    with pytest.raises(SurfaceExecutionBlocked) as blocked:  # the paper says phosphonic; the file is a carboxylic acid
        execute_surface_plan(plan, root, SurfaceExecutionOverrides(sam_molecule=acetic, **sam))
    assert "phosphonic" in blocked.value.missing["sam_functionalization"]
    assert not (root / "stages" / "03_surface_structures").exists()

    artifact = execute_surface_plan(plan, root, SurfaceExecutionOverrides(sam_molecule=_phosphonic_acid(tmp_path), **sam))
    frames = _frames(root, artifact)
    sam_frames = [f for f in frames if f.info["role"] == "sam_on_slab"]
    assert len(sam_frames) == 1 and "P" in sam_frames[0].get_chemical_symbols()
    record = _report(root, artifact)["task_records"]["sam_functionalization"][0]
    assert record["anchor_group"]["kind"] == "phosphonic" and record["binding_mode"] == "bidentate"


def test_gas_adsorbs_on_the_sam_functionalized_surface_when_chained(tmp_path: Path) -> None:
    root, plan = _plan(tmp_path, relations=SAM_PAPER)
    artifact = execute_surface_plan(
        plan,
        root,
        SurfaceExecutionOverrides(
            bulk=_sno2_bulk(tmp_path), surface_facet="(110)", sam_molecule=_phosphonic_acid(tmp_path),
            binding_mode="bidentate", sam_counts=(1,), molecule_name="NO2", coverage_counts=(1,),
            patterns=("uniform",), chain=True,
        ),
    )
    adsorbed = [f for f in _frames(root, artifact) if f.info["role"] == "adsorbate_on_slab"]
    assert adsorbed
    for frame in adsorbed:
        assert frame.info["built_on"] == "sam_functionalization:0"
        assert {"P", "N"} <= set(frame.get_chemical_symbols())


@pytest.mark.parametrize(
    ("overlayer", "extra", "role"),
    [
        ("ALD TiO2 overlayer, 0.5 nm, conformal", {}, "amorphous_film_on_slab"),
        ("ALD TiO2 islands", {"island_atoms": 20}, "amorphous_island_on_slab"),
    ],
)
def test_ald_overlayer_from_the_paper(tmp_path: Path, overlayer: str, extra: dict, role: str) -> None:
    root, plan = _plan(tmp_path, {"materials": ["SnO2"], "surfaces": ["SnO2(110) surface"], "overlayers": [overlayer]})
    artifact = execute_surface_plan(
        plan,
        root,
        SurfaceExecutionOverrides(bulk=_sno2_bulk(tmp_path), surface_facet="(110)", amorphous=A_TIO2, **extra),
    )
    frames = [f for f in _frames(root, artifact) if f.info["role"] == role]
    assert frames and all("Ti" in f.get_chemical_symbols() for f in frames)
    inputs = _report(root, artifact)["resolution"]["inputs"]["ald_overlayer"]
    if not extra:
        assert inputs["ald_thickness"] == {"value": 5.0, "source": "plan"}
    codes = [issue["code"] for issue in _report(root, artifact)["validation"]["warnings"]]
    assert "amorphous_composition_mismatch" not in codes  # paper TiO2 matches the a-TiO2 file


def test_amorphous_material_is_the_base_surface_without_a_crystal(tmp_path: Path) -> None:
    root, plan = _plan(
        tmp_path,
        {"materials": ["amorphous SnO2 film"], "surfaces": ["a-SnO2 surface"], "adsorbates": ["H2"],
         "recommended_modeling_tasks": ["adsorbate_landscape"]},
    )
    artifact = execute_surface_plan(
        plan,
        root,
        SurfaceExecutionOverrides(
            amorphous=A_SNO2, amorphous_thickness=8.0, molecule_name="H2", coverage_counts=(1,),
            site_symbols=("Sn",), patterns=("uniform",),
        ),
    )
    frames = _frames(root, artifact)
    assert frames[0].info["role"] == "amorphous_slab"
    adsorbed = [f for f in frames if f.info["role"] == "adsorbate_on_slab"]
    assert adsorbed and all(f.info["built_on"] == "amorphous_slab:0" for f in adsorbed)
    assert "slab_generation" in artifact.metadata["skipped_tasks"]  # no crystal bulk was needed
    assert artifact.metadata["slab_source"] == "amorphous_slab"


def test_cli_forwards_the_new_task_options(tmp_path: Path) -> None:
    relations = tmp_path / "relations.jsonl"
    relations.write_text(
        json.dumps({"id": "doc", "title": "t", "extraction": {"materials": ["amorphous TiO2"], "surfaces": ["a-TiO2 surface"]}})
        + "\n",
        encoding="utf-8",
    )
    root = tmp_path / "run"
    runner = CliRunner()
    blocked = runner.invoke(
        cli_main, ["init", str(root), "--relations", str(relations), "--modeling-mode", "structure-only"]
    )
    assert blocked.exit_code == 2
    assert "amorphous" in blocked.output and "--accept-defaults" in blocked.output

    result = runner.invoke(
        cli_main,
        ["surface", "execute", "--run-root", str(root), "--amorphous", str(A_TIO2), "--accept-defaults"],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(next((root / "stages").glob("03_surface_structures*/execution_report.json")).read_text(encoding="utf-8"))
    assert report["resolution"]["inputs"]["amorphous_slab"]["amorphous_thickness"] == {"value": 10.0, "source": "default"}
