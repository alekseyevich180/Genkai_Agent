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

from genkai.modeling.surface.mlip import calculators
from genkai.modeling.surface.builders.amorphous_overlayer import (
    OverlayerSettings,
    film_lattice_matches,
    match_film_lattice,
    run_overlayer,
)
from genkai.modeling.surface.screening.amorphous_screen import (
    InterfaceSearchSettings,
    ModelSettings,
    SurfaceScreenSettings,
    screen_surfaces,
    search_interface,
)
from genkai.modeling.surface.builders.sam import SamBuilder, SamSettings, resolve_anchor_group
from genkai.modeling.surface.screening.sam_search import SamSearchSettings, equivalent_groups, run_sam_search
from genkai.modeling.surface.structure_io import read_molecule
from genkai.modeling.surface.builders.substrate import ensure_fixed_bottom, prepare_substrate

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

    from genkai.modeling.surface.builders.amorphous_slab import AmorphousSlabSettings, run_amorphous_slab

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
    from genkai.modeling.surface.screening import cluster_search
    from genkai.modeling.surface.builders.slab import vacuum_gap_angstrom

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
    from genkai.modeling.surface.screening import cluster_search

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


def test_cluster_search_skips_detached_trials_and_exports_extxyz(tmp_path, sno2_110) -> None:
    import optuna
    from ase.constraints import FixAtoms

    from genkai.modeling.surface.screening import cluster_search
    from genkai.modeling.surface.structure_io import components, label_components, write_frames

    # Unit test: select_best_trial prefers attached trials even if a detached trial has lower value.
    study = optuna.create_study(direction="minimize")
    t0 = study.ask()
    t0.set_user_attr("detached", True)
    t0.set_user_attr("structure", cluster_search.atoms_to_json(Atoms("Pt2", positions=[[0, 0, 0], [0, 0, 2.7]])))
    study.tell(t0, -99.0)
    t1 = study.ask()
    t1.set_user_attr("detached", False)
    t1.set_user_attr("structure", cluster_search.atoms_to_json(Atoms("Pt2", positions=[[0, 0, 0], [0, 0, 2.7]])))
    study.tell(t1, -2.5)
    best_trial, all_detached = cluster_search.select_best_trial(study)
    assert best_trial.number == t1.number and all_detached is False

    detached_study = optuna.create_study(direction="minimize")
    td = detached_study.ask()
    td.set_user_attr("detached", True)
    td.set_user_attr("structure", cluster_search.atoms_to_json(Atoms("Pt2", positions=[[0, 0, 0], [0, 0, 2.7]])))
    detached_study.tell(td, 1e6 + 7.5)
    fallback_trial, all_detached = cluster_search.select_best_trial(detached_study)
    assert fallback_trial.number == td.number and all_detached is True

    # End-to-end test: mlip_best_structure.extxyz & cluster_search_structures.extxyz keep FixAtoms and component.
    slab = label_components(sno2_110.atoms.copy(), "substrate")
    slab_path = write_frames(tmp_path / "slab.extxyz", [slab])
    cluster = Atoms("Pt4", positions=[[0, 0, 0], [2.7, 0, 0], [1.35, 2.34, 0], [1.35, 0.78, 2.2]])
    cluster_path = tmp_path / "Pt4.xyz"
    write(cluster_path, cluster)
    out_dir = tmp_path / "cs_out"

    code = cluster_search.main(
        [
            "--surface", str(slab_path), "--cluster", str(cluster_path), "--calculator", "none",
            "--n_trials", "4", "--seed", "7", "--selection_count", "2", "--top_pool_size", "4",
            "--top_pick_count", "2", "--tail_pick_per_bin", "0", "--output_dir", str(out_dir),
        ]
    )
    assert code == 0
    best_extxyz = out_dir / "mlip_output" / "mlip_best_structure.extxyz"
    ranked_extxyz = out_dir / "mlip_output" / "cluster_search_structures.extxyz"
    assert best_extxyz.is_file() and ranked_extxyz.is_file()
    best = read(best_extxyz)
    ranked = read(ranked_extxyz, index=":")
    assert len(ranked) >= 2
    assert np.allclose(best.positions, ranked[0].positions)
    expected_fixed = sorted(int(i) for c in slab.constraints if isinstance(c, FixAtoms) for i in c.index)
    for frame in (best, *ranked):
        actual_fixed = sorted(int(i) for c in frame.constraints if isinstance(c, FixAtoms) for i in c.index)
        assert actual_fixed == expected_fixed
        labels = components(frame)
        assert list(labels[: len(slab)]) == ["substrate"] * len(slab)
        assert list(labels[len(slab) :]) == ["cluster"] * len(cluster)


def test_cluster_search_funnel_anneal_multiseed_and_xy_bounds(tmp_path) -> None:
    import pandas as pd
    from ase.build import fcc111
    from ase.constraints import FixAtoms

    from genkai.modeling.surface.screening import cluster_search
    from genkai.modeling.surface.structure_io import components, label_components, write_frames

    # Small Cu(111) slab + 2 Pt4 isomers so EMT runs real forces and real MD anneal offline in ~1s.
    slab = fcc111("Cu", size=(2, 2, 3), vacuum=8.0)
    fixed_idx = sorted(a.index for a in slab if a.tag == 3)
    slab.set_constraint(FixAtoms(indices=fixed_idx))
    label_components(slab, "substrate")
    slab_path = write_frames(tmp_path / "cu_slab.extxyz", [slab])

    iso_3d = Atoms("Pt4", positions=[[0, 0, 0], [2.75, 0, 0], [1.38, 2.38, 0], [1.38, 0.79, 2.25]])
    iso_3d.info["seed_name"] = "Pt4_tetra"
    iso_2d = Atoms("Pt4", positions=[[0, 0, 0], [2.75, 0, 0], [1.38, 2.38, 0], [4.13, 2.38, 0]])
    iso_2d.info["seed_name"] = "Pt4_planar"
    seeds_path = write_frames(tmp_path / "Pt4_seeds.extxyz", [iso_3d, iso_2d])

    out_dir = tmp_path / "funnel_out"
    code = cluster_search.main(
        [
            "--surface", str(slab_path),
            "--cluster", str(seeds_path),
            "--calculator", "emt",
            "--placement_shape", "input",
            "--max_tilt", "60",
            "--x_range", "0,0.5",
            "--y_range", "0,0.5",
            "--n_trials", "4",
            "--screen_steps", "3",
            "--screen_fmax", "0.3",
            "--refine_top_k", "2",
            "--anneal_steps", "6",
            "--anneal_temperature", "400",
            "--anneal_snapshots", "2",
            "--max_steps", "8",
            "--fmax", "0.2",
            "--selection_count", "2",
            "--top_pool_size", "2",
            "--top_pick_count", "2",
            "--tail_pick_per_bin", "0",
            "--seed", "11",
            "--output_dir", str(out_dir),
        ]
    )
    assert code == 0

    mlip_dir = out_dir / "mlip_output"
    stage1_df = pd.read_csv(mlip_dir / "mlip_energy_table.csv")
    assert len(stage1_df) == 4
    assert "cluster_index" in stage1_df.columns
    assert set(stage1_df["cluster_index"].tolist()) <= {0, 1}
    assert (stage1_df["x_frac"] >= 0.0).all() and (stage1_df["x_frac"] <= 0.5 + 1e-9).all()
    assert (stage1_df["y_frac"] >= 0.0).all() and (stage1_df["y_frac"] <= 0.5 + 1e-9).all()

    refined_csv = mlip_dir / "mlip_refined_table.csv"
    assert refined_csv.is_file()
    refined_df = pd.read_csv(refined_csv)
    assert any(s == "direct" for s in refined_df["stage"])
    assert any(str(s).startswith("anneal_snap_") for s in refined_df["stage"])
    attached_energies = refined_df.loc[~refined_df["detached"], "energy"].tolist()
    assert attached_energies == sorted(attached_energies)

    best = read(mlip_dir / "mlip_best_structure.extxyz")
    ranked = read(mlip_dir / "cluster_search_structures.extxyz", index=":")
    assert len(ranked) >= 2
    assert np.allclose(best.positions, ranked[0].positions)
    for frame in (best, *ranked):
        actual_fixed = sorted(int(i) for c in frame.constraints if isinstance(c, FixAtoms) for i in c.index)
        assert actual_fixed == fixed_idx
        assert np.allclose(frame.positions[fixed_idx], slab.positions[fixed_idx], atol=1e-5)
        labels = components(frame)
        assert list(labels[: len(slab)]) == ["substrate"] * len(slab)
        assert list(labels[len(slab) :]) == ["cluster"] * 4

    # Mismatched stoichiometry across multi-frame cluster seeds must be rejected.
    bad_seeds = write_frames(tmp_path / "bad_seeds.extxyz", [iso_3d, Atoms("Pt3", positions=[[0, 0, 0], [2.7, 0, 0], [1.3, 2.3, 0]])])
    with pytest.raises(ValueError, match="same composition"):
        cluster_search.main(
            [
                "--surface", str(slab_path), "--cluster", str(bad_seeds), "--calculator", "none",
                "--n_trials", "2", "--selection_count", "1", "--top_pool_size", "2",
                "--top_pick_count", "1", "--tail_pick_per_bin", "0", "--output_dir", str(tmp_path / "bad_out"),
            ]
        )
