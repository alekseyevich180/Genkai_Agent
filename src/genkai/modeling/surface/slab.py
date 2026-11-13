"""Bulk-to-slab generation built on pymatgen.

The pipeline turns a bulk crystal into a vacuum slab ready for surface
modeling:

1. Convert the bulk to its conventional standard cell, so Miller indices mean
   what papers mean. Materials Project often returns primitive cells, where
   ``(1, 0, 0)`` of an fcc primitive basis is a conventional ``{111}`` plane.
2. Resolve the facet: explicit input -> surface-energy screening with an
   injected energy function (Wulff area fraction) -> reviewed registry ->
   stop for manual review.
3. Enumerate terminations with ``SlabGenerator`` and record stoichiometry,
   symmetry and polarity. Polarity needs oxidation states; without them
   pymatgen's ``Slab.is_polar`` always returns ``False``.
4. Make ``c`` orthogonal to the surface, tile laterally to a minimum width,
   tag atoms (0 = fixed subsurface, 1 = free surface region, the Open
   Catalyst convention) and fix the bottom of the slab.
5. Validate vacuum, interatomic distances and constraints.

The energy function is injected (``Callable[[Atoms], float]``), so this module
does not depend on a particular MLIP runtime.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
from ase import Atoms
from ase.constraints import FixAtoms
from pymatgen.analysis.wulff import WulffShape
from pymatgen.core import Composition, Structure
from pymatgen.core.surface import (
    Slab,
    SlabGenerator,
    get_symmetrically_distinct_miller_indices,
)
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from genkai.contracts.validation import ValidationIssue, ValidationReport


EV_PER_A2_TO_J_PER_M2 = 16.021766208
MillerIndex = tuple[int, int, int]
EnergyFunction = Callable[[Atoms], float]


# ---------------------------------------------------------------------------
# Reviewed stable-facet registry (fallback when no energies are computed)
# ---------------------------------------------------------------------------

STABLE_FACETS_BY_FORMULA: dict[str, MillerIndex] = {
    "CeO2": (1, 1, 1),
    "TiO2": (1, 1, 0),
    "SnO2": (1, 1, 0),
    "RuO2": (1, 1, 0),
    "IrO2": (1, 1, 0),
}

# Space group -> {stoichiometry signature: facet}. The signature is the sorted
# tuple of reduced element amounts, e.g. (1,) for elements, (1, 1) for AB and
# (1, 2) for AB2; ``None`` matches any composition. Fm-3m hosts prototypes with
# different stable facets, so it is split: fcc metals and fluorite/antifluorite
# AB2 expose (111), whereas rock-salt AB oxides (MgO, NiO, CoO) expose the
# non-polar (100); their (111) is polar. Other Fm-3m compositions (double
# perovskites, Heusler alloys, ...) are not registered and require review.
STABLE_FACETS_BY_SPACEGROUP: dict[str, dict[tuple[int, ...] | None, MillerIndex]] = {
    "Fm-3m": {
        (1,): (1, 1, 1),
        (1, 1): (1, 0, 0),
        (1, 2): (1, 1, 1),
    },
    "Im-3m": {None: (1, 1, 0)},
    "P6_3/mmc": {None: (0, 0, 1)},
    "P63/mmc": {None: (0, 0, 1)},
    "P4_2/mnm": {None: (1, 1, 0)},
    "P42/mnm": {None: (1, 1, 0)},
}

STRUCTURE_FAMILY_LABELS: dict[tuple[str, tuple[int, ...] | None], str] = {
    ("Fm-3m", (1,)): "fcc element",
    ("Fm-3m", (1, 1)): "rock-salt AB",
    ("Fm-3m", (1, 2)): "fluorite/antifluorite AB2",
}


@dataclass(frozen=True)
class FacetResolution:
    miller_index: tuple[int, ...]
    source: str
    reason: str


def canonical_formula(formula: str) -> str:
    return Composition(formula).reduced_formula


def stoichiometry_signature(formula: str) -> tuple[int, ...] | None:
    """Sorted reduced integer amounts, e.g. MgO -> (1, 1), CeO2 -> (1, 2)."""
    amounts = Composition(formula).reduced_composition.get_el_amt_dict().values()
    if any(abs(amount - round(amount)) > 1e-6 for amount in amounts):
        return None
    return tuple(sorted(int(round(amount)) for amount in amounts))


def parse_miller_index(value: str | Sequence[int]) -> MillerIndex:
    """Parse ``"1,1,1"``, ``"(1 1 1)"``, compact ``"(111)"`` / ``"(1-10)"``, a
    sequence, or the four-index hexagonal form such as ``"(10-10)"`` or ``"0001"``."""
    if isinstance(value, str):
        text = value.strip().strip("()[]{}").strip()
        if re.fullmatch(r"(?:-?\d){3,4}", text):
            # Compact notation: one digit per index, "-" marks a negative index.
            values = tuple(int(item) for item in re.findall(r"-?\d", text))
        else:
            values = tuple(int(item) for item in re.findall(r"-?\d+", text))
    else:
        values = tuple(int(item) for item in value)
    if len(values) == 4:
        h, k, i, ell = values
        if h + k + i != 0:
            raise ValueError(f"Invalid Miller-Bravais index: {value!r}")
        values = (h, k, ell)
    if len(values) != 3 or not any(values):
        raise ValueError(f"Invalid Miller index: {value!r}")
    return values  # type: ignore[return-value]


def resolve_stable_facet(
    formula: str,
    spacegroup_symbol: str | None,
    explicit_facet: str | Sequence[int] | None = None,
) -> FacetResolution:
    """Explicit facet, else the reviewed registry, else stop for manual review."""
    if explicit_facet is not None:
        return FacetResolution(
            parse_miller_index(explicit_facet),
            "explicit",
            "Facet was explicitly supplied from paper evidence or user input.",
        )

    normalized_formula = canonical_formula(formula)
    if normalized_formula in STABLE_FACETS_BY_FORMULA:
        return FacetResolution(
            STABLE_FACETS_BY_FORMULA[normalized_formula],
            "stable_facet_registry",
            f"Registered commonly stable facet for {normalized_formula}.",
        )

    normalized_spg = (spacegroup_symbol or "").replace(" ", "")
    signature = stoichiometry_signature(normalized_formula)
    for symbol, facets_by_signature in STABLE_FACETS_BY_SPACEGROUP.items():
        if normalized_spg != symbol.replace(" ", ""):
            continue
        for key in (signature, None):
            if key in facets_by_signature:
                family = STRUCTURE_FAMILY_LABELS.get((symbol, key))
                family_text = f" ({family})" if family else ""
                return FacetResolution(
                    facets_by_signature[key],
                    "structure_family_registry",
                    f"Facet selected from the registered structure family {spacegroup_symbol}{family_text}.",
                )

    raise ValueError(
        f"No stable facet is registered for {normalized_formula} ({spacegroup_symbol or 'unknown space group'}). "
        "Provide a facet from paper evidence, or rank facets by computed surface energy."
    )


# ---------------------------------------------------------------------------
# Settings and candidates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlabSettings:
    """Geometry and constraint settings; lengths in Angstrom."""

    min_slab_size: float = 12.0
    min_vacuum_size: float = 15.0
    min_lateral_size: float = 8.0
    repeat_xy: tuple[int, int] | None = None
    fixed_fraction: float = 0.5
    fixed_layers: int | None = None
    layer_tolerance: float = 0.3
    min_interatomic_distance: float = 0.7
    symprec: float = 0.1

    def __post_init__(self) -> None:
        if self.min_slab_size <= 0 or self.min_vacuum_size <= 0 or self.min_lateral_size <= 0:
            raise ValueError("Slab, vacuum and lateral sizes must be positive.")
        if not 0.0 <= self.fixed_fraction < 1.0:
            raise ValueError("fixed_fraction must satisfy 0 <= fixed_fraction < 1.")
        if self.fixed_layers is not None and self.fixed_layers < 0:
            raise ValueError("fixed_layers must be >= 0.")
        if self.repeat_xy is not None and (len(self.repeat_xy) != 2 or min(self.repeat_xy) < 1):
            raise ValueError("repeat_xy requires two positive integers.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_slab_size_A": self.min_slab_size,
            "min_vacuum_size_A": self.min_vacuum_size,
            "min_lateral_size_A": self.min_lateral_size,
            "repeat_xy": list(self.repeat_xy) if self.repeat_xy else None,
            "fixed_fraction": self.fixed_fraction,
            "fixed_layers": self.fixed_layers,
            "layer_tolerance_A": self.layer_tolerance,
            "min_interatomic_distance_A": self.min_interatomic_distance,
            "symprec": self.symprec,
        }


@dataclass
class SlabCandidate:
    miller_index: MillerIndex
    termination_index: int
    slab: Slab = field(repr=False)
    stoichiometric: bool
    symmetric: bool
    polar: bool | None
    surface_energy_J_m2: float | None = None
    surface_energy_note: str | None = None

    def sort_key(self) -> tuple[Any, ...]:
        """Non-polar, stoichiometric, low surface energy, symmetric, small first."""
        energy = self.surface_energy_J_m2
        return (
            self.polar is True,
            not self.stoichiometric,
            energy is None,
            energy if energy is not None else 0.0,
            not self.symmetric,
            len(self.slab),
            self.termination_index,
        )

    def summary(self) -> dict[str, Any]:
        return {
            "miller_index": list(self.miller_index),
            "termination_index": self.termination_index,
            "shift": round(float(self.slab.shift), 6),
            "n_atoms": len(self.slab),
            "formula": self.slab.composition.element_composition.formula,
            "stoichiometric": self.stoichiometric,
            "symmetric": self.symmetric,
            "polar": self.polar,
            "surface_energy_J_m2": (
                round(self.surface_energy_J_m2, 6) if self.surface_energy_J_m2 is not None else None
            ),
            "surface_energy_note": self.surface_energy_note,
        }


@dataclass
class FacetScreening:
    max_index: int
    method: str
    selected: MillerIndex
    facets: list[dict[str, Any]]
    candidates: dict[MillerIndex, list[SlabCandidate]] = field(repr=False)
    note: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "max_index": self.max_index,
            "method": self.method,
            "selected": list(self.selected),
            "facets": self.facets,
            "note": self.note,
        }


@dataclass
class SlabBuildResult:
    atoms: Atoms
    bulk: Structure
    facet: FacetResolution
    selected: SlabCandidate
    candidates: list[SlabCandidate]
    screening: FacetScreening | None
    validation: ValidationReport
    geometry: dict[str, Any]
    settings: SlabSettings

    def manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "generator": "genkai.modeling.surface.slab (pymatgen SlabGenerator)",
            "bulk": {
                "formula": self.bulk.composition.reduced_formula,
                "spacegroup_symbol": SpacegroupAnalyzer(
                    self.bulk, symprec=self.settings.symprec
                ).get_space_group_symbol(),
                "cell": "conventional_standard",
                "n_atoms": len(self.bulk),
            },
            "facet": {
                "miller_index": list(self.facet.miller_index),
                "selection_source": self.facet.source,
                "reason": self.facet.reason,
            },
            "facet_screening": self.screening.summary() if self.screening else None,
            "selected_termination": self.selected.summary(),
            "terminations": [candidate.summary() for candidate in self.candidates],
            "slab": self.geometry,
            "settings": self.settings.as_dict(),
            "validation": self.validation.model_dump(),
            "validation_passed": self.validation.passed,
        }


# ---------------------------------------------------------------------------
# Bulk preparation and termination enumeration
# ---------------------------------------------------------------------------


def largest_periodic_gap(structure: Structure) -> float:
    """Largest empty gap (Angstrom) along any lattice vector; large values mean vacuum."""
    fractional = np.mod(structure.frac_coords, 1.0)
    largest = 0.0
    for axis, length in enumerate(structure.lattice.abc):
        ordered = np.sort(fractional[:, axis])
        gaps = np.diff(np.r_[ordered, ordered[0] + 1.0])
        largest = max(largest, float(gaps.max() * length))
    return largest


def conventional_bulk(structure: Structure, symprec: float = 0.1, max_gap: float = 5.0) -> Structure:
    """Conventional standard cell; Miller indices in papers refer to this setting.

    Raises ``ValueError`` for slab-like input (a vacuum gap above ``max_gap``),
    because cutting a slab out of a slab gives a meaningless surface.
    """
    plain = structure.copy()
    plain.remove_oxidation_states()
    gap = largest_periodic_gap(plain)
    if gap > max_gap:
        raise ValueError(
            f"Bulk input has a {gap:.1f} A empty gap and looks like a slab, not a bulk crystal. "
            "Provide the bulk unit cell (e.g. from Materials Project) instead."
        )
    return SpacegroupAnalyzer(plain, symprec=symprec).get_conventional_standard_structure()


def _with_oxidation_states(structure: Structure) -> tuple[Structure, bool]:
    """Decorate with oxidation states so slab polarity can be evaluated.

    Elements and all-metal compositions are treated as charge neutral (metals
    screen surface dipoles). Compounds without a valid oxidation-state guess
    return ``polarity_known=False`` rather than silently reporting non-polar.
    """
    decorated = structure.copy()
    composition = structure.composition.element_composition
    elements = composition.elements
    if len(elements) == 1 or all(element.is_metal for element in elements):
        decorated.add_oxidation_state_by_element({element.symbol: 0 for element in elements})
        return decorated, True
    guesses = composition.reduced_composition.oxi_state_guesses()
    if not guesses:
        return structure.copy(), False
    decorated.add_oxidation_state_by_element(dict(guesses[0]))
    return decorated, True


def enumerate_terminations(
    bulk: Structure,
    miller_index: Sequence[int],
    settings: SlabSettings,
) -> list[SlabCandidate]:
    """All distinct terminations of one facet. ``bulk`` must be the conventional cell."""
    miller = parse_miller_index(miller_index)
    decorated, polarity_known = _with_oxidation_states(bulk)
    generator = SlabGenerator(
        decorated,
        miller,
        settings.min_slab_size,
        settings.min_vacuum_size,
        center_slab=True,
        in_unit_planes=False,
        primitive=True,
        reorient_lattice=True,
    )
    bulk_composition = bulk.composition.element_composition.reduced_composition
    candidates = []
    for index, slab in enumerate(generator.get_slabs(symmetrize=False)):
        composition = slab.composition.element_composition.reduced_composition
        candidates.append(
            SlabCandidate(
                miller_index=miller,
                termination_index=index,
                slab=slab,
                stoichiometric=composition.almost_equals(bulk_composition),
                symmetric=bool(slab.is_symmetric()),
                polar=bool(slab.is_polar()) if polarity_known else None,
            )
        )
    if not candidates:
        raise ValueError(f"No slabs could be generated for facet {miller}.")
    return candidates


# ---------------------------------------------------------------------------
# Surface energies and facet screening
# ---------------------------------------------------------------------------


def _plain_atoms(structure: Structure) -> Atoms:
    plain = structure.copy()
    plain.remove_oxidation_states()
    return Atoms(
        symbols=[site.specie.symbol for site in plain],
        positions=plain.cart_coords,
        cell=plain.lattice.matrix,
        pbc=True,
    )


def energy_function_from_calculator(
    calculator: Any,
    *,
    relax_steps: int = 0,
    fmax: float = 0.05,
) -> EnergyFunction:
    """Wrap an ASE calculator; optionally relax positions (constraints respected)."""

    def energy(atoms: Atoms) -> float:
        work = atoms.copy()
        work.calc = calculator
        if relax_steps > 0:
            from ase.optimize import LBFGS

            LBFGS(work, logfile=None).run(fmax=fmax, steps=relax_steps)
        return float(work.get_potential_energy())

    return energy


def bulk_energy_per_atom(bulk: Structure, energy_fn: EnergyFunction) -> float:
    atoms = _plain_atoms(bulk)
    return float(energy_fn(atoms)) / len(atoms)


def assign_surface_energy(
    candidate: SlabCandidate,
    energy_fn: EnergyFunction,
    bulk_energy: float,
) -> None:
    """gamma = (E_slab - N * e_bulk) / (2 A); defined only for stoichiometric slabs."""
    if candidate.polar is True:
        candidate.surface_energy_note = "polar termination; excluded from surface-energy ranking"
        return
    if not candidate.stoichiometric:
        candidate.surface_energy_note = (
            "non-stoichiometric termination; surface energy requires chemical potentials"
        )
        return
    atoms = _plain_atoms(candidate.slab)
    energy = float(energy_fn(atoms))
    gamma = (energy - len(atoms) * bulk_energy) / (2.0 * candidate.slab.surface_area)
    candidate.surface_energy_J_m2 = gamma * EV_PER_A2_TO_J_PER_M2
    candidate.surface_energy_note = (
        None if candidate.symmetric else "asymmetric slab; value is the average of both terminations"
    )


def screen_facets(
    bulk: Structure,
    settings: SlabSettings,
    energy_fn: EnergyFunction,
    max_index: int = 1,
) -> FacetScreening:
    """Rank symmetry-distinct facets by surface energy and Wulff area fraction."""
    if max_index < 1:
        raise ValueError("max_index must be >= 1.")
    bulk_energy = bulk_energy_per_atom(bulk, energy_fn)
    candidates_by_facet: dict[MillerIndex, list[SlabCandidate]] = {}
    rows: list[dict[str, Any]] = []
    for miller in get_symmetrically_distinct_miller_indices(bulk, max_index):
        miller = tuple(int(value) for value in miller)
        candidates = enumerate_terminations(bulk, miller, settings)
        for candidate in candidates:
            assign_surface_energy(candidate, energy_fn, bulk_energy)
        candidates.sort(key=SlabCandidate.sort_key)
        candidates_by_facet[miller] = candidates
        best = candidates[0]
        rows.append(
            {
                "miller_index": list(miller),
                "surface_energy_J_m2": best.surface_energy_J_m2,
                "termination_index": best.termination_index,
                "terminations": len(candidates),
            }
        )

    valid = [
        (tuple(row["miller_index"]), row["surface_energy_J_m2"])
        for row in rows
        if row["surface_energy_J_m2"] is not None
    ]
    if not valid:
        raise ValueError(
            "No facet up to the requested Miller index has a defined surface energy "
            "(all terminations are polar or non-stoichiometric). Provide a facet explicitly."
        )

    method = "wulff_area_fraction"
    note = None
    fractions: dict[MillerIndex, float] = {}
    if any(gamma <= 0 for _, gamma in valid):
        method = "lowest_surface_energy"
        note = "Non-positive surface energy found; Wulff construction skipped. Check the energy model."
    else:
        try:
            wulff = WulffShape(bulk.lattice, [miller for miller, _ in valid], [gamma for _, gamma in valid])
            fractions = {
                tuple(int(value) for value in miller): float(fraction)
                for miller, fraction in wulff.area_fraction_dict.items()
            }
        except Exception as exc:  # degenerate Wulff shapes
            method = "lowest_surface_energy"
            note = f"Wulff construction failed ({exc}); fell back to the lowest surface energy."

    if fractions:
        selected = max(fractions, key=fractions.__getitem__)
    else:
        selected = min(valid, key=lambda item: item[1])[0]
    for row in rows:
        fraction = fractions.get(tuple(row["miller_index"]))
        row["wulff_area_fraction"] = round(fraction, 6) if fraction is not None else None
        if row["surface_energy_J_m2"] is not None:
            row["surface_energy_J_m2"] = round(row["surface_energy_J_m2"], 6)
    return FacetScreening(
        max_index=max_index,
        method=method,
        selected=selected,
        facets=rows,
        candidates=candidates_by_facet,
        note=note,
    )


# ---------------------------------------------------------------------------
# Final geometry: orthogonal c, lateral tiling, tags and fixed atoms
# ---------------------------------------------------------------------------


def atomic_layers(z_values: np.ndarray, tolerance: float) -> list[np.ndarray]:
    """Group atom indices into layers along z, ordered bottom to top."""
    order = np.argsort(z_values, kind="stable")
    layers: list[list[int]] = [[int(order[0])]]
    for index in order[1:]:
        if z_values[index] - z_values[layers[-1][-1]] <= tolerance:
            layers[-1].append(int(index))
        else:
            layers.append([int(index)])
    return [np.array(layer, dtype=int) for layer in layers]


def lateral_repeats(slab: Structure, settings: SlabSettings) -> tuple[int, int]:
    """Repeats so both perpendicular in-plane widths reach ``min_lateral_size``."""
    if settings.repeat_xy is not None:
        return settings.repeat_xy
    a_vec, b_vec = slab.lattice.matrix[0], slab.lattice.matrix[1]
    area = float(np.linalg.norm(np.cross(a_vec, b_vec)))
    width_a = area / float(np.linalg.norm(b_vec))
    width_b = area / float(np.linalg.norm(a_vec))
    return (
        max(1, math.ceil(settings.min_lateral_size / width_a - 1e-6)),
        max(1, math.ceil(settings.min_lateral_size / width_b - 1e-6)),
    )


def _fixed_indices(atoms: Atoms, layers: list[np.ndarray], settings: SlabSettings) -> list[int]:
    if len(layers) < 2:
        return []
    if settings.fixed_layers is not None:
        chosen = layers[: min(settings.fixed_layers, len(layers) - 1)]
    else:
        z_values = atoms.positions[:, 2]
        cutoff = z_values.min() + settings.fixed_fraction * (z_values.max() - z_values.min())
        chosen = [layer for layer in layers[:-1] if z_values[layer].mean() < cutoff - 1e-8]
    return sorted(int(index) for layer in chosen for index in layer)


def finalize_slab(candidate: SlabCandidate, settings: SlabSettings) -> tuple[Atoms, dict[str, Any]]:
    """Orthogonalize c, tile laterally, then tag and fix the bottom of the slab."""
    slab = candidate.slab.copy()
    slab.remove_oxidation_states()
    slab = slab.get_orthogonal_c_slab()
    repeats = lateral_repeats(slab, settings)
    atoms = _plain_atoms(slab)
    # Orthogonalizing c keeps Cartesian positions, which leaves tilted facets as a
    # "staircase" outside the cell. Wrapping in-plane only is physically identical
    # under periodic boundaries and keeps z (and thus layers and vacuum) unchanged.
    atoms.wrap(pbc=[True, True, False])
    atoms = atoms.repeat((repeats[0], repeats[1], 1))

    layers = atomic_layers(atoms.positions[:, 2], settings.layer_tolerance)
    fixed = _fixed_indices(atoms, layers, settings)
    tags = np.ones(len(atoms), dtype=int)
    tags[fixed] = 0
    atoms.set_tags(tags)
    if fixed:
        atoms.set_constraint(FixAtoms(indices=fixed))

    cell = atoms.cell.array
    area = float(np.linalg.norm(np.cross(cell[0], cell[1])))
    geometry = {
        "n_atoms": len(atoms),
        "formula": atoms.get_chemical_formula(mode="hill"),
        "repeat_xy": list(repeats),
        "lateral_widths_A": [
            round(area / float(np.linalg.norm(cell[1])), 4),
            round(area / float(np.linalg.norm(cell[0])), 4),
        ],
        "surface_area_A2": round(area, 4),
        "thickness_A": round(float(np.ptp(atoms.positions[:, 2])), 4),
        "vacuum_gap_A": round(vacuum_gap_angstrom(atoms), 4),
        "n_layers": len(layers),
        "n_fixed_atoms": len(fixed),
        "fixed_policy": (
            f"bottom {settings.fixed_layers} layer(s)"
            if settings.fixed_layers is not None
            else f"layers below {settings.fixed_fraction:.2f} of the slab thickness"
        ),
        "c_axis": "orthogonal to the surface (z is the surface normal)",
        "tags": "0 = fixed subsurface, 1 = free surface region",
    }
    return atoms, geometry


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def vacuum_gap_angstrom(atoms: Atoms) -> float:
    """Largest periodic gap along the third cell vector."""
    if len(atoms) == 0:
        return 0.0
    scaled_z = np.mod(atoms.get_scaled_positions(wrap=True)[:, 2], 1.0)
    ordered = np.sort(scaled_z)
    fractional_gaps = np.diff(np.r_[ordered, ordered[0] + 1.0])
    return float(fractional_gaps.max() * np.linalg.norm(atoms.cell.array[2]))


def validate_slab(
    atoms: Atoms,
    settings: SlabSettings,
    selected: SlabCandidate | None = None,
) -> ValidationReport:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    checks: list[ValidationIssue] = []

    gap = vacuum_gap_angstrom(atoms)
    checks.append(ValidationIssue(code="vacuum_gap", message=f"{gap:.3f} A", context={"value_A": gap}))
    if gap < 5.0:
        errors.append(ValidationIssue(code="no_vacuum", message=f"Periodic z-gap is only {gap:.3f} A."))
    elif gap < settings.min_vacuum_size - 0.5:
        warnings.append(
            ValidationIssue(
                code="thin_vacuum",
                message=f"Vacuum gap {gap:.3f} A is below the requested {settings.min_vacuum_size} A.",
            )
        )

    if len(atoms) > 1:
        distances = atoms.get_all_distances(mic=True)
        np.fill_diagonal(distances, np.inf)
        shortest = float(distances.min())
        checks.append(
            ValidationIssue(code="min_distance", message=f"{shortest:.3f} A", context={"value_A": shortest})
        )
        if shortest < settings.min_interatomic_distance:
            errors.append(
                ValidationIssue(
                    code="atomic_overlap",
                    message=f"Shortest interatomic distance {shortest:.3f} A is below "
                    f"{settings.min_interatomic_distance} A.",
                )
            )

    cell = atoms.cell.array
    area = float(np.linalg.norm(np.cross(cell[0], cell[1])))
    widths = [area / float(np.linalg.norm(cell[1])), area / float(np.linalg.norm(cell[0]))]
    if min(widths) < settings.min_lateral_size - 1e-6:
        warnings.append(
            ValidationIssue(
                code="small_lateral_cell",
                message=f"In-plane widths {widths[0]:.2f} / {widths[1]:.2f} A are below "
                f"{settings.min_lateral_size} A; adsorbates or clusters may interact with images.",
            )
        )

    tags = atoms.get_tags()
    top_layer = atomic_layers(atoms.positions[:, 2], settings.layer_tolerance)[-1]
    if np.any(tags[top_layer] == 0):
        errors.append(ValidationIssue(code="top_layer_fixed", message="The top atomic layer is fixed."))
    if settings.fixed_layers is not None:
        wants_fixed = settings.fixed_layers > 0
    else:
        wants_fixed = settings.fixed_fraction > 0
    if wants_fixed and not np.any(tags == 0):
        warnings.append(
            ValidationIssue(code="no_fixed_atoms", message="No atoms were fixed; the slab may be too thin.")
        )

    if selected is not None:
        if selected.polar is True:
            warnings.append(
                ValidationIssue(
                    code="polar_termination",
                    message="Selected termination is polar; a dipole correction or reconstruction is needed.",
                )
            )
        elif selected.polar is None:
            warnings.append(
                ValidationIssue(
                    code="polarity_unknown",
                    message="No oxidation-state guess was available, so polarity was not evaluated.",
                )
            )
        if not selected.stoichiometric:
            warnings.append(
                ValidationIssue(
                    code="non_stoichiometric_termination",
                    message="Selected termination is not stoichiometric with the bulk.",
                )
            )
    return ValidationReport(errors=errors, warnings=warnings, checks=checks)


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------


def build_slab(
    bulk: Structure,
    *,
    facet: str | Sequence[int] | None = None,
    settings: SlabSettings | None = None,
    energy_fn: EnergyFunction | None = None,
    max_index: int = 1,
    formula: str | None = None,
    spacegroup_symbol: str | None = None,
) -> SlabBuildResult:
    """Build a validated slab from a bulk crystal.

    Facet order: explicit ``facet`` -> surface-energy screening when
    ``energy_fn`` is given -> reviewed registry -> ``ValueError`` for manual
    review. With an explicit facet and ``energy_fn``, terminations are ranked
    by surface energy.
    """
    settings = settings or SlabSettings()
    conventional = conventional_bulk(bulk, settings.symprec)
    screening: FacetScreening | None = None

    if facet is not None:
        resolution = FacetResolution(
            parse_miller_index(facet),
            "explicit",
            "Facet was explicitly supplied from paper evidence or user input.",
        )
    elif energy_fn is not None:
        screening = screen_facets(conventional, settings, energy_fn, max_index)
        resolution = FacetResolution(
            screening.selected,
            "computed_surface_energy",
            f"Selected by {screening.method} among facets up to Miller index {max_index}.",
        )
    else:
        resolution = resolve_stable_facet(
            formula or conventional.composition.reduced_formula,
            spacegroup_symbol
            or SpacegroupAnalyzer(conventional, symprec=settings.symprec).get_space_group_symbol(),
        )

    miller = parse_miller_index(resolution.miller_index)
    if screening is not None and miller in screening.candidates:
        candidates = screening.candidates[miller]
    else:
        candidates = enumerate_terminations(conventional, miller, settings)
        if energy_fn is not None:
            bulk_energy = bulk_energy_per_atom(conventional, energy_fn)
            for candidate in candidates:
                assign_surface_energy(candidate, energy_fn, bulk_energy)
        candidates.sort(key=SlabCandidate.sort_key)

    selected = candidates[0]
    atoms, geometry = finalize_slab(selected, settings)
    validation = validate_slab(atoms, settings, selected)
    return SlabBuildResult(
        atoms=atoms,
        bulk=conventional,
        facet=resolution,
        selected=selected,
        candidates=candidates,
        screening=screening,
        validation=validation,
        geometry=geometry,
        settings=settings,
    )


def write_slab_outputs(
    result: SlabBuildResult,
    output_dir: Any,
    *,
    prefix: str = "slab",
    extra_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write POSCAR (selective dynamics), extxyz, conventional bulk and a manifest."""
    from ase.io import write

    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    slab_path = outdir / f"{prefix}.vasp"
    extxyz_path = outdir / f"{prefix}.extxyz"
    bulk_path = outdir / "bulk_conventional.cif"
    manifest_path = outdir / f"{prefix}_manifest.json"

    write(slab_path, result.atoms, format="vasp", direct=True, sort=True)
    write(extxyz_path, result.atoms, format="extxyz")
    result.bulk.to(filename=str(bulk_path), fmt="cif")

    manifest = result.manifest()
    if extra_manifest:
        manifest.update(extra_manifest)
    manifest["files"] = {
        "surface_slab": str(slab_path),
        "surface_slab_extxyz": str(extxyz_path),
        "bulk_conventional": str(bulk_path),
        "slab_manifest": str(manifest_path),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# Command-line entry point (wrapped by the surface-modeling skill)
# ---------------------------------------------------------------------------

FACET_EVIDENCE = {
    "explicit": "paper_extracted_or_user",
    "stable_facet_registry": "heuristic",
    "structure_family_registry": "heuristic",
}


def load_bulk(path: str | Path) -> Structure:
    """Read a bulk crystal with pymatgen, falling back to ASE readers."""
    try:
        return Structure.from_file(str(path))
    except Exception:
        from ase.io import read
        from pymatgen.io.ase import AseAtomsAdaptor

        return AseAtomsAdaptor.get_structure(read(path))


def build_energy_calculator(name: str, uma_model: str, task_name: str, device: str) -> Any:
    """ASE calculator for surface energies: ``none`` -> None, ``emt`` or ``uma``."""
    if name == "none":
        return None
    if name == "emt":
        from ase.calculators.emt import EMT

        return EMT()
    if name != "uma":
        raise ValueError(f"Unknown calculator {name!r}; choose none, emt or uma.")
    from fairchem.core import FAIRChemCalculator, pretrained_mlip

    predictor = pretrained_mlip.get_predict_unit(uma_model, device=device)
    return FAIRChemCalculator(predictor, task_name=task_name)


def _parse_repeat_xy(text: str) -> tuple[int, int] | None:
    if text.strip().lower() == "auto":
        return None
    values = tuple(int(item) for item in text.split(","))
    if len(values) != 2 or min(values) < 1:
        raise ValueError("--repeat-xy requires 'auto' or two positive integers, e.g. 3,3.")
    return values  # type: ignore[return-value]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a validated surface slab from a bulk crystal.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bulk", type=Path, help="Bulk crystal file readable by pymatgen or ASE (CIF, POSCAR, ...).")
    source.add_argument("--formula", help="Most stable Materials Project bulk for this formula (needs MP_API_KEY).")
    source.add_argument("--material-id", help="Materials Project id, e.g. mp-20194 (needs MP_API_KEY).")
    parser.add_argument("--facet", default=None, help="Miller index in the conventional cell, e.g. 111, (1-10), 1,1,0, 0001.")
    parser.add_argument("--max-index", type=int, default=1, help="Highest Miller index ranked by surface energy.")
    parser.add_argument(
        "--calculator",
        choices=["none", "emt", "uma"],
        default="none",
        help="Energy model for surface-energy ranking; 'none' uses the reviewed facet registry.",
    )
    parser.add_argument("--uma-model", default="uma-s-1p2")
    parser.add_argument("--task-name", default="omat", help="UMA task head used for bulk and slab energies.")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--relax-steps", type=int, default=0, help="LBFGS steps before each energy (0 = static).")
    parser.add_argument("--fmax", type=float, default=0.05)
    parser.add_argument("--min-slab-size", type=float, default=12.0)
    parser.add_argument("--min-vacuum-size", type=float, default=15.0)
    parser.add_argument("--min-lateral-size", type=float, default=8.0)
    parser.add_argument("--repeat-xy", default="auto", help="'auto' (from --min-lateral-size) or two integers.")
    parser.add_argument("--fixed-fraction", type=float, default=0.5, help="Fix layers below this fraction of the thickness.")
    parser.add_argument("--fixed-layers", type=int, default=None, help="Fix this many bottom layers instead.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="slab")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = SlabSettings(
        min_slab_size=args.min_slab_size,
        min_vacuum_size=args.min_vacuum_size,
        min_lateral_size=args.min_lateral_size,
        repeat_xy=_parse_repeat_xy(args.repeat_xy),
        fixed_fraction=args.fixed_fraction,
        fixed_layers=args.fixed_layers,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    (args.output_dir / "run_config.json").write_text(json.dumps(run_config, indent=2) + "\n", encoding="utf-8")

    formula = spacegroup = None
    if args.bulk is not None:
        bulk = load_bulk(args.bulk)
        source: dict[str, Any] = {"type": "file", "path": str(args.bulk)}
    else:
        from .materials_project_slab import fetch_bulk_structure

        bulk, metadata = fetch_bulk_structure(formula=args.formula, material_id=args.material_id)
        source = {"type": "materials_project", **metadata}
        formula, spacegroup = metadata["formula"], metadata.get("spacegroup_symbol")

    calculator = build_energy_calculator(args.calculator, args.uma_model, args.task_name, args.device)
    energy_fn = (
        energy_function_from_calculator(calculator, relax_steps=args.relax_steps, fmax=args.fmax)
        if calculator is not None
        else None
    )
    result = build_slab(
        bulk,
        facet=args.facet,
        settings=settings,
        energy_fn=energy_fn,
        max_index=args.max_index,
        formula=formula,
        spacegroup_symbol=spacegroup,
    )
    energy_model = None
    if calculator is not None:
        energy_model = {
            "calculator": args.calculator,
            "uma_model": args.uma_model if args.calculator == "uma" else None,
            "task_name": args.task_name if args.calculator == "uma" else None,
            "relax_steps": args.relax_steps,
            "fmax": args.fmax,
        }
    facet_evidence = FACET_EVIDENCE.get(
        result.facet.source,
        "mlip_predicted" if args.calculator == "uma" else "heuristic",
    )
    manifest = write_slab_outputs(
        result,
        args.output_dir,
        prefix=args.prefix,
        extra_manifest={"source": source, "energy_model": energy_model, "facet_evidence_level": facet_evidence},
    )

    selected = manifest["selected_termination"]
    print(f"Bulk: {manifest['bulk']['formula']} ({manifest['bulk']['spacegroup_symbol']}, conventional cell)")
    print(f"Facet: {manifest['facet']['miller_index']} via {manifest['facet']['selection_source']}")
    if manifest["facet_screening"]:
        for row in manifest["facet_screening"]["facets"]:
            print(
                f"  {row['miller_index']}: gamma={row['surface_energy_J_m2']} J/m^2, "
                f"Wulff fraction={row['wulff_area_fraction']}"
            )
    print(
        f"Termination {selected['termination_index'] + 1}/{len(manifest['terminations'])}: "
        f"stoichiometric={selected['stoichiometric']} symmetric={selected['symmetric']} polar={selected['polar']}"
    )
    print(
        f"Slab: {manifest['slab']['n_atoms']} atoms, repeat {manifest['slab']['repeat_xy']}, "
        f"{manifest['slab']['n_fixed_atoms']} fixed, vacuum {manifest['slab']['vacuum_gap_A']} A"
    )
    for issue in result.validation.warnings:
        print(f"WARNING [{issue.code}] {issue.message}")
    print(f"Wrote {manifest['files']['surface_slab']}")
    print(f"Wrote {manifest['files']['slab_manifest']}")
    if not result.validation.passed:
        for issue in result.validation.errors:
            print(f"ERROR [{issue.code}] {issue.message}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
