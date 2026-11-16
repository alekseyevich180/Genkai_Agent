"""Self-assembled monolayer (SAM) structures on a stable surface.

Pipeline (geometry only, no energy model)::

    substrate slab (reviewed slab file, or the explicit / most stable facet
                    cut from a bulk crystal by ``genkai.modeling.surface.slab``)
    + user-supplied SAM molecule (CIF by default, any ASE format)
    -> anchor group detection (phosphonic acid, carboxylic acid, thiol, or
       user-given anchor atoms)
    -> user-selected binding mode: phosphonic mono/bi/tridentate, carboxylic
       mono/bidentate, thiol top/bridge/hollow/fcc/hcp
    -> rigid-body placement with explicit anchor-site bond lengths, tilt and
       azimuth, avoiding contacts with the slab and earlier molecules
    -> acidic H handled by policy (oxide surface: moved to a surface O as OH;
       metal surface: removed, e.g. thiolate)
    -> one extxyz frame per requested molecule count + JSON manifest

Every structure is an unrelaxed geometric candidate (evidence ``heuristic``).
Binding modes that the surface cannot host (e.g. tridentate phosphonate on
rutile (110), which has no three close five-fold cations) are reported as
infeasible instead of being forced.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import asdict, dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from ase import Atoms
from ase.constraints import FixAtoms
from ase.data import covalent_radii
from scipy.optimize import minimize
from scipy.spatial.transform import Rotation

from .sites import (
    classify_hollow,
    default_anchor_symbols,
    find_surface_sites,
    in_plane_mic,
    nearest_neighbor_distance,
    oxygen_acceptors,
    site_groups,
    surface_has_oxygen,
    unwrap_group,
)
from .structure_io import export_frames, read_molecule, sha256_of, write_frames, write_manifest
from .substrate import (
    Substrate,
    add_substrate_arguments,
    fixed_indices,
    parse_export,
    parse_ints,
    substrate_from_args,
    surface_area,
)

ANCHOR_KINDS = ("phosphonic", "carboxylic", "thiol")
BINDING_MODES: dict[str, dict[str, int]] = {
    "phosphonic": {"monodentate": 1, "bidentate": 2, "tridentate": 3},
    "carboxylic": {"monodentate": 1, "bidentate": 2},
    "thiol": {"top": 1, "bridge": 2, "hollow": 3, "fcc": 3, "hcp": 3},
}
# Kinds whose single anchor atom bonds to every atom of the site group.
SINGLE_ATOM_ANCHORS = {"thiol"}
ACIDIC_H_POLICIES = ("auto", "transfer", "remove", "keep")
PATTERNS = ("uniform", "clustered", "random")
CLASH_FRACTION = 0.6  # same rejection rule as the structure-only executor
CONTACT_OFFSET_A = 0.4  # molecule-slab soft repulsion below r_i + r_j + offset (covalent radii)
VDW_CONTACT_FRACTION = 0.8  # molecule-molecule soft repulsion below 0.8 x van der Waals radii sum


class SamBuildError(ValueError):
    """Raised when the requested SAM cannot be built as specified."""


# ---------------------------------------------------------------------------
# Molecule analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnchorGroup:
    kind: str
    center: int
    anchor_atoms: tuple[int, ...]  # acidic (H-bearing) atoms first
    acidic_h: tuple[tuple[int, int], ...]  # (anchor atom, hydrogen)
    source: str = "detected"

    def summary(self, molecule: Atoms) -> dict[str, Any]:
        symbols = molecule.get_chemical_symbols()
        return {
            "kind": self.kind,
            "source": self.source,
            "center": {"index": self.center, "symbol": symbols[self.center]},
            "anchor_atoms": [{"index": i, "symbol": symbols[i]} for i in self.anchor_atoms],
            "acidic_h": [{"anchor": a, "hydrogen": h} for a, h in self.acidic_h],
        }


def _neighbors(molecule: Atoms, scale: float = 1.2) -> list[set[int]]:
    # Molecules are covalent: keep every pair within the cutoff (no cation-anion rule).
    radii = covalent_radii[molecule.numbers]
    distances = molecule.get_all_distances()
    bonded = distances <= scale * (radii[:, None] + radii[None, :])
    np.fill_diagonal(bonded, False)
    return [set(np.flatnonzero(row).tolist()) for row in bonded]


def detect_anchor_groups(molecule: Atoms) -> list[AnchorGroup]:
    """Find phosphonic acid, carboxylic acid and thiol anchor groups."""
    symbols = molecule.get_chemical_symbols()
    neighbors = _neighbors(molecule)
    groups: list[AnchorGroup] = []

    def terminal_oxygens(center: int) -> list[int] | None:
        oxygens = [n for n in neighbors[center] if symbols[n] == "O"]
        for oxygen in oxygens:
            if any(symbols[n] != "H" and n != center for n in neighbors[oxygen]):
                return None  # ester / ether oxygen
        return oxygens

    def ordered(atoms: list[int]) -> tuple[tuple[int, ...], tuple[tuple[int, int], ...]]:
        acidic = [(a, h) for a in atoms for h in sorted(neighbors[a]) if symbols[h] == "H"]
        with_h = sorted({a for a, _ in acidic})
        rest = sorted(a for a in atoms if a not in with_h)
        return tuple(with_h + rest), tuple(acidic)

    for index, symbol in enumerate(symbols):
        if symbol == "P":
            oxygens = terminal_oxygens(index)
            others = [n for n in neighbors[index] if symbols[n] != "O"]
            if oxygens is not None and len(oxygens) == 3 and len(others) == 1 and symbols[others[0]] == "C":
                anchors, acidic = ordered(oxygens)
                groups.append(AnchorGroup("phosphonic", index, anchors, acidic))
        elif symbol == "C":
            oxygens = terminal_oxygens(index)
            others = [n for n in neighbors[index] if symbols[n] != "O"]
            if oxygens is not None and len(oxygens) == 2 and len(others) == 1:
                anchors, acidic = ordered(oxygens)
                groups.append(AnchorGroup("carboxylic", index, anchors, acidic))
        elif symbol == "S":
            heavy = [n for n in neighbors[index] if symbols[n] != "H"]
            hydrogens = [n for n in neighbors[index] if symbols[n] == "H"]
            if len(heavy) == 1 and symbols[heavy[0]] == "C" and len(hydrogens) <= 1:
                acidic = tuple((index, h) for h in hydrogens)
                groups.append(AnchorGroup("thiol", index, (index,), acidic))
    return groups


def resolve_anchor_group(
    molecule: Atoms,
    kind: str | None = None,
    anchor_atoms: Sequence[int] | None = None,
) -> AnchorGroup:
    """Pick the anchor group; ambiguity is an error, never a guess."""
    if kind is not None and kind not in ANCHOR_KINDS:
        raise SamBuildError(f"Unknown anchor kind {kind!r}; choose from {', '.join(ANCHOR_KINDS)}.")
    symbols = molecule.get_chemical_symbols()
    if anchor_atoms:
        if kind is None:
            raise SamBuildError("--anchor-atoms needs --anchor-kind to define the binding-mode semantics.")
        atoms = [int(i) for i in anchor_atoms]
        if any(i < 0 or i >= len(molecule) for i in atoms) or len(set(atoms)) != len(atoms):
            raise SamBuildError(f"Anchor atom indices {atoms} are invalid for a {len(molecule)}-atom molecule.")
        if kind in SINGLE_ATOM_ANCHORS and len(atoms) != 1:
            raise SamBuildError(f"A {kind} anchor is a single atom; got {len(atoms)} indices.")
        neighbors = _neighbors(molecule)
        acidic = tuple((a, h) for a in atoms for h in sorted(neighbors[a]) if symbols[h] == "H")
        with_h = sorted({a for a, _ in acidic})
        order = tuple(with_h + [a for a in atoms if a not in with_h])
        heavy = [n for a in atoms for n in neighbors[a] if symbols[n] != "H" and n not in atoms]
        center = max(set(heavy), key=heavy.count) if heavy and kind not in SINGLE_ATOM_ANCHORS else atoms[0]
        return AnchorGroup(kind, int(center), order, acidic, source="user_anchor_atoms")

    groups = detect_anchor_groups(molecule)
    found = ", ".join(f"{g.kind}@{symbols[g.center]}{g.center}" for g in groups) or "none"
    if kind is not None:
        groups = [g for g in groups if g.kind == kind]
    if not groups:
        raise SamBuildError(
            f"No {kind or 'phosphonic/carboxylic/thiol'} anchor group detected (found: {found}); "
            "give --anchor-kind and --anchor-atoms explicitly."
        )
    if len(groups) > 1:
        raise SamBuildError(
            f"Several anchor groups found ({found}); choose one with --anchor-kind, "
            "or --anchor-atoms if several groups share a kind."
        )
    return groups[0]


# ---------------------------------------------------------------------------
# Settings and results
# ---------------------------------------------------------------------------


@dataclass
class SamSettings:
    binding_mode: str
    coverage_counts: tuple[int, ...] | None = (1,)
    density_per_nm2: float | None = None
    tilt_deg: float = 0.0
    azimuth_deg: float = 0.0
    bond_length: float | None = None
    bond_tolerance: float = 0.35
    acidic_h: str = "auto"
    site_symbols: tuple[str, ...] | None = None
    surface_depth: float = 2.5
    max_span: float | None = None
    pattern: str = "uniform"
    seed: int = 42
    n_starts: int = 8
    vacuum_above: float = 15.0
    oh_length: float = 0.98

    def __post_init__(self) -> None:
        if self.acidic_h not in ACIDIC_H_POLICIES:
            raise SamBuildError(f"acidic_h must be one of {', '.join(ACIDIC_H_POLICIES)}.")
        if self.pattern not in PATTERNS:
            raise SamBuildError(f"pattern must be one of {', '.join(PATTERNS)}.")
        if (self.coverage_counts is None) == (self.density_per_nm2 is None):
            raise SamBuildError("Give exactly one of coverage counts or a density (molecules per nm^2).")
        if self.coverage_counts is not None and min(self.coverage_counts) < 1:
            raise SamBuildError("Coverage counts must be positive integers.")
        if self.density_per_nm2 is not None and self.density_per_nm2 <= 0:
            raise SamBuildError("The density must be positive.")
        if not 0.0 <= self.tilt_deg < 90.0:
            raise SamBuildError("The tilt angle must satisfy 0 <= tilt < 90 degrees.")
        if self.bond_tolerance <= 0 or self.n_starts < 1:
            raise SamBuildError("bond_tolerance and n_starts must be positive.")


@dataclass
class PlacedMolecule:
    fragment_id: int
    site_group: tuple[int, ...]
    bonds: list[dict[str, Any]]
    tilt_deg: float
    h_handling: list[dict[str, Any]]
    max_bond_deviation_A: float

    def summary(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SamFrameResult:
    requested_count: int
    atoms: Atoms | None
    molecules: list[PlacedMolecule] = field(default_factory=list)
    attempts: int = 0
    rejections: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    min_contact_ratio: float | None = None
    min_nonbonded_contact_ratio: float | None = None
    intermolecular: dict[str, float] | None = None
    designed: list[tuple[int, int]] = field(default_factory=list)  # (atom, partner) designed bonds, frame indices

    def summary(self, area_A2: float) -> dict[str, Any]:
        placed = len(self.molecules)
        return {
            "requested_count": self.requested_count,
            "placed_count": placed,
            "density_per_nm2": round(placed / (area_A2 / 100.0), 4),
            "site_groups_tried": self.attempts,
            "rejections": dict(self.rejections),
            "min_contact_ratio": self.min_contact_ratio,
            "min_nonbonded_contact_ratio": self.min_nonbonded_contact_ratio,
            "min_intermolecular_distance_A": self.intermolecular,
            "error": self.error,
            "n_atoms": len(self.atoms) if self.atoms is not None else None,
            "molecules": [molecule.summary() for molecule in self.molecules],
        }


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def target_axis(tilt_deg: float, azimuth_deg: float, cell: np.ndarray) -> np.ndarray:
    """Unit vector tilted from +z by ``tilt`` towards ``azimuth`` (from the a axis)."""
    a_dir = cell[0, :2] / np.linalg.norm(cell[0, :2])
    phi = np.radians(azimuth_deg) + np.arctan2(a_dir[1], a_dir[0])
    theta = np.radians(tilt_deg)
    return np.array([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)])


def _rotation_aligning(source: np.ndarray, target: np.ndarray) -> Rotation:
    source = source / np.linalg.norm(source)
    target = target / np.linalg.norm(target)
    axis = np.cross(source, target)
    sin = np.linalg.norm(axis)
    cos = float(np.dot(source, target))
    if sin < 1e-8:
        if cos > 0:
            return Rotation.identity()
        perpendicular = np.cross(source, [1.0, 0.0, 0.0])
        if np.linalg.norm(perpendicular) < 1e-6:
            perpendicular = np.cross(source, [0.0, 1.0, 0.0])
        return Rotation.from_rotvec(np.pi * perpendicular / np.linalg.norm(perpendicular))
    return Rotation.from_rotvec(axis / sin * np.arctan2(sin, cos))


def _environment_cloud(
    env: Atoms, centre: np.ndarray, radius: float, z_min: float
) -> tuple[np.ndarray, np.ndarray]:
    """Environment atoms above ``z_min`` (with in-plane images) within ``radius`` of ``centre`` laterally."""
    cell = env.cell.array
    positions = env.get_positions()
    widths = [surface_area(env) / np.linalg.norm(cell[1]), surface_area(env) / np.linalg.norm(cell[0])]
    n_a, n_b = (int(np.ceil(radius / w)) + 1 for w in widths)
    upper = positions[:, 2] >= z_min
    points, owners = [], []
    for i in range(-n_a, n_a + 1):
        for j in range(-n_b, n_b + 1):
            shifted = positions + i * cell[0] + j * cell[1]
            keep = upper & (np.linalg.norm(shifted[:, :2] - centre[:2], axis=1) <= radius)
            points.append(shifted[keep])
            owners.append(np.flatnonzero(keep))
    return np.vstack(points), np.concatenate(owners)


def _vdw_radii(numbers: np.ndarray) -> np.ndarray:
    from ase.data.vdw import vdw_radii

    radii = np.array([vdw_radii[z] for z in numbers], dtype=float)
    fallback = covalent_radii[numbers] + 0.8
    return np.where(np.isnan(radii), fallback, radii)


def _placement_objective_factory(
    local: np.ndarray,
    threshold: np.ndarray,
    bonds: list[tuple[int, np.ndarray, float]],
    axis_local: np.ndarray,
    axis_target: np.ndarray,
    cloud: np.ndarray,
    excluded: np.ndarray,
    origin: np.ndarray,
):
    def place(x: np.ndarray) -> np.ndarray:
        return Rotation.from_rotvec(x[:3]).apply(local) + origin + x[3:]

    def objective(x: np.ndarray) -> float:
        placed = place(x)
        bond = sum((np.linalg.norm(placed[a] - site) - d0) ** 2 for a, site, d0 in bonds)
        axis = 1.0 - float(np.dot(Rotation.from_rotvec(x[:3]).apply(axis_local), axis_target))
        distances = np.linalg.norm(placed[:, None, :] - cloud[None, :, :], axis=2)
        overlap = np.clip(threshold - distances, 0.0, None)
        overlap[excluded] = 0.0
        return 10.0 * bond + 5.0 * axis + 10.0 * float((overlap**2).sum())

    return place, objective


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class SamBuilder:
    """Place SAM molecules on a substrate slab with a chosen binding mode."""

    def __init__(self, substrate: Atoms, molecule: Atoms, group: AnchorGroup, settings: SamSettings):
        modes = BINDING_MODES[group.kind]
        if settings.binding_mode not in modes:
            raise SamBuildError(
                f"Binding mode {settings.binding_mode!r} is not defined for a {group.kind} anchor; "
                f"choose from {', '.join(modes)}."
            )
        self.substrate = substrate
        self.molecule = molecule
        self.group = group
        self.settings = settings
        self.n_sites = modes[settings.binding_mode]
        self.single_atom = group.kind in SINGLE_ATOM_ANCHORS
        if not self.single_atom and self.n_sites > len(group.anchor_atoms):
            raise SamBuildError(
                f"{settings.binding_mode} needs {self.n_sites} anchor atoms; the group has {len(group.anchor_atoms)}."
            )
        self.bonded_anchors = group.anchor_atoms[:1] if self.single_atom else group.anchor_atoms[: self.n_sites]
        self.h_policy = self._resolve_h_policy()
        self.template, self.template_map, self.removed_h = self._deprotonated_template()
        self.site_symbols = list(settings.site_symbols) if settings.site_symbols else default_anchor_symbols(substrate)
        missing = [s for s in self.site_symbols if s not in set(substrate.get_chemical_symbols())]
        if missing:
            raise SamBuildError(f"Site element(s) {', '.join(missing)} are not present in the slab.")
        self.sites = find_surface_sites(substrate, self.site_symbols, depth=settings.surface_depth)
        self.site_selection = "exposed and undercoordinated"
        if not self.sites:
            # The reference coordination is the slab maximum; in a slab too thin to have a
            # bulk-like interior (e.g. two CeO2(111) trilayers, every Ce 7-fold) nothing looks
            # undercoordinated, so fall back to exposed atoms and say so.
            self.sites = find_surface_sites(
                substrate, self.site_symbols, depth=settings.surface_depth, undercoordinated_only=False
            )
            self.site_selection = (
                "exposed only: no atom is undercoordinated relative to the slab maximum "
                "(slab may be too thin for a bulk-like reference coordination)"
            )
        if not self.sites:
            raise SamBuildError(
                f"No exposed {'/'.join(self.site_symbols)} atom found in the top {settings.surface_depth} A of the slab."
            )
        self.max_span = settings.max_span if settings.max_span is not None else self._default_span()
        self.groups = self._site_groups()
        self.axis_target = target_axis(settings.tilt_deg, settings.azimuth_deg, substrate.cell.array)
        self.acceptors = [s.index for s in oxygen_acceptors(substrate, settings.surface_depth)]

    # -- preparation ------------------------------------------------------

    def _resolve_h_policy(self) -> str:
        if self.settings.acidic_h != "auto":
            return self.settings.acidic_h
        return "transfer" if surface_has_oxygen(self.substrate, self.settings.surface_depth) else "remove"

    def _deprotonated_template(self) -> tuple[Atoms, list[int], list[tuple[int, int]]]:
        removed = [] if self.h_policy == "keep" else [
            (a, h) for a, h in self.group.acidic_h if a in self.bonded_anchors
        ]
        drop = {h for _, h in removed}
        keep = [i for i in range(len(self.molecule)) if i not in drop]
        return self.molecule[keep], keep, removed

    def _default_span(self) -> float:
        indices = [s.index for s in self.sites]
        if self.single_atom:
            if self.n_sites == 1 or len(indices) < 2:
                return 0.0
            return 1.25 * nearest_neighbor_distance(self.substrate, indices)
        anchors = self.molecule.positions[list(self.bonded_anchors)]
        spread = max(
            (np.linalg.norm(anchors[i] - anchors[j]) for i in range(len(anchors)) for j in range(i + 1, len(anchors))),
            default=0.0,
        )
        return spread + 2.0

    def _site_groups(self) -> list[tuple[int, ...]]:
        indices = [s.index for s in self.sites]
        groups = site_groups(self.substrate, indices, self.n_sites, self.max_span)
        mode = self.settings.binding_mode
        if mode in ("fcc", "hcp"):
            groups = [g for g in groups if classify_hollow(self.substrate, g) == mode]
        if not groups:
            raise SamBuildError(
                f"The surface has no {mode} site: no group of {self.n_sites} exposed "
                f"{'/'.join(self.site_symbols)} atom(s) within {self.max_span:.2f} A "
                f"({len(indices)} candidate atoms). Choose another binding mode or facet, or widen --max-span."
            )
        return groups

    def bond_length(self, anchor_symbol: str, site_symbol: str) -> float:
        if self.settings.bond_length is not None:
            return float(self.settings.bond_length)
        from ase.data import atomic_numbers

        return float(covalent_radii[atomic_numbers[anchor_symbol]] + covalent_radii[atomic_numbers[site_symbol]])

    # -- placement --------------------------------------------------------

    def _order_groups(self, rng: random.Random) -> list[int]:
        centres = np.array([unwrap_group(self.substrate, g).mean(axis=0) for g in self.groups])
        if self.settings.pattern == "random":
            order = list(range(len(self.groups)))
            rng.shuffle(order)
            return order
        deltas = (centres[None, :, :] - centres[:, None, :]).reshape(-1, 3)
        deltas[:, 2] = 0.0
        pairwise = np.linalg.norm(in_plane_mic(self.substrate, deltas), axis=1).reshape(len(centres), len(centres))
        start = int(np.argmin(np.linalg.norm(centres[:, :2] - centres[:, :2].mean(axis=0), axis=1)))
        if self.settings.pattern == "clustered":
            return [int(i) for i in np.argsort(pairwise[start], kind="stable")]
        order = [start]
        while len(order) < len(centres):
            distance = pairwise[:, order].min(axis=1)
            distance[order] = -np.inf
            order.append(int(np.argmax(distance)))
        return order

    def place(
        self,
        env: Atoms,
        group: tuple[int, ...],
        rng: np.random.Generator,
        axis_target: np.ndarray | None = None,
    ) -> tuple[np.ndarray, list, float, float] | None:
        """Best rigid placement of the template on ``group``; ``None`` if it fails the checks."""
        axis_target = self.axis_target if axis_target is None else axis_target
        template = self.template
        anchors_t = [self.template_map.index(a) for a in self.bonded_anchors]
        anchor_centroid = template.positions[anchors_t].mean(axis=0)
        local = template.get_positions() - anchor_centroid
        heavy = [i for i, s in enumerate(template.get_chemical_symbols()) if s != "H"] or list(range(len(template)))
        far = heavy[int(np.argmax(np.linalg.norm(local[heavy], axis=1)))]
        axis_local = local[far] / max(np.linalg.norm(local[far]), 1e-8)
        sites = unwrap_group(env, group)
        site_symbols = [env.get_chemical_symbols()[i] for i in group]
        origin = sites.mean(axis=0)
        mol_radius = float(np.linalg.norm(local, axis=1).max())
        cloud, owners = _environment_cloud(env, origin, mol_radius + 3.0, z_min=float(sites[:, 2].min()) - 3.0)
        # Slab atoms repel with covalent radii (+offset); earlier molecules with van der Waals radii.
        covalent_threshold = (
            covalent_radii[template.numbers][:, None] + covalent_radii[env.numbers[owners]][None, :] + CONTACT_OFFSET_A
        )
        vdw_threshold = VDW_CONTACT_FRACTION * (
            _vdw_radii(template.numbers)[:, None] + _vdw_radii(env.numbers[owners])[None, :]
        )
        is_molecule = owners >= len(self.substrate)
        threshold = np.where(is_molecule[None, :], vdw_threshold, covalent_threshold)
        anchor_symbols = template.get_chemical_symbols()

        site_images = []
        for k, index in enumerate(group):
            delta = np.linalg.norm(cloud - sites[k], axis=1)
            site_images.append(int(np.argmin(np.where(owners == index, delta, np.inf))))

        if self.single_atom:
            assignments = [[(anchors_t[0], k) for k in range(len(group))]]
        else:
            assignments = [list(zip(perm, range(len(group)))) for perm in permutations(anchors_t)]

        best: tuple[float, np.ndarray, list] | None = None
        for assignment in assignments:
            bonds = [
                (a, sites[k], self.bond_length(anchor_symbols[a], site_symbols[k])) for a, k in assignment
            ]
            excluded = np.zeros((len(template), len(cloud)), dtype=bool)
            for a, k in assignment:
                excluded[a, site_images[k]] = True
            place, objective = _placement_objective_factory(
                local, threshold, bonds, axis_local, axis_target, cloud, excluded, origin
            )
            base = _rotation_aligning(axis_local, axis_target)
            height = max(d0 for _, _, d0 in bonds)
            for start in range(self.settings.n_starts):
                spin = 2.0 * np.pi * start / self.settings.n_starts + rng.uniform(-0.2, 0.2)
                rotation = Rotation.from_rotvec(axis_target * spin) * base
                x0 = np.concatenate([rotation.as_rotvec(), [0.0, 0.0, height]])
                result = minimize(objective, x0, method="L-BFGS-B", options={"maxiter": 400})
                if best is None or result.fun < best[0]:
                    best = (float(result.fun), place(result.x), [(a, k, d0) for (a, _, d0), (_, k) in zip(bonds, assignment)])
        if best is None:
            return None
        _, positions, bond_spec = best
        bonds_report = []
        deviation = 0.0
        for a, k, d0 in bond_spec:
            distance = float(np.linalg.norm(positions[a] - sites[k]))
            deviation = max(deviation, abs(distance - d0))
            bonds_report.append(
                {
                    "anchor_atom": self.template_map[a],
                    "anchor_symbol": anchor_symbols[a],
                    "site_index": int(group[k]),
                    "site_symbol": site_symbols[k],
                    "target_A": round(d0, 4),
                    "distance_A": round(distance, 4),
                }
            )
        axis_placed = positions[far] - positions[anchors_t].mean(axis=0)
        tilt = float(np.degrees(np.arccos(np.clip(axis_placed[2] / np.linalg.norm(axis_placed), -1.0, 1.0))))
        return positions, bonds_report, deviation, tilt

    def _transfer_hydrogens(self, frame: Atoms, anchor_positions: dict[int, np.ndarray], used: set[int]) -> tuple[list[np.ndarray], list[dict[str, Any]]]:
        new_h: list[np.ndarray] = []
        report: list[dict[str, Any]] = []
        for anchor, hydrogen in self.removed_h:
            if self.h_policy == "remove":
                report.append({"hydrogen": hydrogen, "from_anchor": anchor, "action": "removed"})
                continue
            origin = anchor_positions[anchor]
            candidates = [i for i in self.acceptors if i not in used]
            distances = [
                float(np.linalg.norm(in_plane_mic(frame, frame.positions[i] - origin)[0])) for i in candidates
            ]
            placed = False
            for distance, oxygen in sorted(zip(distances, candidates)):
                if distance > 6.0:
                    break
                position = frame.positions[oxygen] + np.array([0.0, 0.0, self.settings.oh_length])
                others = np.delete(np.arange(len(frame)), oxygen)
                deltas = in_plane_mic(frame, frame.positions[others] - position)
                ratio = np.linalg.norm(deltas, axis=1) / (covalent_radii[1] + covalent_radii[frame.numbers[others]])
                extra = [np.linalg.norm(position - h) / (2 * covalent_radii[1]) for h in new_h]
                if ratio.min() >= 1.0 and all(value >= 1.0 for value in extra):
                    new_h.append(position)
                    used.add(oxygen)
                    report.append(
                        {
                            "hydrogen": hydrogen,
                            "from_anchor": anchor,
                            "action": "transferred",
                            "acceptor_O": int(oxygen),
                            "acceptor_distance_A": round(distance, 4),
                        }
                    )
                    placed = True
                    break
            if not placed:
                report.append({"hydrogen": hydrogen, "from_anchor": anchor, "action": "removed_no_acceptor"})
        return new_h, report

    def _new_state(self) -> dict[str, Any]:
        frame = self.substrate.copy()
        # Room above the slab before any minimum-image contact check, so a long
        # molecule is never folded back onto the slab bottom through c.
        extent = 2.0 * float(np.linalg.norm(self.template.positions - self.template.positions.mean(axis=0), axis=1).max())
        cell = frame.cell.array.copy()
        cell[2] = [0.0, 0.0, max(cell[2, 2], float(frame.positions[:, 2].max()) + extent + self.settings.vacuum_above)]
        frame.set_cell(cell)
        n_slab = len(frame)
        return {
            "frame": frame,
            "n_slab": n_slab,
            "fragment": np.zeros(n_slab, dtype=int),
            "role": np.zeros(n_slab, dtype=int),
            "used_sites": set(),
            "used_acceptors": set(),
            "designed": [],
        }

    def _try_add(
        self,
        state: dict[str, Any],
        group: tuple[int, ...],
        rng: np.random.Generator,
        result: SamFrameResult,
        axis_target: np.ndarray | None = None,
    ) -> bool:
        """Place one molecule on ``group``; update ``state`` and ``result`` on success."""
        result.attempts += 1
        placed = self.place(state["frame"], group, rng, axis_target)
        if placed is None:
            result.rejections["no_solution"] = result.rejections.get("no_solution", 0) + 1
            return False
        positions, bonds, deviation, tilt = placed
        if deviation > self.settings.bond_tolerance:
            result.rejections["bond_fit"] = result.rejections.get("bond_fit", 0) + 1
            return False
        frame = state["frame"]
        molecule = self.template.copy()
        molecule.set_positions(positions)
        trial = frame + molecule
        fragment_id = len(result.molecules) + 1
        trial_fragment = np.concatenate([state["fragment"], np.full(len(molecule), fragment_id)])
        if (ratio := _min_contact_ratio(trial, trial_fragment)) is not None and ratio < CLASH_FRACTION:
            result.rejections["overlap"] = result.rejections.get("overlap", 0) + 1
            return False
        anchor_positions = {a: positions[self.template_map.index(a)] for a in self.bonded_anchors}
        new_h, h_report = self._transfer_hydrogens(trial, anchor_positions, state["used_acceptors"])
        offset = len(frame)
        for bond in bonds:
            state["designed"].append((offset + self.template_map.index(bond["anchor_atom"]), bond["site_index"]))
        transferred = [entry for entry in h_report if entry["action"] == "transferred"]
        for k, entry in enumerate(transferred):
            state["designed"].append((len(trial) + k, entry["acceptor_O"]))
        if new_h:
            trial = trial + Atoms(["H"] * len(new_h), positions=new_h)
        anchor_flags = np.full(len(molecule), 2)
        for a in self.bonded_anchors:
            anchor_flags[self.template_map.index(a)] = 1
        state["frame"] = trial
        state["fragment"] = np.concatenate([trial_fragment, np.full(len(new_h), fragment_id)])
        state["role"] = np.concatenate([state["role"], anchor_flags, np.full(len(new_h), 3)])
        state["used_sites"].update(group)
        result.molecules.append(
            PlacedMolecule(
                fragment_id=fragment_id,
                site_group=tuple(int(i) for i in group),
                bonds=bonds,
                tilt_deg=round(tilt, 2),
                h_handling=h_report,
                max_bond_deviation_A=round(deviation, 4),
            )
        )
        return True

    def _complete(self, state: dict[str, Any], result: SamFrameResult) -> SamFrameResult:
        frame = self._finalize(state["frame"], state["fragment"], state["role"], state["n_slab"])
        count = len(result.molecules)
        result.atoms = frame
        result.designed = list(state["designed"])
        result.min_contact_ratio = _min_contact_ratio(frame, state["fragment"])
        result.min_nonbonded_contact_ratio = _min_contact_ratio(frame, state["fragment"], state["designed"])
        result.intermolecular = _intermolecular_contacts(frame, state["fragment"])
        frame.info.update(
            {
                "task": "surface_functionalization",
                "role": "sam_on_slab",
                "anchor_kind": self.group.kind,
                "binding_mode": self.settings.binding_mode,
                "molecule_count": count,
                "density_per_nm2": round(count / (surface_area(frame) / 100.0), 4),
                "min_contact_ratio": round(result.min_contact_ratio, 4) if result.min_contact_ratio is not None else -1.0,
            }
        )
        return result

    def build(self, count: int) -> SamFrameResult:
        """Place ``count`` molecules on site groups in pattern order (first group that fits)."""
        rng_py = random.Random(self.settings.seed)
        rng_np = np.random.default_rng(self.settings.seed)
        state = self._new_state()
        result = SamFrameResult(requested_count=count, atoms=None)
        max_attempts = 4 * count + 10
        for group_id in self._order_groups(rng_py):
            if len(result.molecules) == count or result.attempts >= max_attempts:
                break
            group = self.groups[group_id]
            if state["used_sites"] & set(group):
                continue
            self._try_add(state, group, rng_np, result)
        if len(result.molecules) < count:
            result.error = (
                f"Placed {len(result.molecules)} of {count} molecules ({result.attempts} site groups tried, "
                f"{len(self.groups)} available); lower the count, change tilt/binding mode, or enlarge the cell."
            )
            return result
        return self._complete(state, result)

    def assemble(self, placements: Sequence[tuple[tuple[int, ...], float, float]], seed: int | None = None) -> SamFrameResult:
        """Place one molecule per explicit (site group, tilt deg, azimuth deg); no fallback groups."""
        rng_np = np.random.default_rng(self.settings.seed if seed is None else seed)
        state = self._new_state()
        result = SamFrameResult(requested_count=len(placements), atoms=None)
        for group, tilt, azimuth in placements:
            if state["used_sites"] & set(group):
                result.error = f"Site group {tuple(group)} shares sites with an earlier molecule."
                return result
            axis = target_axis(tilt, azimuth, self.substrate.cell.array)
            if not self._try_add(state, tuple(group), rng_np, result, axis):
                reason = ", ".join(result.rejections) or "placement failed"
                result.error = f"Could not place a molecule on site group {tuple(group)} ({reason})."
                return result
        return self._complete(state, result)

    def _finalize(self, frame: Atoms, fragment: np.ndarray, role: np.ndarray, n_slab: int) -> Atoms:
        fixed = fixed_indices(self.substrate)
        tags = np.concatenate([self.substrate.get_tags(), np.full(len(frame) - n_slab, 2)])
        frame.set_tags(tags)
        frame.set_constraint(FixAtoms(indices=fixed) if fixed else [])
        frame.new_array("fragment_id", fragment.astype(int))
        frame.new_array("sam_role", role.astype(int))
        cell = frame.cell.array.copy()
        needed = float(frame.positions[:, 2].max()) + self.settings.vacuum_above
        cell[2] = [0.0, 0.0, max(float(self.substrate.cell.array[2, 2]), needed)]
        frame.set_cell(cell)
        return frame


def _intermolecular_contacts(atoms: Atoms, fragments: np.ndarray) -> dict[str, float] | None:
    """Shortest H-H, C-C and overall distances between different molecules (minimum image)."""
    molecules = fragments > 0
    if len(set(fragments[molecules].tolist())) < 2:
        return None
    distances = atoms.get_all_distances(mic=True)
    symbols = np.array(atoms.get_chemical_symbols())
    pair = (fragments[:, None] != fragments[None, :]) & molecules[:, None] & molecules[None, :]
    report = {"any": round(float(distances[pair].min()), 4)}
    for a, b in (("H", "H"), ("C", "C")):
        mask = pair & (symbols[:, None] == a) & (symbols[None, :] == b)
        if mask.any():
            report[f"{a}-{b}"] = round(float(distances[mask].min()), 4)
    return report


def _min_contact_ratio(
    atoms: Atoms, fragments: np.ndarray, designed: Sequence[tuple[int, int]] = ()
) -> float | None:
    """Smallest d / (r_i + r_j) over pairs of different fragments (minimum image).

    ``designed`` pairs (anchor-site bonds, transferred H on its acceptor O) are
    left out, so the value measures unintended contacts only.
    """
    if len(set(fragments.tolist())) < 2:
        return None
    distances = atoms.get_all_distances(mic=True)
    radii = covalent_radii[atoms.numbers]
    ratio = distances / (radii[:, None] + radii[None, :])
    different = fragments[:, None] != fragments[None, :]
    for i, j in designed:
        different[i, j] = different[j, i] = False
    return float(ratio[different].min()) if different.any() else None


# ---------------------------------------------------------------------------
# Run (programmatic API) and CLI
# ---------------------------------------------------------------------------


@dataclass
class SamRunResult:
    frames: list[Atoms]
    manifest: dict[str, Any]
    structures_path: Path
    manifest_path: Path
    exported: list[Path]


def resolve_counts(settings: SamSettings, area_A2: float) -> tuple[list[int], dict[str, Any]]:
    if settings.coverage_counts is not None:
        return sorted(set(int(c) for c in settings.coverage_counts)), {"source": "counts"}
    area_nm2 = area_A2 / 100.0
    count = max(1, int(round(settings.density_per_nm2 * area_nm2)))
    return [count], {
        "source": "density",
        "requested_density_per_nm2": settings.density_per_nm2,
        "surface_area_nm2": round(area_nm2, 4),
        "rounded_count": count,
        "achieved_density_per_nm2": round(count / area_nm2, 4),
    }


def run_sam(
    substrate: Substrate,
    molecule_path: str | Path,
    settings: SamSettings,
    output_dir: str | Path,
    *,
    molecule_format: str | None = None,
    anchor_kind: str | None = None,
    anchor_atoms: Sequence[int] | None = None,
    export: Sequence[str] = ("cif",),
) -> SamRunResult:
    """Build SAM frames for every requested count and write extxyz + manifest."""
    outdir = Path(output_dir)
    molecule, molecule_format_used = read_molecule(molecule_path, molecule_format)
    group = resolve_anchor_group(molecule, anchor_kind, anchor_atoms)
    builder = SamBuilder(substrate.atoms, molecule, group, settings)
    area = surface_area(substrate.atoms)
    counts, count_record = resolve_counts(settings, area)

    clean = substrate.atoms.copy()
    clean.new_array("fragment_id", np.zeros(len(clean), dtype=int))
    clean.new_array("sam_role", np.zeros(len(clean), dtype=int))
    clean.info.update({"task": "surface_functionalization", "role": "clean_slab", "molecule_count": 0})
    frames = [clean]
    frame_reports = []
    for count in counts:
        result = builder.build(count)
        frame_reports.append(result.summary(area))
        if result.atoms is not None:
            result.atoms.info["frame_id"] = len(frames)
            frames.append(result.atoms)
    clean.info["frame_id"] = 0

    structures_path = write_frames(outdir / "sam_structures.extxyz", frames)
    exported = export_frames(frames, outdir / "exports", "sam", export) if export else []
    warnings = [issue.model_dump() for issue in substrate.warnings]
    if builder.site_selection.startswith("exposed only"):
        warnings.append({"code": "sites_not_undercoordinated", "message": builder.site_selection})
    failed = [report for report in frame_reports if report["error"]]
    manifest = {
        "schema_version": "1.0",
        "generator": "genkai.modeling.surface.sam",
        "mode": "structure-only",
        "calculator": "none",
        "evidence_level": "heuristic",
        "scientific_calculation_started": False,
        "energies_available": False,
        "note": "Unrelaxed geometric SAM candidates; bond lengths are covalent-radius targets, not optimized values.",
        "substrate": substrate.record,
        "molecule": {
            "path": Path(molecule_path).as_posix(),
            "format": molecule_format_used,
            "sha256": sha256_of(molecule_path),
            "formula": molecule.get_chemical_formula(mode="hill"),
            "n_atoms": len(molecule),
            "anchor_group": group.summary(molecule),
            "bonded_anchor_atoms": list(builder.bonded_anchors),
            "deposited_formula": builder.template.get_chemical_formula(mode="hill"),
        },
        "binding": {
            "mode": settings.binding_mode,
            "sites_per_molecule": builder.n_sites,
            "single_anchor_atom": builder.single_atom,
            "site_symbols": builder.site_symbols,
            "site_selection": builder.site_selection,
            "candidate_sites": [site.summary() for site in builder.sites],
            "site_groups_available": len(builder.groups),
            "max_span_A": round(builder.max_span, 4),
            "acidic_h_policy": builder.h_policy,
            "acidic_h_requested": settings.acidic_h,
        },
        "coverage": count_record,
        "settings": asdict(settings),
        "frames": [
            {"frame_id": 0, "role": "clean_slab", "n_atoms": len(clean)},
            *[{"frame_id": f.info["frame_id"], "role": "sam_on_slab", "molecule_count": f.info["molecule_count"]} for f in frames[1:]],
        ],
        "builds": frame_reports,
        "files": {
            "structures": structures_path.as_posix(),
            "exports": [path.as_posix() for path in exported],
        },
        "validation": {
            "warnings": warnings,
            "failed_counts": [report["requested_count"] for report in failed],
        },
        "conventions": {
            "tags": "0 = fixed subsurface, 1 = free slab, 2 = SAM atoms and transferred H",
            "fragment_id": "0 = slab, k = k-th molecule (with its transferred H)",
            "sam_role": "0 = slab, 1 = bonded anchor atom, 2 = other molecule atom, 3 = transferred H",
        },
    }
    manifest_path = write_manifest(outdir / "sam_manifest.json", manifest)
    return SamRunResult(frames, manifest, structures_path, manifest_path, exported)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build unrelaxed SAM structures on a stable surface (geometry only, no energy model)."
    )
    add_substrate_arguments(parser)
    parser.add_argument("--molecule", type=Path, required=True, help="SAM molecule file (CIF by default; any ASE format).")
    parser.add_argument("--molecule-format", default=None)
    parser.add_argument("--anchor-kind", choices=ANCHOR_KINDS, default=None, help="Required when several groups exist.")
    parser.add_argument("--anchor-atoms", default=None, help="0-based molecule indices of the anchor atom(s), e.g. 3,4,5.")
    parser.add_argument(
        "--binding-mode",
        required=True,
        help="phosphonic: monodentate|bidentate|tridentate; carboxylic: monodentate|bidentate; "
        "thiol: top|bridge|hollow|fcc|hcp.",
    )
    coverage = parser.add_mutually_exclusive_group(required=True)
    coverage.add_argument("--counts", help="Molecule counts per cell, e.g. 1,2,4 (one frame each).")
    coverage.add_argument("--density", type=float, help="Target molecules per nm^2 (rounded to an integer count).")
    parser.add_argument("--tilt", type=float, default=0.0, help="Molecular axis tilt from the surface normal (deg).")
    parser.add_argument("--azimuth", type=float, default=0.0, help="Tilt direction from the cell a axis (deg).")
    parser.add_argument("--bond-length", type=float, default=None, help="Anchor-site bond length (A); default covalent radii sum.")
    parser.add_argument("--bond-tolerance", type=float, default=0.35)
    parser.add_argument(
        "--acidic-h",
        choices=ACIDIC_H_POLICIES,
        default="auto",
        help="auto: move to a surface O as OH on O-containing surfaces, remove otherwise.",
    )
    parser.add_argument("--site-symbols", default=None, help="Surface elements the anchor binds to, e.g. Sn or Au.")
    parser.add_argument("--surface-depth", type=float, default=2.5)
    parser.add_argument("--max-span", type=float, default=None, help="Largest distance between atoms of one site group (A).")
    parser.add_argument("--pattern", choices=PATTERNS, default="uniform")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-starts", type=int, default=8)
    parser.add_argument("--export", default="cif", help="Comma-separated export formats (cif, vasp) or 'none'.")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        settings = SamSettings(
            binding_mode=args.binding_mode,
            coverage_counts=parse_ints(args.counts),
            density_per_nm2=args.density,
            tilt_deg=args.tilt,
            azimuth_deg=args.azimuth,
            bond_length=args.bond_length,
            bond_tolerance=args.bond_tolerance,
            acidic_h=args.acidic_h,
            site_symbols=tuple(s.strip() for s in args.site_symbols.split(",")) if args.site_symbols else None,
            surface_depth=args.surface_depth,
            max_span=args.max_span,
            pattern=args.pattern,
            seed=args.seed,
            n_starts=args.n_starts,
        )
        substrate = substrate_from_args(args)
        result = run_sam(
            substrate,
            args.molecule,
            settings,
            args.output_dir,
            molecule_format=args.molecule_format,
            anchor_kind=args.anchor_kind,
            anchor_atoms=parse_ints(args.anchor_atoms),
            export=parse_export(args.export),
        )
    except (SamBuildError, ValueError, FileNotFoundError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    manifest = result.manifest
    substrate_record = manifest["substrate"]
    print(f"Substrate: {substrate_record['formula']} facet={substrate_record.get('facet')} via {substrate_record['facet_source']}")
    print(f"Anchor: {manifest['molecule']['anchor_group']['kind']}, binding mode {manifest['binding']['mode']}, "
          f"acidic H {manifest['binding']['acidic_h_policy']}")
    for build in manifest["builds"]:
        status = "ok" if not build["error"] else f"FAILED: {build['error']}"
        print(f"  count {build['requested_count']}: placed {build['placed_count']} "
              f"({build['density_per_nm2']} nm^-2), min non-bonded contact ratio "
              f"{build['min_nonbonded_contact_ratio']} - {status}")
    print(f"Wrote {result.structures_path} ({len(result.frames)} frames) and {result.manifest_path}")
    return 0 if not manifest["validation"]["failed_counts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
