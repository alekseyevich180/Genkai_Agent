"""Amorphous oxide overlayers for ALD-modified surfaces (geometry only).

Two coverages, both cut from a user-supplied periodic amorphous bulk cell:

* ``full`` - a continuous amorphous film. ``film_fit="strain"``: the in-plane
  cells of slab and film are matched with pymatgen's ZSL algorithm and the
  amorphous supercell is affinely strained onto the slab supercell, so the film
  stays periodic without seams. ``film_fit="cut"``: a randomly rotated tiling
  of the amorphous cell is cut to the slab cell and atoms that end up too close
  across the periodic boundaries are removed (works for any cell, e.g.
  hexagonal facets). ``auto`` (default) uses ``strain`` when a match exists and
  ``cut`` otherwise. A window of the requested thickness is placed at
  ``interface_gap`` above the slab.
* ``partial`` - an amorphous island on one facet (sub-monolayer ALD: only a
  few facets carry islands). A connected, hemisphere-like cluster of a given
  atom count or radius is cut from the amorphous bulk and placed on the facet;
  the slab is enlarged so the island and its periodic images stay apart.

The facet is the user's choice; without one the substrate module cuts the most
stable facet. Cut films and islands are generally off-stoichiometric; the
composition is reported, never corrected silently. Nothing is relaxed or
annealed: every structure is an unrelaxed candidate (evidence ``heuristic``).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from ase import Atoms
from ase.build import make_supercell
from ase.constraints import FixAtoms
from ase.data import covalent_radii

from .sites import ANION_SYMBOLS, bond_matrix, in_plane_mic
from .structure_io import export_frames, read_structure, sha256_of, write_frames, write_manifest
from .substrate import (
    Substrate,
    add_substrate_arguments,
    fixed_indices,
    parse_export,
    parse_floats,
    repeats_for_width,
    substrate_from_args,
    supercell_in_plane,
    surface_area,
)

COVERAGES = ("full", "partial")
FILM_FITS = ("auto", "strain", "cut")
CLASH_FRACTION = 0.6
SEAM_FRACTION = 0.85  # cut films: no pair closer than 0.85 x the shortest same-pair distance in the bulk
AMU_PER_A3_TO_G_PER_CM3 = 1.66053906660


class OverlayerBuildError(ValueError):
    """Raised when the requested overlayer cannot be built as specified."""


@dataclass
class OverlayerSettings:
    coverage: str
    thickness: float | None = None
    island_atoms: int | None = None
    island_radius: float | None = None
    island_position: tuple[float, float] = (0.5, 0.5)
    island_separation: float = 8.0
    interface_gap: float = 2.0
    max_strain: float = 0.05
    max_area: float = 600.0
    samples: int = 1
    seed: int = 42
    vacuum_above: float = 15.0
    film_fit: str = "auto"

    def __post_init__(self) -> None:
        if self.coverage not in COVERAGES:
            raise OverlayerBuildError(f"coverage must be one of {', '.join(COVERAGES)}.")
        if self.film_fit not in FILM_FITS:
            raise OverlayerBuildError(f"film_fit must be one of {', '.join(FILM_FITS)}.")
        if self.coverage == "full":
            if self.thickness is None or self.thickness <= 0:
                raise OverlayerBuildError("Full coverage needs a positive film thickness (A).")
            if self.island_atoms is not None or self.island_radius is not None:
                raise OverlayerBuildError("Island size options apply only to partial coverage.")
        else:
            if (self.island_atoms is None) == (self.island_radius is None):
                raise OverlayerBuildError("Partial coverage needs exactly one of island_atoms or island_radius.")
            if self.island_atoms is not None and self.island_atoms < 2:
                raise OverlayerBuildError("An island needs at least 2 atoms.")
            if self.island_radius is not None and self.island_radius <= 0:
                raise OverlayerBuildError("The island radius must be positive.")
            if self.thickness is not None:
                raise OverlayerBuildError("thickness applies only to full coverage.")
        if self.interface_gap <= 0 or self.samples < 1 or self.island_separation < 0:
            raise OverlayerBuildError("interface_gap and samples must be positive; island_separation >= 0.")
        if not 0 < self.max_strain <= 0.3:
            raise OverlayerBuildError("max_strain must satisfy 0 < max_strain <= 0.3.")


# ---------------------------------------------------------------------------
# Amorphous input and analysis helpers
# ---------------------------------------------------------------------------


def check_amorphous_bulk(atoms: Atoms) -> None:
    """The amorphous input must be a dense periodic 3D cell, not a slab or cluster."""
    if atoms.cell.rank < 3:
        raise OverlayerBuildError("The amorphous structure needs a full 3D periodic cell.")
    scaled = np.mod(atoms.get_scaled_positions(wrap=False), 1.0)
    lengths = atoms.cell.lengths()
    for axis in range(3):
        values = np.sort(scaled[:, axis])
        gaps = np.diff(np.concatenate([values, [values[0] + 1.0]])) * lengths[axis]
        if gaps.max() > 5.0:
            raise OverlayerBuildError(
                f"The amorphous structure has a {gaps.max():.1f} A empty gap along cell axis {axis}; "
                "supply a periodic bulk cell, not a slab or cluster."
            )


def density_g_cm3(atoms: Atoms, volume_A3: float) -> float:
    return float(atoms.get_masses().sum() / volume_A3 * AMU_PER_A3_TO_G_PER_CM3)


def composition_report(part: Atoms, reference: Atoms) -> dict[str, Any]:
    """Composition of a cut film/island against the amorphous bulk it came from."""

    def split(atoms: Atoms) -> tuple[int, int]:
        symbols = atoms.get_chemical_symbols()
        anions = sum(1 for s in symbols if s in ANION_SYMBOLS)
        return anions, len(symbols) - anions

    anions, cations = split(part)
    ref_anions, ref_cations = split(reference)
    ref_ratio = ref_anions / ref_cations if ref_cations else None
    ratio = anions / cations if cations else None
    return {
        "formula": part.get_chemical_formula(mode="hill"),
        "n_atoms": len(part),
        "reference_formula": reference.get_chemical_formula(mode="hill", empirical=True),
        "anion_to_cation_ratio": round(ratio, 4) if ratio is not None else None,
        "reference_anion_to_cation_ratio": round(ref_ratio, 4) if ref_ratio is not None else None,
        "excess_anions": round(anions - ref_ratio * cations, 4) if ref_ratio is not None else None,
        "stoichiometric": bool(ref_ratio is not None and abs(anions - ref_ratio * cations) < 1e-6),
    }


def _plane_coordinates(v1: np.ndarray, v2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """2D coordinates of two vectors in their own right-handed plane frame, and the plane normal."""
    e1 = v1 / np.linalg.norm(v1)
    normal = np.cross(v1, v2)
    normal /= np.linalg.norm(normal)
    e2 = np.cross(normal, e1)
    return np.array([[v @ e1, v @ e2] for v in (v1, v2)]), normal


@dataclass
class FilmMatch:
    substrate_matrix: np.ndarray
    film_matrix: np.ndarray
    principal_strains: tuple[float, float]
    area_A2: float

    def summary(self) -> dict[str, Any]:
        return {
            "substrate_supercell": self.substrate_matrix.tolist(),
            "amorphous_supercell": self.film_matrix.tolist(),
            "principal_strains": [round(s, 5) for s in self.principal_strains],
            "max_abs_strain": round(max(abs(s) for s in self.principal_strains), 5),
            "area_A2": round(self.area_A2, 4),
            "method": "pymatgen ZSLGenerator; amorphous supercell strained affinely onto the slab supercell",
        }


def match_film_lattice(substrate: Atoms, amorphous: Atoms, max_strain: float, max_area: float) -> FilmMatch:
    """Smallest in-plane supercell pair whose affine map has |strain| <= max_strain (no mirroring)."""
    matches = film_lattice_matches(substrate, amorphous, max_strain, max_area)
    if not matches:
        raise OverlayerBuildError(
            f"No in-plane supercell match between slab and amorphous cell within {max_strain:.1%} strain and "
            f"{max_area:.0f} A^2; raise --max-strain or --max-area."
        )
    return matches[0]


def film_lattice_matches(substrate: Atoms, amorphous: Atoms, max_strain: float, max_area: float) -> list[FilmMatch]:
    """All distinct proper (non-mirrored) matches, smallest area then smallest strain first."""
    from pymatgen.analysis.interfaces.zsl import ZSLGenerator

    sv = substrate.cell.array[:2]
    fv = amorphous.cell.array[:2]
    film_2d, _ = _plane_coordinates(*fv)
    sub_2d, _ = _plane_coordinates(*sv)
    generator = ZSLGenerator(
        max_area_ratio_tol=2.0 * max_strain + 0.01,
        max_area=max_area,
        max_length_tol=max_strain,
        max_angle_tol=max_strain,
    )
    found: dict[tuple[int, ...], FilmMatch] = {}
    for match in generator(fv, sv):
        film_sl = np.asarray(match.film_sl_vectors, dtype=float)
        sub_sl = np.asarray(match.substrate_sl_vectors, dtype=float)
        tf = np.rint(film_sl @ np.linalg.pinv(fv)).astype(int)
        ts = np.rint(sub_sl @ np.linalg.pinv(sv)).astype(int)
        if not (np.allclose(tf @ fv, film_sl, atol=1e-3) and np.allclose(ts @ sv, sub_sl, atol=1e-3)):
            continue
        if np.linalg.det(tf) < 0:  # flip one vector pair; the correspondence is unchanged
            tf[1] *= -1
            ts[1] *= -1
        if round(float(np.linalg.det(tf))) <= 0 or round(float(np.linalg.det(ts))) <= 0:
            continue  # would need a mirror image of the amorphous structure
        film_vectors = tf @ film_2d
        sub_vectors = ts @ sub_2d
        mapping = sub_vectors.T @ np.linalg.inv(film_vectors.T)
        stretches = np.sqrt(np.linalg.eigvalsh(mapping.T @ mapping))
        strains = (float(stretches[0] - 1.0), float(stretches[1] - 1.0))
        if max(abs(s) for s in strains) > max_strain + 1e-9:
            continue
        area = abs(float(np.linalg.det(sub_vectors)))
        key = tuple(int(v) for v in np.concatenate([ts.ravel(), tf.ravel()]))
        found.setdefault(key, FilmMatch(ts, tf, strains, area))
    return sorted(found.values(), key=lambda m: (round(m.area_A2, 3), max(map(abs, m.principal_strains))))


def pair_reference_distances(bulk: Atoms) -> dict[tuple[str, str], float]:
    """Shortest distance of every element pair in the periodic amorphous bulk."""
    distances = bulk.get_all_distances(mic=True)
    np.fill_diagonal(distances, np.inf)
    symbols = np.array(bulk.get_chemical_symbols())
    reference: dict[tuple[str, str], float] = {}
    for a in sorted(set(symbols)):
        for b in sorted(set(symbols)):
            block = distances[np.ix_(symbols == a, symbols == b)]
            if block.size and np.isfinite(block).any():
                reference[(a, b)] = float(block[np.isfinite(block)].min())
    return reference


def repair_seams(
    film: Atoms, reference: dict[tuple[str, str], float], fraction: float = SEAM_FRACTION
) -> tuple[Atoms, int]:
    """Remove atoms closer than ``fraction`` x the bulk pair distance (minimum image), worst first."""
    current = film.copy()
    removed = 0
    while len(current) > 1:
        distances = current.get_all_distances(mic=True)
        np.fill_diagonal(distances, np.inf)
        symbols = current.get_chemical_symbols()
        limits = np.array(
            [[fraction * reference.get((a, b), 0.0) for b in symbols] for a in symbols]
        )
        violations = distances < limits
        if not violations.any():
            break
        del current[int(np.argmax(violations.sum(axis=1)))]
        removed += 1
    return current, removed


def remove_isolated(atoms: Atoms, pbc_in_plane: bool) -> tuple[Atoms, int]:
    """Drop atoms with no bonded neighbour (fragments of the cut), repeating until stable."""
    removed = 0
    current = atoms.copy()
    current.pbc = [pbc_in_plane, pbc_in_plane, False]
    while len(current):
        coordination = bond_matrix(current, mic=pbc_in_plane).sum(axis=1)
        lonely = np.flatnonzero(coordination == 0)
        if not len(lonely):
            break
        del current[[int(i) for i in lonely]]
        removed += len(lonely)
    return current, removed


def _largest_component(atoms: Atoms) -> tuple[Atoms, int]:
    bonded = bond_matrix(atoms, mic=False)
    seen = np.zeros(len(atoms), dtype=bool)
    components: list[list[int]] = []
    for start in range(len(atoms)):
        if seen[start]:
            continue
        stack, component = [start], []
        seen[start] = True
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in np.flatnonzero(bonded[current]):
                if not seen[neighbor]:
                    seen[neighbor] = True
                    stack.append(int(neighbor))
        components.append(component)
    keep = max(components, key=len)
    return atoms[sorted(keep)], len(atoms) - len(keep)


# ---------------------------------------------------------------------------
# Full coverage: amorphous film
# ---------------------------------------------------------------------------


def _assemble(slab: Atoms, overlayer: Atoms, settings: OverlayerSettings) -> tuple[Atoms, float | None]:
    top = float(slab.positions[:, 2].max())
    overlayer = overlayer.copy()
    overlayer.positions[:, 2] += top + settings.interface_gap - float(overlayer.positions[:, 2].min())
    n_slab = len(slab)
    frame = slab.copy()
    frame.set_constraint()
    frame.extend(overlayer)
    cell = frame.cell.array.copy()
    cell[2] = [0.0, 0.0, max(float(slab.cell.array[2, 2]), float(frame.positions[:, 2].max()) + settings.vacuum_above)]
    frame.set_cell(cell)
    frame.pbc = True
    tags = np.concatenate([slab.get_tags(), np.full(len(overlayer), 2)])
    frame.set_tags(tags)
    fixed = fixed_indices(slab)
    if fixed:
        frame.set_constraint(FixAtoms(indices=fixed))
    role = np.concatenate([np.zeros(n_slab, dtype=int), np.ones(len(overlayer), dtype=int)])
    frame.new_array("fragment_id", role.copy())
    frame.new_array("ald_role", role)
    distances = frame.get_all_distances(mic=True)[:n_slab, n_slab:]
    radii = covalent_radii[frame.numbers]
    ratio = distances / (radii[:n_slab, None] + radii[None, n_slab:])
    return frame, (float(ratio.min()) if ratio.size else None)


def build_film(
    slab: Atoms, amorphous: Atoms, match: FilmMatch, settings: OverlayerSettings, rng: np.random.Generator
) -> tuple[Atoms, dict[str, Any]]:
    fv = amorphous.cell.array[:2]
    _, film_normal = _plane_coordinates(*fv)
    layer_height = abs(float(amorphous.cell.array[2] @ film_normal))
    thickness = float(settings.thickness)  # type: ignore[arg-type]
    nz = int(np.ceil(thickness / layer_height)) + 1
    transform = np.zeros((3, 3), dtype=int)
    transform[:2, :2] = match.film_matrix
    transform[2, 2] = nz
    block = make_supercell(amorphous, transform)
    s1, s2 = slab.cell.array[0], slab.cell.array[1]
    # Affine map: film supercell vectors -> slab supercell vectors, film normal -> z. Applying it to
    # Cartesian positions keeps a tilted amorphous c consistent (no artificial shear).
    f1, f2 = block.cell.array[0], block.cell.array[1]
    source = np.column_stack([f1, f2, film_normal])
    target = np.column_stack([s1, s2, [0.0, 0.0, 1.0]])
    mapped = (target @ np.linalg.inv(source) @ block.get_positions(wrap=True).T).T
    z = mapped[:, 2] - mapped[:, 2].min()
    z0 = float(rng.uniform(0.0, layer_height))
    window = (z >= z0) & (z < z0 + thickness)
    positions = mapped[window].copy()
    positions[:, 2] = z[window] - z0
    film = Atoms(
        [s for s, keep in zip(block.get_chemical_symbols(), window) if keep],
        positions=positions,
        cell=[s1, s2, [0.0, 0.0, thickness + 10.0]],
        pbc=[True, True, False],
    )
    film.wrap(pbc=[True, True, False])
    film, removed = remove_isolated(film, pbc_in_plane=True)
    if not len(film):
        raise OverlayerBuildError("The cut film is empty; increase the thickness.")
    frame, contact = _assemble(slab, film, settings)
    area = surface_area(slab)
    report = {
        "film_fit": "strain",
        "z_window_start_A": round(z0, 4),
        "thickness_A": thickness,
        "isolated_atoms_removed": removed,
        "film_density_g_cm3": round(density_g_cm3(film, area * thickness), 4),
        "composition": composition_report(film, amorphous),
        "interface_gap_A": settings.interface_gap,
        "min_interface_contact_ratio": round(contact, 4) if contact is not None else None,
    }
    return frame, report


def build_film_cut(
    slab: Atoms,
    amorphous: Atoms,
    reference: dict[tuple[str, str], float],
    settings: OverlayerSettings,
    rng: np.random.Generator,
) -> tuple[Atoms, dict[str, Any]]:
    """Film for any slab cell: cut a randomly rotated amorphous tiling, then repair the periodic seams."""
    from scipy.spatial.transform import Rotation

    thickness = float(settings.thickness)  # type: ignore[arg-type]
    s1, s2 = slab.cell.array[0], slab.cell.array[1]
    corners = np.array([[0.0, 0.0], s1[:2], s2[:2], (s1 + s2)[:2]])
    extent = corners.max(axis=0) - corners.min(axis=0)
    span = float(extent.sum() + thickness + 4.0)  # covers the box diagonal after any rotation
    volume = float(amorphous.get_volume())
    cell = amorphous.cell.array
    widths = [volume / np.linalg.norm(np.cross(cell[(i + 1) % 3], cell[(i + 2) % 3])) for i in range(3)]
    block = amorphous.repeat([int(np.ceil(span / w)) + 1 for w in widths])
    block.wrap()
    centre = 0.5 * block.cell.array.sum(axis=0)
    rotation = Rotation.random(random_state=int(rng.integers(0, 2**31 - 1)))
    local = rotation.apply(block.get_positions() - centre)
    xy = local[:, :2] + 0.5 * (s1 + s2)[:2]
    fractional = np.linalg.solve(np.array([s1[:2], s2[:2]]).T, xy.T).T
    keep = (
        (fractional >= 0.0).all(axis=1)
        & (fractional < 1.0).all(axis=1)
        & (local[:, 2] >= -0.5 * thickness)
        & (local[:, 2] < 0.5 * thickness)
    )
    positions = fractional[keep, :1] * s1 + fractional[keep, 1:2] * s2
    positions[:, 2] = local[keep, 2] + 0.5 * thickness
    film = Atoms(
        [s for s, k in zip(block.get_chemical_symbols(), keep) if k],
        positions=positions,
        cell=[s1, s2, [0.0, 0.0, thickness + 10.0]],
        pbc=[True, True, False],
    )
    cut_atoms = len(film)
    film, seam_removed = repair_seams(film, reference)
    film, isolated = remove_isolated(film, pbc_in_plane=True)
    if not len(film):
        raise OverlayerBuildError("The cut film is empty; increase the thickness.")
    frame, contact = _assemble(slab, film, settings)
    area = surface_area(slab)
    report = {
        "film_fit": "cut",
        "rotation_quaternion": [round(v, 6) for v in rotation.as_quat()],
        "thickness_A": thickness,
        "atoms_in_cut": cut_atoms,
        "seam_atoms_removed": seam_removed,
        "seam_rule": f"no pair closer than {SEAM_FRACTION} x its shortest distance in the amorphous bulk",
        "isolated_atoms_removed": isolated,
        "film_density_g_cm3": round(density_g_cm3(film, area * thickness), 4),
        "composition": composition_report(film, amorphous),
        "interface_gap_A": settings.interface_gap,
        "min_interface_contact_ratio": round(contact, 4) if contact is not None else None,
    }
    return frame, report


# ---------------------------------------------------------------------------
# Partial coverage: amorphous island
# ---------------------------------------------------------------------------


def _cut_island(amorphous: Atoms, settings: OverlayerSettings, rng: np.random.Generator) -> tuple[Atoms, dict[str, Any]]:
    volume = float(amorphous.get_volume())
    number_density = len(amorphous) / volume
    if settings.island_radius is not None:
        radius = float(settings.island_radius)
    else:
        radius = (3.0 * settings.island_atoms / (2.0 * np.pi * number_density)) ** (1.0 / 3.0)  # type: ignore[operator]
    cell = amorphous.cell.array
    widths = [volume / np.linalg.norm(np.cross(cell[(i + 1) % 3], cell[(i + 2) % 3])) for i in range(3)]
    reps = [max(1, int(np.ceil((4.0 * radius + 6.0) / w))) for w in widths]
    block = amorphous.repeat(reps)
    block.wrap()
    centre = 0.5 * block.cell.array.sum(axis=0) + rng.uniform(-0.5, 0.5, size=3) @ cell
    positions = block.get_positions()
    above = np.flatnonzero(positions[:, 2] >= centre[2])
    distance = np.linalg.norm(positions[above] - centre, axis=1)
    order = above[np.argsort(distance, kind="stable")]
    sorted_distance = np.sort(distance, kind="stable")
    plain = block.copy()
    plain.pbc = False
    if settings.island_atoms is not None:
        radii = covalent_radii[plain.numbers]
        anion = np.isin(np.array(plain.get_chemical_symbols()), list(ANION_SYMBOLS))
        island: list[int] = [int(order[0])]
        for index, dist in zip(order[1:], sorted_distance[1:]):
            if len(island) >= settings.island_atoms or dist > 3.0 * radius + 4.0:
                break
            members = np.array(island)
            gaps = np.linalg.norm(positions[members] - positions[index], axis=1)
            cutoff = 1.15 * (radii[members] + radii[index])
            pairs_ok = anion[members] != anion[index] if anion.any() and (~anion).any() else np.ones(len(members), bool)
            if ((gaps <= cutoff) & pairs_ok).any():
                island.append(int(index))
        cluster = plain[sorted(island)]
        removed = 0
    else:
        cluster = plain[sorted(int(i) for i in order[sorted_distance <= radius])]
        cluster, removed = _largest_component(cluster) if len(cluster) > 1 else (cluster, 0)
    if len(cluster) < 2:
        raise OverlayerBuildError("The island cut contains fewer than 2 bonded atoms; enlarge it.")
    cluster.positions -= cluster.positions.mean(axis=0)
    report = {
        "requested_atoms": settings.island_atoms,
        "requested_radius_A": settings.island_radius,
        "cut_radius_estimate_A": round(radius, 4),
        "detached_atoms_removed": removed,
        "composition": composition_report(cluster, amorphous),
    }
    if settings.island_atoms is not None and len(cluster) < settings.island_atoms:
        report["warning"] = f"Only {len(cluster)} connected atoms could be cut (requested {settings.island_atoms})."
    return cluster, report


def lateral_diameter(atoms: Atoms) -> float:
    xy = atoms.positions[:, :2]
    if len(xy) < 2:
        return 0.0
    return float(np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2).max())


def footprint_area(atoms: Atoms) -> float:
    from scipy.spatial import ConvexHull, QhullError

    xy = atoms.positions[:, :2]
    if len(xy) < 3:
        return 0.0
    try:
        return float(ConvexHull(xy).volume)
    except QhullError:
        return 0.0


def place_island(
    slab: Atoms, island: Atoms, settings: OverlayerSettings
) -> tuple[Atoms, dict[str, Any]]:
    x, y = settings.island_position
    target = x * slab.cell.array[0] + y * slab.cell.array[1]
    placed = island.copy()
    placed.positions[:, :2] += target[:2] - placed.positions[:, :2].mean(axis=0)
    frame, contact = _assemble(slab, placed, settings)
    n_slab = len(slab)
    island_positions = frame.positions[n_slab:]
    image_gap = np.inf
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            if i == 0 and j == 0:
                continue
            shifted = island_positions + i * slab.cell.array[0] + j * slab.cell.array[1]
            gaps = np.linalg.norm(island_positions[:, None, :] - shifted[None, :, :], axis=2)
            image_gap = min(image_gap, float(gaps.min()))
    area = surface_area(slab)
    footprint = footprint_area(placed)
    report = {
        "lateral_diameter_A": round(lateral_diameter(placed), 4),
        "footprint_area_A2": round(footprint, 4),
        "footprint_fraction": round(footprint / area, 4),
        "min_gap_to_periodic_image_A": round(image_gap, 4),
        "interface_gap_A": settings.interface_gap,
        "min_interface_contact_ratio": round(contact, 4) if contact is not None else None,
    }
    return frame, report


# ---------------------------------------------------------------------------
# Run (programmatic API) and CLI
# ---------------------------------------------------------------------------


@dataclass
class OverlayerRunResult:
    frames: list[Atoms]
    manifest: dict[str, Any]
    structures_path: Path
    manifest_path: Path
    exported: list[Path]


def run_overlayer(
    substrate: Substrate,
    amorphous_path: str | Path,
    settings: OverlayerSettings,
    output_dir: str | Path,
    *,
    amorphous_format: str | None = None,
    export: Sequence[str] = ("cif",),
) -> OverlayerRunResult:
    """Build ALD overlayer frames (clean slab first) and write extxyz + manifest."""
    outdir = Path(output_dir)
    amorphous, amorphous_format_used = read_structure(amorphous_path, amorphous_format)
    amorphous.pbc = True
    check_amorphous_bulk(amorphous)
    rng = np.random.default_rng(settings.seed)
    samples: list[dict[str, Any]] = []
    frames: list[Atoms] = []
    match_record: dict[str, Any] | None = None
    notes: list[str] = []

    if settings.coverage == "full":
        match: FilmMatch | None = None
        no_match_reason = None
        if settings.film_fit in ("auto", "strain"):
            try:
                match = match_film_lattice(substrate.atoms, amorphous, settings.max_strain, settings.max_area)
            except OverlayerBuildError as exc:
                if settings.film_fit == "strain":
                    raise
                no_match_reason = str(exc)
        if match is not None:
            match_record = {"film_fit": "strain", **match.summary()}
            slab = supercell_in_plane(substrate.atoms, match.substrate_matrix)
            for sample in range(settings.samples):
                frame, report = build_film(slab, amorphous, match, settings, rng)
                samples.append({"sample": sample, **report})
                frames.append(frame)
        else:
            slab = substrate.atoms
            reference = pair_reference_distances(amorphous)
            match_record = {
                "film_fit": "cut",
                "reason": no_match_reason or "film_fit=cut requested",
                "pair_reference_distances_A": {f"{a}-{b}": round(d, 4) for (a, b), d in reference.items()},
            }
            notes.append(
                "Film cut without lattice matching: atoms too close across the periodic cell boundaries were "
                "removed (see seam_atoms_removed); the film is less uniform there than a strained film."
            )
            for sample in range(settings.samples):
                frame, report = build_film_cut(slab, amorphous, reference, settings, rng)
                samples.append({"sample": sample, **report})
                frames.append(frame)
    else:
        islands = [_cut_island(amorphous, settings, rng) for _ in range(settings.samples)]
        for sample, (island, cut_report) in enumerate(islands):
            # The isolated island, for an energy-based placement search (cluster_search --cluster).
            cut_report["island_file"] = write_frames(outdir / "islands" / f"island_{sample:03d}.extxyz", [island]).as_posix()
        diameter = max(lateral_diameter(island) for island, _ in islands)
        repeats = repeats_for_width(substrate.atoms, diameter + settings.island_separation + 2.0 * settings.interface_gap)
        slab = substrate.atoms.repeat((repeats[0], repeats[1], 1))
        match_record = {"slab_repeat_xy": list(repeats), "max_island_diameter_A": round(diameter, 4)}
        for sample, (island, cut_report) in enumerate(islands):
            frame, place_report = place_island(slab, island, settings)
            samples.append({"sample": sample, **cut_report, **place_report})
            frames.append(frame)

    clean = slab.copy()
    clean.new_array("fragment_id", np.zeros(len(clean), dtype=int))
    clean.new_array("ald_role", np.zeros(len(clean), dtype=int))
    clean.info.update({"task": "ald_overlayer", "role": "clean_slab", "frame_id": 0})
    issues: list[str] = []
    for frame_id, (frame, report) in enumerate(zip(frames, samples), start=1):
        contact = report.get("min_interface_contact_ratio")
        if contact is not None and contact < CLASH_FRACTION:
            issues.append(f"sample {report['sample']}: interface contact ratio {contact} < {CLASH_FRACTION}")
        frame.info.update(
            {
                "task": "ald_overlayer",
                "role": f"amorphous_{'film' if settings.coverage == 'full' else 'island'}_on_slab",
                "coverage": settings.coverage,
                "sample": report["sample"],
                "frame_id": frame_id,
            }
        )
        report["frame_id"] = frame_id
    all_frames = [clean, *frames]

    structures_path = write_frames(outdir / "ald_structures.extxyz", all_frames)
    exported = export_frames(all_frames, outdir / "exports", "ald", export) if export else []
    manifest = {
        "schema_version": "1.0",
        "generator": "genkai.modeling.surface.amorphous_overlayer",
        "mode": "structure-only",
        "calculator": "none",
        "evidence_level": "heuristic",
        "scientific_calculation_started": False,
        "energies_available": False,
        "note": (
            "Amorphous overlayer cut from the supplied amorphous bulk and placed without relaxation or annealing; "
            "the interface and the cut surfaces are not equilibrated and the composition is not corrected."
        ),
        "substrate": substrate.record,
        "slab_in_frames": {
            "n_atoms": len(slab),
            "surface_area_A2": round(surface_area(slab), 4),
            "n_fixed": len(fixed_indices(slab)),
        },
        "amorphous": {
            "path": Path(amorphous_path).as_posix(),
            "format": amorphous_format_used,
            "sha256": sha256_of(amorphous_path),
            "formula": amorphous.get_chemical_formula(mode="hill"),
            "n_atoms": len(amorphous),
            "cell_lengths_A": [round(v, 4) for v in amorphous.cell.lengths()],
            "density_g_cm3": round(density_g_cm3(amorphous, float(amorphous.get_volume())), 4),
        },
        "coverage": settings.coverage,
        "lattice": match_record,
        "settings": asdict(settings),
        "samples": samples,
        "files": {
            "structures": structures_path.as_posix(),
            "exports": [p.as_posix() for p in exported],
            "islands": [s["island_file"] for s in samples if "island_file" in s],
        },
        "validation": {"warnings": [i.model_dump() for i in substrate.warnings], "issues": issues, "notes": notes},
        "conventions": {
            "tags": "0 = fixed subsurface, 1 = free slab, 2 = amorphous overlayer",
            "fragment_id": "0 = slab, 1 = overlayer",
            "ald_role": "0 = slab, 1 = overlayer",
            "frames": "frame 0 = clean slab (same supercell), then one frame per sample",
        },
    }
    manifest_path = write_manifest(outdir / "ald_manifest.json", manifest)
    return OverlayerRunResult(all_frames, manifest, structures_path, manifest_path, exported)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build unrelaxed ALD-modified surfaces: a full amorphous film or a partial amorphous island."
    )
    add_substrate_arguments(parser)
    parser.add_argument("--amorphous", type=Path, required=True, help="Periodic amorphous bulk cell (CIF by default; any ASE format).")
    parser.add_argument("--amorphous-format", default=None)
    parser.add_argument("--coverage", choices=COVERAGES, required=True, help="full: continuous film; partial: island on the facet.")
    parser.add_argument("--thickness", type=float, default=None, help="Film thickness in A (full coverage).")
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--island-atoms", type=int, default=None, help="Island atom count (partial coverage).")
    size.add_argument("--island-radius", type=float, default=None, help="Island hemisphere radius in A (partial coverage).")
    parser.add_argument("--island-position", default="0.5,0.5", help="Fractional in-plane position of the island centre.")
    parser.add_argument("--island-separation", type=float, default=8.0, help="Minimum gap between an island and its images (A).")
    parser.add_argument("--interface-gap", type=float, default=2.0, help="Gap between the slab top and the overlayer bottom (A).")
    parser.add_argument("--max-strain", type=float, default=0.05, help="Largest in-plane strain of the amorphous film.")
    parser.add_argument("--max-area", type=float, default=600.0, help="Largest matched in-plane supercell area (A^2).")
    parser.add_argument(
        "--film-fit",
        choices=FILM_FITS,
        default="auto",
        help="Full coverage: strain (lattice match, seamless), cut (any cell, seams repaired), auto (strain, else cut).",
    )
    parser.add_argument("--samples", type=int, default=1, help="Different cuts of the amorphous bulk (one frame each).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--export", default="cif", help="Comma-separated export formats (cif, vasp) or 'none'.")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        position = parse_floats(args.island_position)
        if position is None or len(position) != 2:
            raise OverlayerBuildError("--island-position needs two fractions, e.g. 0.5,0.5.")
        settings = OverlayerSettings(
            coverage=args.coverage,
            thickness=args.thickness,
            island_atoms=args.island_atoms,
            island_radius=args.island_radius,
            island_position=(position[0], position[1]),
            island_separation=args.island_separation,
            interface_gap=args.interface_gap,
            max_strain=args.max_strain,
            max_area=args.max_area,
            samples=args.samples,
            film_fit=args.film_fit,
            seed=args.seed,
        )
        substrate = substrate_from_args(args)
        result = run_overlayer(
            substrate,
            args.amorphous,
            settings,
            args.output_dir,
            amorphous_format=args.amorphous_format,
            export=parse_export(args.export),
        )
    except (OverlayerBuildError, ValueError, FileNotFoundError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    manifest = result.manifest
    substrate_record = manifest["substrate"]
    print(f"Substrate: {substrate_record['formula']} facet={substrate_record.get('facet')} via {substrate_record['facet_source']}")
    print(f"Amorphous: {manifest['amorphous']['formula']} ({manifest['amorphous']['density_g_cm3']} g/cm^3), coverage {settings.coverage}")
    lattice = dict(manifest["lattice"] or {})
    lattice.pop("pair_reference_distances_A", None)
    print(f"Lattice: {lattice}")
    for note in manifest["validation"]["notes"]:
        print(f"NOTE {note}")
    for sample in manifest["samples"]:
        comp = sample["composition"]
        print(f"  sample {sample['sample']}: {comp['formula']} (anion/cation {comp['anion_to_cation_ratio']} vs "
              f"{comp['reference_anion_to_cation_ratio']}), interface contact ratio {sample['min_interface_contact_ratio']}")
    for issue in manifest["validation"]["issues"]:
        print(f"WARNING {issue}")
    print(f"Wrote {result.structures_path} ({len(result.frames)} frames) and {result.manifest_path}")
    return 0 if not manifest["validation"]["issues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
