from __future__ import annotations

from collections import Counter

import numpy as np
import pytest
from ase.build import fcc111
from ase.constraints import FixAtoms
from ase.io import read, write

from genkai.modeling.surface.builders import sites
from genkai.modeling.surface.builders.slab import SlabSettings, build_slab
from genkai.modeling.surface.structure_io import (
    export_frames,
    make_molecule_whole,
    read_molecule,
    read_structure,
    write_frames,
)
from genkai.modeling.surface.builders.substrate import apply_slab_convention, make_slab_contiguous, supercell_in_plane

from .surface_builders_helpers import in_box_split_across_face, methylphosphonic_acid, rutile


@pytest.fixture(scope="module")
def sno2_110():
    return build_slab(rutile("SnO2"), facet="110", settings=SlabSettings()).atoms


def test_extensionless_poscar_falls_back_to_vasp_reader(tmp_path) -> None:
    slab = fcc111("Au", (2, 2, 3), vacuum=8.0, periodic=True)
    path = tmp_path / "Au_slab"
    write(path, slab, format="vasp")
    atoms, used = read_structure(path)
    assert used.startswith("vasp")
    assert atoms.get_chemical_formula() == slab.get_chemical_formula()


def test_cif_molecule_split_across_cell_face_is_made_whole(tmp_path) -> None:
    molecule = methylphosphonic_acid()
    write(tmp_path / "mpa.cif", in_box_split_across_face(molecule))
    restored, used = read_molecule(tmp_path / "mpa.cif")
    assert used == "cif"
    assert not restored.pbc.any()
    # Same bonded geometry: every interatomic distance is preserved.
    assert np.allclose(np.sort(restored.get_all_distances().ravel()), np.sort(molecule.get_all_distances().ravel()), atol=1e-3)


def test_extxyz_keeps_constraints_tags_and_arrays_and_poscar_is_unsorted(tmp_path, sno2_110) -> None:
    slab = sno2_110.copy()
    slab.new_array("fragment_id", np.arange(len(slab)) % 3)
    write_frames(tmp_path / "frames.extxyz", [slab, slab])
    back = read(tmp_path / "frames.extxyz", ":")
    assert len(back) == 2
    assert sorted(back[0].constraints[0].index) == sorted(slab.constraints[0].index)
    assert np.array_equal(back[0].get_tags(), slab.get_tags())
    assert np.array_equal(back[0].arrays["fragment_id"], slab.arrays["fragment_id"])
    paths = export_frames([slab], tmp_path / "exports", "s", ["vasp", "cif"])
    poscar = read(next(p for p in paths if p.suffix == ".vasp"))
    assert poscar.get_chemical_symbols() == slab.get_chemical_symbols()


def test_slab_from_cif_gets_bottom_fixed_again(tmp_path, sno2_110) -> None:
    write(tmp_path / "slab.cif", sno2_110)
    atoms, _ = read_structure(tmp_path / "slab.cif")
    assert not atoms.constraints  # CIF drops FixAtoms
    fixed, source = apply_slab_convention(make_slab_contiguous(atoms), SlabSettings())
    assert source.startswith("reapplied")
    z = fixed.positions[:, 2]
    index = fixed.constraints[0].index
    assert z[index].max() < z[fixed.get_tags() == 1].max()
    assert set(np.flatnonzero(fixed.get_tags() == 0)) == set(index)


def test_non_diagonal_supercell_keeps_fixed_atoms(sno2_110) -> None:
    bigger = supercell_in_plane(sno2_110, [[1, 1], [0, 2]])
    assert len(bigger) == 2 * len(sno2_110)
    assert len(bigger.constraints[0].index) == 2 * len(sno2_110.constraints[0].index)


def test_rutile_110_sites_are_fivefold_sn_and_bridging_o(sno2_110) -> None:
    cations = sites.find_surface_sites(sno2_110, sites.default_anchor_symbols(sno2_110))
    cells = np.linalg.norm(np.cross(*sno2_110.cell.array[:2])) / (3.186 * 4.737 * np.sqrt(2))
    assert len(cations) == round(cells)
    assert {(s.symbol, s.coordination, s.reference_coordination) for s in cations} == {("Sn", 5, 6)}
    acceptors = sites.oxygen_acceptors(sno2_110)
    assert acceptors[0].coordination == 2  # bridging O first
    assert Counter(s.coordination for s in acceptors)[2] == round(cells)


def test_rutile_110_has_no_close_triple_of_fivefold_cations(sno2_110) -> None:
    indices = [s.index for s in sites.find_surface_sites(sno2_110, ["Sn"])]
    assert sites.site_groups(sno2_110, indices, 2, 4.6)
    assert sites.site_groups(sno2_110, indices, 3, 4.6) == []


def test_fcc111_hollows_split_evenly_into_fcc_and_hcp() -> None:
    slab = fcc111("Au", (3, 3, 4), vacuum=10.0, periodic=True)
    top = [s.index for s in sites.find_surface_sites(slab)]
    assert len(top) == 9
    nn = sites.nearest_neighbor_distance(slab, top)
    triangles = sites.site_groups(slab, top, 3, 1.25 * nn)
    assert Counter(sites.classify_hollow(slab, t) for t in triangles) == {"fcc": 9, "hcp": 9}


def test_cation_cation_contacts_are_not_bonds_in_oxides() -> None:
    bulk = rutile("SnO2")
    from pymatgen.io.ase import AseAtomsAdaptor

    atoms = AseAtomsAdaptor.get_atoms(bulk)
    atoms.set_constraint(FixAtoms(indices=[]))
    cn = sites.coordination_numbers(atoms)
    symbols = atoms.get_chemical_symbols()
    assert {int(c) for c, s in zip(cn, symbols) if s == "Sn"} == {6}
    assert {int(c) for c, s in zip(cn, symbols) if s == "O"} == {3}
