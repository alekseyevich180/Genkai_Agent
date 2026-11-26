from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from ase.data import covalent_radii

from genkai.modeling.surface.builders import amorphous_overlayer as ald
from genkai.modeling.surface.builders.amorphous_overlayer import OverlayerBuildError, OverlayerSettings, run_overlayer
from genkai.modeling.surface.builders.substrate import prepare_substrate

from .surface_builders_helpers import rutile

AMORPHOUS = Path(__file__).resolve().parents[1] / "amorphous"
A_SNO2 = AMORPHOUS / "SnO2"  # extension-less POSCAR supplied by the user
A_TIO2 = AMORPHOUS / "TiO2.vasp"

pytestmark = pytest.mark.skipif(not A_SNO2.is_file() or not A_TIO2.is_file(), reason="amorphous test cells missing")


@pytest.fixture(scope="module")
def substrates(tmp_path_factory):
    root = tmp_path_factory.mktemp("ald_inputs")
    built = {}
    for formula in ("SnO2", "TiO2"):
        rutile(formula).to(filename=str(root / f"{formula}.cif"))
        built[formula] = prepare_substrate(bulk=root / f"{formula}.cif")
    return built


def _min_ratio(atoms, indices) -> float:
    part = atoms[list(indices)]
    distances = part.get_all_distances(mic=True)
    radii = covalent_radii[part.numbers]
    ratio = distances / (radii[:, None] + radii[None, :])
    np.fill_diagonal(ratio, np.inf)
    return float(ratio.min())


def test_full_film_is_periodic_strained_and_placed_on_the_stable_facet(tmp_path, substrates) -> None:
    substrate = substrates["SnO2"]
    assert substrate.record["facet_source"] == "stable_facet_registry"
    result = run_overlayer(substrate, A_SNO2, OverlayerSettings("full", thickness=6.0), tmp_path)
    manifest = result.manifest
    assert manifest["amorphous"]["format"].startswith("vasp")
    assert manifest["lattice"]["max_abs_strain"] <= 0.05
    clean, film = result.frames
    assert clean.info["role"] == "clean_slab" and film.info["role"] == "amorphous_film_on_slab"
    n_slab = len(clean)
    assert np.allclose(film.cell.array[:2], clean.cell.array[:2])
    overlayer = np.flatnonzero(film.arrays["ald_role"] == 1)
    assert set(film.get_tags()[overlayer]) == {2}
    assert sorted(film.constraints[0].index) == sorted(clean.constraints[0].index)
    gap = film.positions[overlayer, 2].min() - clean.positions[:, 2].max()
    assert gap == pytest.approx(2.0, abs=1e-6)
    # No seam: contacts inside the strained film stay close to those of the bulk cell.
    bulk = ald.read_structure(A_SNO2)[0]
    assert _min_ratio(film, overlayer) >= 0.9 * _min_ratio(bulk, range(len(bulk)))
    sample = manifest["samples"][0]
    assert sample["composition"]["reference_anion_to_cation_ratio"] == 2.0
    assert sample["min_interface_contact_ratio"] >= ald.CLASH_FRACTION
    assert len(film) - n_slab == sample["composition"]["n_atoms"]


def test_partial_coverage_island_is_isolated_from_its_images(tmp_path, substrates) -> None:
    settings = OverlayerSettings("partial", island_atoms=30, island_separation=8.0, samples=2)
    result = run_overlayer(substrates["TiO2"], A_TIO2, settings, tmp_path)
    assert len(result.frames) == 3
    for sample in result.manifest["samples"]:
        assert sample["composition"]["n_atoms"] == 30
        assert sample["min_gap_to_periodic_image_A"] >= 8.0
        assert 0.0 < sample["footprint_fraction"] < 0.5
    island_frame = result.frames[1]
    island = np.flatnonzero(island_frame.arrays["ald_role"] == 1)
    slab_top = result.frames[0].positions[:, 2].max()
    assert island_frame.positions[island, 2].min() - slab_top == pytest.approx(2.0, abs=1e-6)


def test_invalid_overlayer_inputs_are_rejected(tmp_path, substrates) -> None:
    with pytest.raises(OverlayerBuildError, match="thickness"):
        OverlayerSettings("full")
    with pytest.raises(OverlayerBuildError, match="exactly one"):
        OverlayerSettings("partial", island_atoms=10, island_radius=5.0)
    slab_file = tmp_path / "slab.extxyz"
    substrates["SnO2"].atoms.write(slab_file)
    with pytest.raises(OverlayerBuildError, match="empty gap"):
        run_overlayer(substrates["SnO2"], slab_file, OverlayerSettings("full", thickness=5.0), tmp_path / "x")
    # Only an explicit strain fit refuses; the default (auto) falls back to a cut film.
    with pytest.raises(OverlayerBuildError, match="No in-plane supercell match"):
        run_overlayer(
            substrates["SnO2"],
            A_SNO2,
            OverlayerSettings("full", thickness=5.0, max_strain=0.001, max_area=150.0, film_fit="strain"),
            tmp_path / "y",
        )


def test_cli_partial_coverage_on_explicit_facet(tmp_path) -> None:
    rutile("SnO2").to(filename=str(tmp_path / "SnO2.cif"))
    code = ald.main(
        [
            "--bulk", str(tmp_path / "SnO2.cif"),
            "--facet", "101",
            "--amorphous", str(A_SNO2),
            "--coverage", "partial",
            "--island-radius", "4.5",
            "--output-dir", str(tmp_path / "out"),
        ]
    )
    assert code == 0
    import json

    manifest = json.loads((tmp_path / "out" / "ald_manifest.json").read_text(encoding="utf-8"))
    assert manifest["substrate"]["facet"] == [1, 0, 1]
    assert manifest["substrate"]["facet_source"] == "explicit"
    assert (tmp_path / "out" / "exports" / "ald_001.cif").is_file()


def test_partial_coverage_max_atoms_guard_and_large_cell_warning(tmp_path, substrates, monkeypatch) -> None:
    # Auto-repeat for a 20-atom island with 8 A separation produces far more than 50 atoms.
    with pytest.raises(OverlayerBuildError, match="max_atoms"):
        run_overlayer(
            substrates["TiO2"],
            A_TIO2,
            OverlayerSettings("partial", island_atoms=20, island_separation=8.0, max_atoms=50),
            tmp_path / "blocked",
            export=(),
        )

    # CLI --max-atoms also exits cleanly with code 2.
    rutile("SnO2").to(filename=str(tmp_path / "SnO2.cif"))
    code = ald.main(
        [
            "--bulk", str(tmp_path / "SnO2.cif"),
            "--amorphous", str(A_SNO2),
            "--coverage", "partial",
            "--island-atoms", "20",
            "--max-atoms", "50",
            "--output-dir", str(tmp_path / "cli_blocked"),
        ]
    )
    assert code == 2

    # When total atoms exceed LARGE_SYSTEM_ATOM_WARNING, manifest records a clear note.
    monkeypatch.setattr(ald, "LARGE_SYSTEM_ATOM_WARNING", 100)
    result = run_overlayer(
        substrates["TiO2"],
        A_TIO2,
        OverlayerSettings("partial", island_atoms=20, island_separation=8.0),
        tmp_path / "warned",
        export=(),
    )
    notes = result.manifest["validation"]["notes"]
    assert any("atoms" in note and "memory" in note.lower() for note in notes), notes
