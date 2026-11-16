"""Shared test structures for the SAM and ALD-overlayer builders."""

from __future__ import annotations

import numpy as np
from ase import Atoms
from pymatgen.core import Lattice, Structure


def rutile(formula: str = "SnO2") -> Structure:
    params = {"SnO2": (4.737, 3.186, 0.3071), "TiO2": (4.594, 2.959, 0.3048)}
    a, c, x = params[formula]
    cation = formula[:-2]
    return Structure.from_spacegroup("P4_2/mnm", Lattice.tetragonal(a, c), [cation, "O"], [[0, 0, 0], [x, x, 0]])


def methylphosphonic_acid() -> Atoms:
    """CH3-PO(OH)2 with tetrahedral P; atoms 3 and 4 are the P-OH oxygens."""
    return Atoms(
        "PCOOOHHHHH",
        positions=[
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 1.80),
            (1.405, 0.0, -0.497),
            (-0.736, 1.274, -0.520),
            (-0.736, -1.274, -0.520),
            (-1.194, 2.066, -0.843),
            (-1.194, -2.066, -0.843),
            (0.514, 0.890, 2.163),
            (-1.028, 0.0, 2.163),
            (0.514, -0.890, 2.163),
        ],
    )


def carboxymethylphosphonic_acid() -> Atoms:
    """HOOC-CH2-PO(OH)2: one phosphonic and one carboxylic anchor group (120 deg carboxyl)."""
    molecule = methylphosphonic_acid()
    c1 = molecule.positions[1]
    u = molecule.positions[7] - c1
    u /= np.linalg.norm(u)
    del molecule[7]  # replace one methyl H by the carboxyl carbon
    c2 = c1 + 1.52 * u
    w = np.cross(u, [0.0, 0.0, 1.0])
    w /= np.linalg.norm(w)
    o_double = c2 + 1.21 * (0.5 * u + np.sqrt(0.75) * w)
    o_hydroxyl = c2 + 1.34 * (0.5 * u - np.sqrt(0.75) * w)
    h = o_hydroxyl + 0.97 * (o_hydroxyl - c2) / np.linalg.norm(o_hydroxyl - c2)
    molecule.extend(Atoms("COOH", positions=[c2, o_double, o_hydroxyl, h]))
    return molecule


def in_box_split_across_face(molecule: Atoms, box: float = 8.0, shift: float = 7.5) -> Atoms:
    """Periodic copy folded so the molecule straddles a cell face (as CIF files store it)."""
    boxed = molecule.copy()
    boxed.set_cell([box, box, box])
    boxed.pbc = True
    boxed.translate([shift, box / 2, box / 2])
    boxed.wrap()
    return boxed
