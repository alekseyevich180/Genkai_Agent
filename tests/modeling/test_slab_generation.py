import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from ase.build import fcc111
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms
from ase.io import read
from pymatgen.core import Lattice, Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from genkai.modeling.slab import (
    SlabSettings,
    atomic_layers,
    build_slab,
    energy_function_from_calculator,
    parse_miller_index,
    write_slab_outputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SLAB_SCRIPT = PROJECT_ROOT / "agents/Agent/skills/surface-modeling/scripts/surface/slab_generation.py"


def rock_salt_mgo() -> Structure:
    return Structure.from_spacegroup("Fm-3m", Lattice.cubic(4.21), ["Mg", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def fluorite_ceo2() -> Structure:
    return Structure.from_spacegroup("Fm-3m", Lattice.cubic(5.411), ["Ce", "O"], [[0, 0, 0], [0.25, 0.25, 0.25]])


def fcc(symbol: str, a: float) -> Structure:
    return Structure.from_spacegroup("Fm-3m", Lattice.cubic(a), [symbol], [[0, 0, 0]])


def layer_symbols(atoms, tolerance=0.3) -> list[set[str]]:
    symbols = np.array(atoms.get_chemical_symbols())
    return [set(symbols[layer]) for layer in atomic_layers(atoms.positions[:, 2], tolerance)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("(111)", (1, 1, 1)),
        ("111", (1, 1, 1)),
        ("(1-10)", (1, -1, 0)),
        ("(10-10)", (1, 0, 0)),
        ("0001", (0, 0, 1)),
        ("1,1,0", (1, 1, 0)),
        ("(1 1 1)", (1, 1, 1)),
    ],
)
def test_parse_miller_index_accepts_paper_notation(text, expected) -> None:
    assert parse_miller_index(text) == expected


def test_primitive_bulk_is_cut_in_the_conventional_miller_setting() -> None:
    # MP-style primitive cell: (1,0,0) in the primitive basis would be a {111} plane.
    primitive = SpacegroupAnalyzer(rock_salt_mgo()).get_primitive_standard_structure()

    result = build_slab(primitive)

    assert result.facet.miller_index == (1, 0, 0)
    assert result.facet.source == "structure_family_registry"
    # Rock-salt (100) layers contain both ions; (111) layers would be pure Mg or pure O.
    assert all(layer == {"Mg", "O"} for layer in layer_symbols(result.atoms))
    assert result.selected.polar is False
    assert result.validation.passed


def test_rock_salt_111_is_reported_as_polar() -> None:
    result = build_slab(rock_salt_mgo(), facet="(111)")

    assert result.selected.polar is True
    assert "polar_termination" in [issue.code for issue in result.validation.warnings]


def test_ceria_registry_selects_stoichiometric_oxygen_terminated_slab() -> None:
    result = build_slab(fluorite_ceo2())

    assert result.facet.miller_index == (1, 1, 1)
    assert result.selected.stoichiometric and result.selected.symmetric
    assert result.selected.polar is False
    layers = layer_symbols(result.atoms)
    assert layers[-1] == {"O"} and layers[0] == {"O"}
    assert result.validation.passed


def test_bottom_is_fixed_tagged_and_cell_is_wide_enough() -> None:
    settings = SlabSettings(min_lateral_size=8.0, fixed_fraction=0.5)
    result = build_slab(fcc("Pt", 3.92), facet="111", settings=settings)
    atoms = result.atoms

    fixed = [constraint for constraint in atoms.constraints if isinstance(constraint, FixAtoms)]
    assert len(fixed) == 1
    fixed_indices = set(int(index) for index in fixed[0].get_indices())
    assert fixed_indices == set(np.flatnonzero(atoms.get_tags() == 0))
    z = atoms.positions[:, 2]
    assert max(z[list(fixed_indices)]) < min(np.delete(z, list(fixed_indices)))
    assert min(result.geometry["lateral_widths_A"]) >= 8.0
    assert np.allclose(atoms.cell.array[2][:2], 0.0)  # c is the surface normal

    layered = build_slab(fcc("Pt", 3.92), facet="111", settings=SlabSettings(fixed_layers=2))
    layers = atomic_layers(layered.atoms.positions[:, 2], 0.3)
    assert set(np.flatnonzero(layered.atoms.get_tags() == 0)) == set(np.concatenate(layers[:2]))


def test_surface_energy_screening_selects_the_wulff_dominant_facet() -> None:
    result = build_slab(fcc("Cu", 3.61), energy_fn=energy_function_from_calculator(EMT()))

    assert result.facet.source == "computed_surface_energy"
    assert result.screening is not None
    assert result.screening.method == "wulff_area_fraction"
    gamma = {tuple(row["miller_index"]): row["surface_energy_J_m2"] for row in result.screening.facets}
    assert gamma[(1, 1, 1)] < gamma[(1, 0, 0)] < gamma[(1, 1, 0)]
    assert result.facet.miller_index == (1, 1, 1)


def test_slab_like_bulk_input_is_rejected() -> None:
    slab = AseAtomsAdaptor.get_structure(fcc111("Pt", size=(1, 1, 4), vacuum=8.0))

    with pytest.raises(ValueError, match="looks like a slab"):
        build_slab(slab, facet="111")


def test_unregistered_composition_without_facet_requires_review() -> None:
    heusler = Structure.from_spacegroup(
        "Fm-3m",
        Lattice.cubic(5.95),
        ["Mn", "Al", "Cu"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.25, 0.25, 0.25]],
    )

    with pytest.raises(ValueError, match="No stable facet is registered"):
        build_slab(heusler)


def test_outputs_keep_selective_dynamics_and_manifest(tmp_path: Path) -> None:
    result = build_slab(fluorite_ceo2())

    manifest = write_slab_outputs(result, tmp_path)

    poscar = read(manifest["files"]["surface_slab"])
    n_fixed = sum(len(c.get_indices()) for c in poscar.constraints if isinstance(c, FixAtoms))
    assert n_fixed == manifest["slab"]["n_fixed_atoms"] > 0
    stored = json.loads(Path(manifest["files"]["slab_manifest"]).read_text(encoding="utf-8"))
    assert stored["bulk"]["cell"] == "conventional_standard"
    assert stored["facet"]["miller_index"] == [1, 1, 1]
    assert stored["validation_passed"] is True
    assert len(stored["terminations"]) == 2


def test_cli_ranks_facets_with_emt_and_writes_outputs(tmp_path: Path) -> None:
    bulk_path = tmp_path / "Pt.cif"
    fcc("Pt", 3.92).to(filename=str(bulk_path))
    output_dir = tmp_path / "slab"

    completed = subprocess.run(
        [
            sys.executable,
            str(SLAB_SCRIPT),
            "--bulk",
            str(bulk_path),
            "--calculator",
            "emt",
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "slab_manifest.json").read_text(encoding="utf-8"))
    assert manifest["facet"]["selection_source"] == "computed_surface_energy"
    assert manifest["facet"]["miller_index"] == [1, 1, 1]
    assert manifest["energy_model"]["calculator"] == "emt"
    assert manifest["facet_evidence_level"] == "heuristic"
    assert (output_dir / "slab.vasp").exists() and (output_dir / "run_config.json").exists()
