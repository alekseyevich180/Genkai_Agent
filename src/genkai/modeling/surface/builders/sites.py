"""Coordination-based surface site analysis.

Sites are atoms near the top of a slab that are *exposed* (no atom sits on top
of them) and, by default, *undercoordinated* compared with the same element
deeper in the slab, e.g. five-fold Sn (Sn5c) and two-fold bridging O on
rutile SnO2(110), or every top-layer atom of a metal facet. This replaces the
"highest atom of an element" rule of the adsorbate script.

Bonds use ``scale * (r_i + r_j)`` covalent-radius cutoffs. In compounds that
contain anions only cation-anion pairs count as bonds; otherwise short
cation-cation contacts (Sn-Sn 3.19 A along rutile c) would be miscounted.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Sequence

import numpy as np
from ase import Atoms
from ase.data import covalent_radii
from ase.geometry import find_mic

from ..structure_io import solid_mask

ANION_SYMBOLS = frozenset({"O", "S", "Se", "Te", "N", "F", "Cl", "Br", "I"})
DEFAULT_BOND_SCALE = 1.15
EXPOSURE_RADIUS_A = 1.2  # lateral radius of the "nothing on top" test
EXPOSURE_HEIGHT_A = 0.4  # atoms this much higher count as covering


@dataclass(frozen=True)
class SurfaceSite:
    index: int
    symbol: str
    coordination: int
    reference_coordination: int
    z: float

    @property
    def missing_neighbors(self) -> int:
        return self.reference_coordination - self.coordination

    def summary(self) -> dict[str, object]:
        return {
            "index": self.index,
            "symbol": self.symbol,
            "coordination": self.coordination,
            "reference_coordination": self.reference_coordination,
            "z_A": round(self.z, 4),
        }


def in_plane_mic(atoms: Atoms, vectors: np.ndarray) -> np.ndarray:
    """Minimum-image vectors using only the in-plane periodicity (z is the normal)."""
    vectors = np.atleast_2d(np.asarray(vectors, dtype=float))
    pbc = np.array(atoms.pbc, dtype=bool)
    pbc[2] = False
    if not pbc.any():
        return vectors
    mic, _ = find_mic(vectors, atoms.cell, pbc=pbc)
    return mic


def bond_pairs(atoms: Atoms, scale: float = DEFAULT_BOND_SCALE, mic: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Bonded (i, j) pairs, one entry per periodic image, with the cation-anion rule.

    ``neighbor_list`` counts every image within the cutoff, so small cells
    (e.g. a rutile primitive cell with c = 3.19 A, where Sn bonds to two images
    of the same O) get correct coordination numbers.
    """
    from ase.neighborlist import neighbor_list

    if len(atoms) == 0:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=int)
    probe = atoms.copy()
    probe.set_constraint()
    if not mic:
        probe.pbc = False
    numbers = sorted(set(int(z) for z in probe.numbers))
    from ase.data import chemical_symbols

    anion = {z: chemical_symbols[z] in ANION_SYMBOLS for z in numbers}
    ionic = any(anion.values()) and not all(anion.values())
    cutoffs: dict[tuple[int, int], float] = {}
    for a in numbers:
        for b in numbers:
            if ionic and anion[a] == anion[b]:
                continue
            cutoffs[(a, b)] = scale * float(covalent_radii[a] + covalent_radii[b])
    if not cutoffs:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=int)
    i, j = neighbor_list("ij", probe, cutoffs)
    return i, j


def bond_matrix(atoms: Atoms, scale: float = DEFAULT_BOND_SCALE, mic: bool = True) -> np.ndarray:
    """Boolean connectivity (any periodic image) with the cation-anion rule."""
    bonded = np.zeros((len(atoms), len(atoms)), dtype=bool)
    i, j = bond_pairs(atoms, scale, mic)
    bonded[i, j] = True
    np.fill_diagonal(bonded, False)
    return bonded


def coordination_numbers(atoms: Atoms, scale: float = DEFAULT_BOND_SCALE) -> np.ndarray:
    i, _ = bond_pairs(atoms, scale)
    return np.bincount(i, minlength=len(atoms))


def reference_coordination(atoms: Atoms, coordination: np.ndarray) -> dict[str, int]:
    """Highest coordination of each element in the slab (its bulk-like value)."""
    reference: dict[str, int] = {}
    for symbol, value in zip(atoms.get_chemical_symbols(), coordination):
        reference[symbol] = max(reference.get(symbol, 0), int(value))
    return reference


def exposed_indices(atoms: Atoms, candidates: Iterable[int]) -> list[int]:
    """Atoms with no other atom on top of them within ``EXPOSURE_RADIUS_A``."""
    positions = atoms.get_positions()
    exposed: list[int] = []
    for index in candidates:
        higher = np.flatnonzero(positions[:, 2] > positions[index, 2] + EXPOSURE_HEIGHT_A)
        if len(higher):
            lateral = in_plane_mic(atoms, positions[higher] - positions[index])
            if (np.linalg.norm(lateral[:, :2], axis=1) < EXPOSURE_RADIUS_A).any():
                continue
        exposed.append(int(index))
    return exposed


def surface_region(atoms: Atoms, depth: float) -> list[int]:
    """Solid atoms (substrate and overlayer) within ``depth`` of the top of the solid surface.

    Atoms that earlier steps added on top (clusters, SAM molecules, adsorbates; see
    ``structure_io.components``) are never part of the surface; they still cover the
    atoms below them in ``exposed_indices``. Unlabeled structures are all substrate.
    """
    z = atoms.positions[:, 2]
    solid = solid_mask(atoms)
    if not solid.any():
        solid = np.ones(len(atoms), dtype=bool)
    top = float(z[solid].max())
    return [int(i) for i in np.flatnonzero(solid & (z >= top - depth))]


def find_surface_sites(
    atoms: Atoms,
    symbols: Sequence[str] | None = None,
    *,
    depth: float = 2.5,
    scale: float = DEFAULT_BOND_SCALE,
    undercoordinated_only: bool = True,
) -> list[SurfaceSite]:
    """Exposed (and by default undercoordinated) atoms in the top ``depth`` Angstrom."""
    coordination = coordination_numbers(atoms, scale)
    reference = reference_coordination(atoms, coordination)
    chemical = atoms.get_chemical_symbols()
    wanted = set(symbols) if symbols else None
    region = [i for i in surface_region(atoms, depth) if wanted is None or chemical[i] in wanted]
    sites: list[SurfaceSite] = []
    for index in exposed_indices(atoms, region):
        site = SurfaceSite(
            index=index,
            symbol=chemical[index],
            coordination=int(coordination[index]),
            reference_coordination=reference[chemical[index]],
            z=float(atoms.positions[index, 2]),
        )
        if undercoordinated_only and site.missing_neighbors <= 0:
            continue
        sites.append(site)
    return sorted(sites, key=lambda s: (-round(s.z, 2), atoms.positions[s.index, 1], atoms.positions[s.index, 0]))


def default_anchor_symbols(atoms: Atoms) -> list[str]:
    """Cations of an ionic slab, or every element of a metallic slab."""
    present = sorted(set(atoms.get_chemical_symbols()))
    cations = [symbol for symbol in present if symbol not in ANION_SYMBOLS]
    return cations or present


def surface_has_oxygen(atoms: Atoms, depth: float = 2.5) -> bool:
    chemical = atoms.get_chemical_symbols()
    return any(chemical[i] == "O" for i in surface_region(atoms, depth))


def oxygen_acceptors(atoms: Atoms, depth: float = 2.5, scale: float = DEFAULT_BOND_SCALE) -> list[SurfaceSite]:
    """Exposed surface O atoms, lowest coordination (e.g. bridging O) first."""
    sites = find_surface_sites(atoms, ["O"], depth=depth, scale=scale, undercoordinated_only=False)
    return sorted(sites, key=lambda s: (s.coordination, -s.z))


def unwrap_group(atoms: Atoms, group: Sequence[int]) -> np.ndarray:
    """Positions of a site group made contiguous around its first atom."""
    positions = atoms.positions[list(group)]
    return positions[0] + in_plane_mic(atoms, positions - positions[0])


def nearest_neighbor_distance(atoms: Atoms, indices: Sequence[int]) -> float:
    positions = atoms.positions[list(indices)]
    best = np.inf
    for i in range(len(positions)):
        others = np.delete(positions, i, axis=0)
        if len(others):
            best = min(best, float(np.linalg.norm(in_plane_mic(atoms, others - positions[i]), axis=1).min()))
    return best


def site_groups(atoms: Atoms, indices: Sequence[int], size: int, max_span: float) -> list[tuple[int, ...]]:
    """Groups of ``size`` distinct sites whose unwrapped pairwise distances are <= ``max_span``."""
    indices = [int(i) for i in indices]
    if size < 1:
        raise ValueError("Site group size must be >= 1.")
    if size == 1:
        return [(i,) for i in indices]
    positions = atoms.positions[indices]
    n = len(indices)
    close = np.zeros((n, n), dtype=bool)
    for i in range(n):
        lateral = in_plane_mic(atoms, positions - positions[i])
        close[i] = np.linalg.norm(lateral, axis=1) <= max_span
    np.fill_diagonal(close, False)
    groups: list[tuple[int, ...]] = []
    for combo in combinations(range(n), size):
        if not all(close[a, b] for a, b in combinations(combo, 2)):
            continue
        unwrapped = unwrap_group(atoms, [indices[k] for k in combo])
        spans = [np.linalg.norm(unwrapped[a] - unwrapped[b]) for a, b in combinations(range(size), 2)]
        if max(spans) <= max_span + 1e-6:
            groups.append(tuple(sorted(indices[k] for k in combo)))
    return sorted(set(groups))


def classify_hollow(atoms: Atoms, group: Sequence[int], window: tuple[float, float] = (0.5, 3.2)) -> str:
    """'hcp' if an atom of the layer below sits under the hollow centre, else 'fcc'."""
    centre = unwrap_group(atoms, group).mean(axis=0)
    z = atoms.positions[:, 2]
    below = np.flatnonzero((z < centre[2] - window[0]) & (z > centre[2] - window[1]))
    if len(below):
        lateral = in_plane_mic(atoms, atoms.positions[below] - centre)
        if (np.linalg.norm(lateral[:, :2], axis=1) < 0.6).any():
            return "hcp"
    return "fcc"
