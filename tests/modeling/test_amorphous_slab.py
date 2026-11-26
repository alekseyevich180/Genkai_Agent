from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ase.data import covalent_radii
from ase.io import write
from ase.neighborlist import neighbor_list

from genkai.modeling.surface.builders import amorphous_slab as aslab
from genkai.modeling.surface.builders.amorphous_overlayer import (
    OverlayerBuildError,
    OverlayerSettings,
    pair_reference_distances,
    run_overlayer,
)
from genkai.modeling.surface.builders.sam import SamSettings, run_sam
from genkai.modeling.surface.structure_io import read_structure
from genkai.modeling.surface.builders.substrate import prepare_substrate

ROOT = Path(__file__).resolve().parents[2]
A_SNO2 = ROOT / "tests" / "amorphous" / "SnO2"
A_TIO2 = ROOT / "tests" / "amorphous" / "TiO2.vasp"
EXAMPLES = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "examples"
LEGACY_SLAB = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling" / "sno2_101" / "stable_surface_slab.vasp"

pytestmark = pytest.mark.skipif(not A_SNO2.is_file() or not A_TIO2.is_file(), reason="amorphous test cells missing")


def _min_ratio(atoms) -> float:
    distances = atoms.get_all_distances(mic=True)
    radii = covalent_radii[atoms.numbers]
    ratio = distances / (radii[:, None] + radii[None, :])
    np.fill_diagonal(ratio, np.inf)
    return float(ratio.min())


def _tilted_copy(path: Path, tmp_path: Path):
    """Same amorphous structure described with a tilted c (c + a is also a lattice vector)."""
    bulk, _ = read_structure(path)
    tilted = bulk.copy()
    cell = bulk.cell.array.copy()
    cell[2] = cell[2] + cell[0]
    tilted.set_cell(cell, scale_atoms=False)
    tilted.wrap()
    target = tmp_path / "tilted.extxyz"
    write(target, tilted)
    return bulk, target


def test_pure_amorphous_slab_is_seamless_fixed_and_has_vacuum(tmp_path) -> None:
    settings = aslab.AmorphousSlabSettings(thickness=8.0, samples=2)
    result = aslab.run_amorphous_slab(A_SNO2, settings, tmp_path)
    bulk, _ = read_structure(A_SNO2)
    assert len(result.frames) == 2 and len(result.sample_paths) == 2
    windows = {sample["z_window_start_A"] for sample in result.manifest["samples"]}
    assert len(windows) == 2  # different cuts, different surfaces
    for slab, report in zip(result.frames, result.manifest["samples"]):
        assert np.allclose(sorted(slab.cell.lengths()[:2]), sorted(bulk.cell.lengths()[:2]))
        assert report["vacuum_above_A"] == pytest.approx(15.0, abs=1e-6)
        fixed = slab.constraints[0].index
        free = np.setdiff1d(np.arange(len(slab)), fixed)
        assert len(fixed) > 0 and slab.positions[fixed, 2].max() < slab.positions[free, 2].max()
        assert set(np.flatnonzero(slab.get_tags() == 0)) == set(fixed)
        # Exact in-plane periodicity: no contact shorter than in the bulk cell itself.
        assert _min_ratio(slab) >= _min_ratio(bulk) - 1e-6
        assert report["composition"]["reference_anion_to_cation_ratio"] == 2.0


def test_tilted_amorphous_cell_gives_an_undistorted_slab(tmp_path) -> None:
    bulk, tilted = _tilted_copy(A_TIO2, tmp_path)
    result = aslab.run_amorphous_slab(tilted, aslab.AmorphousSlabSettings(thickness=8.0), tmp_path / "out")
    assert _min_ratio(result.frames[0]) >= _min_ratio(bulk) - 1e-6


def test_amorphous_slab_is_a_valid_substrate_for_sam(tmp_path) -> None:
    slab_result = aslab.run_amorphous_slab(A_TIO2, aslab.AmorphousSlabSettings(thickness=8.0), tmp_path / "slab")
    substrate = prepare_substrate(surface=slab_result.sample_paths[0])
    assert substrate.record["constraints_source"] == "file"
    result = run_sam(substrate, EXAMPLES / "4-acid.vasp", SamSettings("monodentate", coverage_counts=(1,)), tmp_path / "sam")
    (placed,) = result.manifest["builds"][0]["molecules"]
    assert placed["bonds"][0]["site_symbol"] == "Ti"


def test_amorphous_slab_cif_gets_its_bottom_fixed_again(tmp_path) -> None:
    slab_result = aslab.run_amorphous_slab(A_SNO2, aslab.AmorphousSlabSettings(thickness=8.0), tmp_path / "slab")
    write(tmp_path / "aslab.cif", slab_result.frames[0])  # CIF drops FixAtoms
    substrate = prepare_substrate(surface=tmp_path / "aslab.cif")
    atoms = substrate.atoms
    fixed = atoms.constraints[0].index
    assert substrate.record["constraints_source"].startswith("reapplied")
    assert len(fixed) > 0 and atoms.positions[fixed, 2].max() < atoms.positions[:, 2].max()


def test_slab_without_discrete_layers_is_fixed_by_height() -> None:
    from ase import Atoms

    from genkai.modeling.surface.builders.slab import SlabSettings
    from genkai.modeling.surface.builders.substrate import apply_slab_convention

    # z spaced 0.1 A apart: every gap is below the 0.3 A layer tolerance, i.e. a single "layer".
    column = Atoms("O40", positions=[(0.0, 0.0, 0.1 * k) for k in range(40)], cell=[10, 10, 30], pbc=True)
    fixed_slab, source = apply_slab_convention(column, SlabSettings())
    assert "no discrete layers" in source
    fixed = fixed_slab.constraints[0].index
    assert len(fixed) == 20 and fixed_slab.positions[fixed, 2].max() < 2.0


def test_full_film_on_hexagonal_facet_falls_back_to_cut_with_repaired_seams(tmp_path) -> None:
    substrate = prepare_substrate(surface=EXAMPLES / "CeO2 (1 1 1).cif")
    result = run_overlayer(substrate, A_TIO2, OverlayerSettings("full", thickness=5.0), tmp_path)
    manifest = result.manifest
    assert manifest["lattice"]["film_fit"] == "cut"
    assert manifest["validation"]["notes"] and not manifest["validation"]["issues"]
    clean, film = result.frames
    assert np.allclose(film.cell.array[:2], clean.cell.array[:2])
    overlayer = film[np.flatnonzero(film.arrays["ald_role"] == 1)]
    overlayer.pbc = [True, True, False]
    reference = pair_reference_distances(read_structure(A_TIO2)[0])
    distances = overlayer.get_all_distances(mic=True)
    symbols = overlayer.get_chemical_symbols()
    for i in range(len(overlayer)):
        for j in range(i + 1, len(overlayer)):
            assert distances[i, j] >= 0.85 * reference[(symbols[i], symbols[j])] - 1e-9
    gap = overlayer.positions[:, 2].min() - clean.positions[:, 2].max()
    assert gap == pytest.approx(2.0, abs=1e-6)
    with pytest.raises(OverlayerBuildError, match="No in-plane supercell match"):
        run_overlayer(substrate, A_TIO2, OverlayerSettings("full", thickness=5.0, film_fit="strain"), tmp_path / "s")


def test_strained_film_from_tilted_amorphous_cell_is_not_sheared(tmp_path) -> None:
    rutile = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling" / "sno2_101" / "bulk_from_materials_project.cif"
    substrate = prepare_substrate(bulk=rutile)
    bulk, tilted = _tilted_copy(A_SNO2, tmp_path)
    result = run_overlayer(substrate, tilted, OverlayerSettings("full", thickness=6.0, film_fit="strain"), tmp_path / "out")
    film = result.frames[1]
    overlayer = film[np.flatnonzero(film.arrays["ald_role"] == 1)]
    overlayer.pbc = [True, True, False]
    # Up to the in-plane strain (<= 5 %) the film keeps the bulk's shortest contacts.
    assert _min_ratio(overlayer) >= 0.94 * _min_ratio(bulk)


def test_legacy_slab_with_tilted_c_is_normalized_without_changing_bonds() -> None:
    from ase.io import read

    raw = read(LEGACY_SLAB)
    substrate = prepare_substrate(surface=LEGACY_SLAB)
    assert substrate.record["cell_normalized"] is True
    assert "slab_cell_normalized" in {w.code for w in substrate.warnings}
    cell = substrate.atoms.cell.array
    assert np.abs(cell[2, :2]).max() < 1e-8 and np.abs(cell[:2, 2]).max() < 1e-8
    before = np.sort(neighbor_list("d", raw, 6.0))
    after = np.sort(neighbor_list("d", substrate.atoms, 6.0))
    assert len(before) == len(after) and np.allclose(before, after, atol=1e-8)


def test_amorphous_slab_stoichiometric_and_periods_options(tmp_path) -> None:
    # By integer periods: every clean cut is strictly stoichiometric (O:Ti = 2.0).
    res_periods = aslab.run_amorphous_slab(
        A_TIO2, aslab.AmorphousSlabSettings(periods=2, stoichiometric=True, samples=2), tmp_path / "periods", export=()
    )
    assert len(res_periods.frames) == 2
    for report in res_periods.manifest["samples"]:
        assert report["composition"]["stoichiometric"] is True
        assert report["composition"]["anion_to_cation_ratio"] == pytest.approx(2.0, abs=1e-6)

    # With arbitrary thickness + stoichiometric=True: snaps to a stoichiometric cut instead of O176Ti96.
    res_stoich = aslab.run_amorphous_slab(
        A_TIO2, aslab.AmorphousSlabSettings(thickness=8.0, stoichiometric=True, samples=2), tmp_path / "stoich", export=()
    )
    assert len(res_stoich.frames) == 2
    for report in res_stoich.manifest["samples"]:
        assert report["composition"]["stoichiometric"] is True
        assert report["isolated_atoms_removed"] == 0

    with pytest.raises(OverlayerBuildError):
        aslab.AmorphousSlabSettings(thickness=8.0, periods=2)
    with pytest.raises(OverlayerBuildError):
        aslab.AmorphousSlabSettings()
