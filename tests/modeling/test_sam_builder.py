from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase.build import fcc111, molecule
from ase.io import read, write

from genkai.modeling.surface.builders import sam
from genkai.modeling.surface.builders.sam import SamBuildError, SamSettings, detect_anchor_groups, resolve_anchor_group, run_sam
from genkai.modeling.surface.builders.sites import classify_hollow
from genkai.modeling.surface.builders.substrate import prepare_substrate

from .surface_builders_helpers import (
    carboxymethylphosphonic_acid,
    in_box_split_across_face,
    methylphosphonic_acid,
    rutile,
)


@pytest.fixture(scope="module")
def inputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("sam_inputs")
    rutile("SnO2").to(filename=str(root / "SnO2_bulk.cif"))
    write(root / "mpa.cif", in_box_split_across_face(methylphosphonic_acid()))
    write(root / "cmpa.xyz", carboxymethylphosphonic_acid())
    write(root / "CH3SH.cif", molecule("CH3SH"))
    write(root / "Au111.cif", fcc111("Au", (3, 3, 4), vacuum=10.0, periodic=True))
    return root


@pytest.fixture(scope="module")
def sno2_substrate(inputs):
    return prepare_substrate(bulk=inputs / "SnO2_bulk.cif")


def test_anchor_groups_are_detected_by_bonding() -> None:
    kinds = sorted(g.kind for g in detect_anchor_groups(carboxymethylphosphonic_acid()))
    assert kinds == ["carboxylic", "phosphonic"]
    (thiol,) = detect_anchor_groups(molecule("CH3SH"))
    assert thiol.kind == "thiol" and len(thiol.acidic_h) == 1
    (phosphonic,) = detect_anchor_groups(methylphosphonic_acid())
    assert phosphonic.anchor_atoms[:2] == (3, 4)  # P-OH oxygens before P=O
    assert len(phosphonic.acidic_h) == 2


def test_several_anchor_groups_must_be_chosen_explicitly() -> None:
    with pytest.raises(SamBuildError, match="Several anchor groups"):
        resolve_anchor_group(carboxymethylphosphonic_acid())
    assert resolve_anchor_group(carboxymethylphosphonic_acid(), "phosphonic").kind == "phosphonic"
    with pytest.raises(SamBuildError, match="needs --anchor-kind"):
        resolve_anchor_group(methylphosphonic_acid(), anchor_atoms=[3])


def test_most_stable_facet_is_the_default_substrate(sno2_substrate) -> None:
    assert sno2_substrate.record["facet"] == [1, 1, 0]
    assert sno2_substrate.record["facet_source"] == "stable_facet_registry"


def test_bidentate_phosphonate_on_sno2_110(tmp_path, inputs, sno2_substrate) -> None:
    result = run_sam(sno2_substrate, inputs / "mpa.cif", SamSettings("bidentate", coverage_counts=(1, 2)), tmp_path)
    slab = sno2_substrate.atoms
    assert [f.info["role"] for f in result.frames] == ["clean_slab", "sam_on_slab", "sam_on_slab"]
    build = result.manifest["builds"][0]
    (placed,) = build["molecules"]
    assert [b["site_symbol"] for b in placed["bonds"]] == ["Sn", "Sn"]
    assert all(abs(b["distance_A"] - b["target_A"]) <= 0.35 for b in placed["bonds"])
    assert [h["action"] for h in placed["h_handling"]] == ["transferred", "transferred"]
    assert build["min_nonbonded_contact_ratio"] >= sam.CLASH_FRACTION

    frame = result.frames[1]
    # Composition is conserved: both acidic H moved to surface O.
    assert len(frame) == len(slab) + 10
    assert sorted(frame.constraints[0].index) == sorted(slab.constraints[0].index)
    assert set(frame.get_tags()[len(slab):]) == {2}
    roles = frame.arrays["sam_role"]
    for h_index in np.flatnonzero(roles == 3):
        oxygen = int(np.argmin(np.where(np.arange(len(frame)) < len(slab), frame.get_distances(h_index, range(len(frame)), mic=True), np.inf)))
        assert frame.get_chemical_symbols()[oxygen] == "O"
        assert frame.get_distance(h_index, oxygen, mic=True) == pytest.approx(0.98, abs=1e-6)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["molecule"]["format"] == "cif"
    assert manifest["evidence_level"] == "heuristic"
    assert read(result.structures_path, ":")[2].info["molecule_count"] == 2


def test_capacity_and_impossible_modes_are_reported(tmp_path, inputs, sno2_substrate) -> None:
    result = run_sam(sno2_substrate, inputs / "mpa.cif", SamSettings("bidentate", coverage_counts=(3,)), tmp_path)
    assert result.manifest["validation"]["failed_counts"] == [3]
    assert "Placed 2 of 3" in result.manifest["builds"][0]["error"]
    with pytest.raises(SamBuildError, match="no tridentate site"):
        run_sam(sno2_substrate, inputs / "mpa.cif", SamSettings("tridentate"), tmp_path / "tri")


def test_thiolate_in_fcc_hollow_on_au111(tmp_path, inputs) -> None:
    substrate = prepare_substrate(surface=inputs / "Au111.cif")
    assert substrate.record["constraints_source"].startswith("reapplied")
    settings = SamSettings("fcc", coverage_counts=(1, 3), tilt_deg=30.0)
    result = run_sam(substrate, inputs / "CH3SH.cif", settings, tmp_path)
    assert result.manifest["binding"]["acidic_h_policy"] == "remove"
    assert result.manifest["molecule"]["deposited_formula"] == "CH3S"
    dense = result.manifest["builds"][-1]
    assert dense["placed_count"] == 3
    # Molecule-molecule repulsion uses van der Waals radii, so chains do not interpenetrate.
    assert dense["min_intermolecular_distance_A"]["H-H"] >= 1.8
    for build in result.manifest["builds"]:
        assert build["error"] is None
        for placed in build["molecules"]:
            assert [b["site_symbol"] for b in placed["bonds"]] == ["Au"] * 3
            assert all(b["distance_A"] == pytest.approx(b["target_A"], abs=0.1) for b in placed["bonds"])
            assert placed["tilt_deg"] == pytest.approx(30.0, abs=3.0)
            assert classify_hollow(substrate.atoms, placed["site_group"]) == "fcc"


def test_thin_slab_without_bulk_like_interior_falls_back_to_exposed_sites(tmp_path) -> None:
    # The skill example is two O-Ce-O trilayers: every Ce is 7-fold, none is "undercoordinated".
    example = Path(__file__).resolve().parents[2] / "agents/Agent/skills/surface-modeling/examples"
    substrate = prepare_substrate(surface=example / "CeO2 (1 1 1).cif")
    result = run_sam(substrate, example / "4-acid.vasp", SamSettings("bidentate", coverage_counts=(1,)), tmp_path)
    assert result.manifest["binding"]["site_selection"].startswith("exposed only")
    assert result.manifest["validation"]["warnings"][-1]["code"] == "sites_not_undercoordinated"
    (placed,) = result.manifest["builds"][0]["molecules"]
    assert [b["site_symbol"] for b in placed["bonds"]] == ["Ce", "Ce"]


def test_density_is_converted_to_an_integer_count(tmp_path, inputs, sno2_substrate) -> None:
    result = run_sam(sno2_substrate, inputs / "mpa.cif", SamSettings("monodentate", coverage_counts=None, density_per_nm2=1.5), tmp_path)
    coverage = result.manifest["coverage"]
    assert coverage["source"] == "density"
    assert coverage["rounded_count"] == round(1.5 * coverage["surface_area_nm2"])


def test_cli_writes_structures_and_blocks_ambiguous_molecules(tmp_path, inputs, capsys) -> None:
    common = ["--bulk", str(inputs / "SnO2_bulk.cif"), "--binding-mode", "monodentate", "--counts", "1"]
    assert sam.main([*common, "--molecule", str(inputs / "cmpa.xyz"), "--output-dir", str(tmp_path / "a")]) == 2
    assert "Several anchor groups" in capsys.readouterr().err
    code = sam.main(
        [*common, "--molecule", str(inputs / "cmpa.xyz"), "--anchor-kind", "phosphonic", "--export", "cif,vasp", "--output-dir", str(tmp_path / "b")]
    )
    assert code == 0
    assert (tmp_path / "b" / "sam_structures.extxyz").is_file()
    assert (tmp_path / "b" / "exports" / "sam_001.vasp").is_file()
