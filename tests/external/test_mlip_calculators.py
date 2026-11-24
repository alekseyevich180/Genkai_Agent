"""Opt-in real single points. Run explicitly with the chosen backend's launcher."""

import os

import numpy as np
import pytest
from ase.build import bulk

from genkai.modeling.surface.mlip.calculators import build_calculator

pytestmark = pytest.mark.external


@pytest.mark.parametrize("backend", ["mace", "uma"])
def test_real_mlip_single_point(backend):
    pytest.importorskip("mace.calculators" if backend == "mace" else "fairchem.core")
    atoms = bulk("Cu", "fcc", a=3.61)
    atoms.calc = build_calculator(
        backend, device=os.environ.get("GENKAI_MLIP_DEVICE", "cpu"),
        uma_model=os.environ.get("GENKAI_UMA_MODEL", "uma-s-1p2"), task_name="omat",
    )
    assert np.isfinite(atoms.get_potential_energy())
    forces = atoms.get_forces()
    assert forces.shape == (len(atoms), 3)
    assert np.isfinite(forces).all()
