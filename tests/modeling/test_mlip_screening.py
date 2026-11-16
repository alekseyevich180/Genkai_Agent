"""MLIP-screening layer: calculators, constraint handling, SAM search, amorphous screening, island search.

Everything here runs with the mock calculator (``none``); no UMA model is loaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.io import read, write

from genkai.modeling.surface import calculators
from genkai.modeling.surface.amorphous_overlayer import (
    OverlayerSettings,
    film_lattice_matches,
    match_film_lattice,
    run_overlayer,
)
from genkai.modeling.surface.amorphous_screen import (
    InterfaceSearchSettings,
    ModelSettings,
    SurfaceScreenSettings,
    screen_surfaces,
    search_interface,
)
from genkai.modeling.surface.sam import SamBuilder, SamSettings, resolve_anchor_group
from genkai.modeling.surface.sam_search import SamSearchSettings, equivalent_groups, run_sam_search
from genkai.modeling.surface.structure_io import read_molecule
from genkai.modeling.surface.substrate import ensure_fixed_bottom, prepare_substrate

ROOT = Path(__file__).resolve().parents[2]
SNO2_BULK = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling" / "sno2_101" / "bulk_from_materials_project.cif"
EXAMPLES = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "examples"
A_SNO2 = ROOT / "tests" / "amorphous" / "SnO2"
A_TIO2 = ROOT / "tests" / "amorphous" / "TiO2.vasp"


@pytest.fixture(scope="module")
def sno2_110():
    return prepare_substrate(bulk=SNO2_BULK)


def test_mock_calculator_has_zero_forces_and_penalizes_overlap() -> None:
    calc = calculators.ContactMockCalculator()
    bonded = Atoms("SnO", positions=[[0, 0, 0], [0, 0, 2.05]], cell=[15, 15, 15], pbc=True)
    squeezed = Atoms("SnO", positions=[[0, 0, 0], [0, 0, 1.0]], cell=[15, 15, 15], pbc=True)
    bonded.calc = calc
    energy_bonded = bonded.get_potential_energy()
    assert np.allclose(bonded.get_forces(), 0.0)
    squeezed.calc = calculators.ContactMockCalculator()
    assert squeezed.get_potential_energy() > energy_bonded
    assert calculators.evidence_for("none") == "mock"


def test_unavailable_uma_task_head_fails_before_loading_a_model() -> None:
    tasks = calculators.available_uma_tasks()
    if tasks is None or "oc22" in tasks:
        pytest.skip("needs a fairchem without the oc22 task head")
    with pytest.raises(ValueError, match="oc22"):
        calculators.validate_uma_task("oc22")
    calculators.validate_uma_task(tasks[0])


def test_ensure_fixed_bottom_keeps_file_constraints_and_fixes_cif_slabs(tmp_path, sno2_110) -> None:
    write(tmp_path / "slab.cif", sno2_110.atoms)
    fixed, source = ensure_fixed_bottom(read(tmp_path / "slab.cif"), 0.5)
    assert source.startswith("reapplied") and len(fixed.constraints[0].index) > 0
    kept, source = ensure_fixed_bottom(sno2_110.atoms, 0.5)
    assert source == "file"
    untouched, source = ensure_fixed_bottom(read(tmp_path / "slab.cif"), 0.0)
    assert source.startswith("none") and not untouched.constraints


def test_film_lattice_matches_are_sorted_and_start_with_the_best(sno2_110) -> None:
    from genkai.modeling.surface.structure_io import read_structure

    bulk, _ = read_structure(A_TIO2)  # a-SnO2 has a single match on this cell within 5 % / 600 A^2
    matches = film_lattice_matches(sno2_110.atoms, bulk, 0.05, 600.0)
    assert len(matches) >= 2
    areas = [round(m.area_A2, 3) for m in matches]
    assert areas == sorted(areas)
    best = match_film_lattice(sno2_110.atoms, bulk, 0.05, 600.0)
    assert best.area_A2 == pytest.approx(matches[0].area_A2)


def test_translation_equivalent_sites_on_a_crystal_but_not_on_an_amorphous_slab(tmp_path, sno2_110) -> None:
    molecule, _ = read_molecule(EXAMPLES / "4-acid.vasp")
    group = resolve_anchor_group(molecule)
    builder = SamBuilder(sno2_110.atoms, molecule, group, SamSettings("monodentate"))
    equivalents = equivalent_groups(builder.substrate, builder.groups, builder.groups[0], 0.3, 4.5)
    assert len(equivalents) == len(builder.groups) == 6  # every Sn5c of rutile (110)
    assert tuple(equivalents[0][0]) == tuple(builder.groups[0])

    from genkai.modeling.surface.amorphous_slab import AmorphousSlabSettings, run_amorphous_slab

    slab = run_amorphous_slab(A_TIO2, AmorphousSlabSettings(thickness=11.84, repeat_xy=(1, 1)), tmp_path / "a", export=())
    amorphous = prepare_substrate(surface=slab.sample_paths[0])
    abuilder = SamBuilder(amorphous.atoms, molecule, group, SamSettings("monodentate"))
    if len(abuilder.groups) > 1:
        aeq = equivalent_groups(abuilder.substrate, abuilder.groups, abuilder.groups[0], 0.3, 4.5)
        assert len(aeq) == 1  # only the reference itself


def test_sam_search_ranks_placements_and_copies_onto_equivalent_sites(tmp_path, sno2_110) -> None:
    search = SamSearchSettings(n_trials=6, top_k=2, screen_steps=2, max_steps=2, coverage_counts=(1, 2, 3))
    result = run_sam_search(sno2_110, EXAMPLES / "4-acid.vasp", SamSettings("monodentate"), search, tmp_path)
    manifest = result.manifest
    assert manifest["energies_meaningful"] is False and manifest["evidence_level"] == "mock"
    roles = [frame.info["role"] for frame in result.frames]
    assert roles[0] == "clean_slab_relaxed" and roles.count("sam_single_ranked") == 2 and roles.count("sam_coverage") == 2
    for frame in result.frames:
        assert len(frame.constraints[0].index) == len(sno2_110.atoms.constraints[0].index)
    covered = [c for c in manifest["coverage"] if "error" not in c]
    assert [c["requested_count"] for c in covered] == [2, 3]
    assert all(c["binding_retained"] for c in covered)
    layer = result.frames[-1]
    assert sorted(set(layer.arrays["fragment_id"].tolist())) == [0, 1, 2, 3]
    sites = [g[0] for g in covered[-1]["site_groups"]]
    assert len(set(sites)) == 3


def test_amorphous_surface_screening_keeps_windows_stoichiometric(tmp_path) -> None:
    settings = SurfaceScreenSettings(periods=2, samples=3)
    manifest = screen_surfaces(A_TIO2, settings, ModelSettings(max_steps=2), tmp_path, export=())
    samples = manifest["samples"]
    assert len(samples) == 3
    assert all(s["stoichiometric"] and s["surface_energy_eV_A2"] is not None for s in samples)
    gammas = [s["surface_energy_eV_A2"] for s in samples]
    assert gammas == sorted(gammas) and [s["rank"] for s in samples] == [1, 2, 3]
    assert manifest["energies_meaningful"] is False


def test_interface_search_ranks_candidates_by_adhesion(tmp_path, sno2_110) -> None:
    settings = InterfaceSearchSettings(thickness=5.0, n_matches=2, n_trials=3, screen_steps=1)
    manifest = search_interface(sno2_110, A_TIO2, settings, ModelSettings(max_steps=1), tmp_path, export=())
    candidates = manifest["candidates"]
    assert [c["candidate"].split("_")[0] for c in candidates] == ["strain", "strain"]
    adhesion = [c["W_adh_eV_A2"] for c in candidates]
    assert adhesion == sorted(adhesion, reverse=True)
    frames = read(tmp_path / "amorphous_interfaces_ranked.extxyz", ":")
    for frame in frames:
        film = frame.arrays["ald_role"] == 1
        assert len(frame.constraints[0].index) > 0
        assert frame.positions[film, 2].min() > frame.positions[~film, 2].max()


def test_cluster_search_makes_room_above_the_slab_for_large_clusters(tmp_path) -> None:
    from genkai.modeling.surface import cluster_search
    from genkai.modeling.surface.slab import vacuum_gap_angstrom

    particle = ROOT / "tests/fixtures/archives/generated/s41563-025-02134-9_surface_fullrun/modeling/structures/Ru_hcp_r7.xyz"
    slab_file = EXAMPLES / "CeO2 (1 1 1).cif"  # c = 24.7 A, too short for a ~12 A tall particle plus gap
    code = cluster_search.main(
        [
            "--surface", str(slab_file), "--cluster", str(particle), "--calculator", "none", "--n_trials", "4",
            "--seed", "2", "--selection_count", "2", "--top_pool_size", "4", "--top_pick_count", "2",
            "--tail_pick_per_bin", "0", "--min_vacuum", "10", "--output_dir", str(tmp_path),
        ]
    )
    assert code == 0
    for path in (tmp_path / "mlip_output").glob("0*_trial_*.cif"):
        structure = read(path)
        assert structure.cell.lengths()[2] > 24.8
        assert vacuum_gap_angstrom(structure) >= 10.0 - 1e-6


def test_island_files_feed_the_cluster_placement_search(tmp_path, sno2_110) -> None:
    from genkai.modeling.surface import cluster_search

    ald = run_overlayer(sno2_110, A_TIO2, OverlayerSettings("partial", island_atoms=20), tmp_path / "ald", export=())
    island = Path(ald.manifest["files"]["islands"][0])
    slab_file = Path(ald.manifest["files"]["substrate_slab"])
    assert len(read(island)) == 20 and len(read(slab_file)) == len(ald.frames[0])
    code = cluster_search.main(
        [
            "--surface", str(slab_file), "--cluster", str(island), "--calculator", "none",
            "--placement_shape", "input", "--max_tilt", "60", "--n_trials", "6", "--seed", "1",
            "--selection_count", "2", "--top_pool_size", "4", "--top_pick_count", "2", "--tail_pick_per_bin", "0",
            "--output_dir", str(tmp_path / "search"),
        ]
    )
    assert code == 0
    config = json.loads((tmp_path / "search" / "run_config.json").read_text(encoding="utf-8"))
    assert config["max_tilt"] == 60.0 and config["placement_shape"] == "input"
    assert len(list((tmp_path / "search" / "mlip_output").glob("0*_trial_*.cif"))) == 2
