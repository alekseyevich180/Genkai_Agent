"""Substrate slabs shared by the SAM and ALD-overlayer builders.

A substrate comes either from a reviewed slab file or from a bulk crystal cut
by :mod:`genkai.modeling.surface.slab`. Without an explicit facet the slab
module picks the most stable facet: surface-energy ranking when an energy model
is given (Wulff area fraction), otherwise the reviewed stable-facet registry.

Every substrate follows the slab convention: the third cell vector is the
surface normal (z), the slab is contiguous along z, atoms tagged 0 are fixed
(``FixAtoms``) and atoms tagged 1 are free. Slab files read from CIF carry no
constraints; the bottom of such slabs is fixed again with the same rule as the
slab generator and the source of the constraints is recorded.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.build import make_supercell
from ase.constraints import FixAtoms

from genkai.contracts.validation import ValidationIssue

from .slab import (
    FACET_EVIDENCE,
    SlabSettings,
    _fixed_indices,
    atomic_layers,
    build_energy_calculator,
    build_slab,
    energy_function_from_calculator,
    load_bulk,
    vacuum_gap_angstrom,
)
from .structure_io import read_structure, sha256_of

MIN_VACUUM_GAP_A = 5.0


@dataclass
class Substrate:
    atoms: Atoms
    record: dict[str, Any]
    warnings: list[ValidationIssue] = field(default_factory=list)


def fixed_indices(atoms: Atoms) -> list[int]:
    fixed: list[int] = []
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            fixed.extend(int(index) for index in constraint.get_indices())
    return sorted(set(fixed))


def lateral_widths(atoms: Atoms) -> tuple[float, float]:
    """Perpendicular in-plane widths of the cell (distance between opposite faces)."""
    a_vec, b_vec = atoms.cell.array[0], atoms.cell.array[1]
    area = float(np.linalg.norm(np.cross(a_vec, b_vec)))
    return area / float(np.linalg.norm(b_vec)), area / float(np.linalg.norm(a_vec))


def surface_area(atoms: Atoms) -> float:
    return float(np.linalg.norm(np.cross(atoms.cell.array[0], atoms.cell.array[1])))


def repeats_for_width(atoms: Atoms, min_width: float) -> tuple[int, int]:
    width_a, width_b = lateral_widths(atoms)
    return (
        max(1, int(np.ceil(min_width / width_a - 1e-6))),
        max(1, int(np.ceil(min_width / width_b - 1e-6))),
    )


def check_slab_cell(atoms: Atoms) -> None:
    """The third cell vector must be the surface normal and the slab must have vacuum."""
    cell = atoms.cell.array
    if cell.shape != (3, 3) or atoms.cell.rank < 3:
        raise ValueError("The slab needs a full 3D cell.")
    if np.abs(cell[2, :2]).max() > 1e-4 or np.abs(cell[:2, 2]).max() > 1e-4:
        raise ValueError(
            "The third cell vector must be the surface normal (along z) with a and b in the xy plane; "
            "regenerate the slab with the slab generator."
        )
    gap = vacuum_gap_angstrom(atoms)
    if gap < MIN_VACUUM_GAP_A:
        raise ValueError(
            f"The structure has only a {gap:.2f} A vacuum gap along c and looks like a bulk cell; "
            "pass it as a bulk crystal instead."
        )


def orient_slab_cell(atoms: Atoms) -> tuple[Atoms, bool]:
    """Rotate a slab so a, b lie in the xy plane and replace c by its normal component.

    Slabs from older generators (e.g. Materials Project routes before the slab
    module) keep a tilted c vector. With vacuum along c, using the component of
    c along the surface normal instead is the same operation as pymatgen's
    ``get_orthogonal_c_slab``: atoms move only by a rigid rotation and in-plane
    wrapping, so every bonded distance is unchanged.
    """
    cell = atoms.cell.array
    if np.abs(cell[2, :2]).max() <= 1e-4 and np.abs(cell[:2, 2]).max() <= 1e-4:
        return atoms.copy(), False
    a, b, c = cell
    if np.linalg.det(cell) < 0:  # left-handed: swap a and b so a x b points along c
        a, b = b, a
    normal = np.cross(a, b)
    normal /= np.linalg.norm(normal)
    e1 = a / np.linalg.norm(a)
    rotation = np.vstack([e1, np.cross(normal, e1), normal])
    slab = atoms.copy()
    slab.set_cell(np.vstack([rotation @ a, rotation @ b, [0.0, 0.0, float(c @ normal)]]), scale_atoms=False)
    slab.set_positions(atoms.get_positions() @ rotation.T)
    slab.wrap(pbc=[True, True, False])
    return slab, True


def make_slab_contiguous(atoms: Atoms, bottom_margin: float = 0.5) -> Atoms:
    """Shift atoms along z only if the slab straddles the cell top/bottom."""
    slab = atoms.copy()
    height = float(slab.cell.array[2, 2])
    scaled = np.mod(slab.get_scaled_positions(wrap=False)[:, 2], 1.0)
    order = np.sort(scaled)
    gaps = np.diff(np.concatenate([order, [order[0] + 1.0]]))
    largest = int(np.argmax(gaps))
    inside = (slab.get_scaled_positions(wrap=False)[:, 2] >= 0.0).all() and (
        slab.get_scaled_positions(wrap=False)[:, 2] < 1.0
    ).all()
    if largest == len(order) - 1 and inside:
        return slab  # vacuum gap already spans the cell boundary
    start = order[(largest + 1) % len(order)]  # first atom above the vacuum gap
    shifted = np.mod(scaled - start, 1.0)
    positions = slab.get_positions()
    positions[:, 2] = shifted * height + bottom_margin
    slab.set_positions(positions)
    return slab


def fixed_below_fraction(atoms: Atoms, fraction: float) -> list[int]:
    """Indices of atoms below ``fraction`` of the slab thickness (z)."""
    z = atoms.positions[:, 2]
    cutoff = z.min() + fraction * (z.max() - z.min())
    return [int(i) for i in np.flatnonzero(z < cutoff - 1e-8)]


def apply_slab_convention(atoms: Atoms, settings: SlabSettings) -> tuple[Atoms, str]:
    """Ensure tags 0/1 match FixAtoms; fix the slab bottom if no constraint exists."""
    slab = atoms.copy()
    fixed = fixed_indices(slab)
    if fixed:
        source = "file"
    else:
        layers = atomic_layers(slab.positions[:, 2], settings.layer_tolerance)
        fixed = _fixed_indices(slab, layers, settings)
        source = "reapplied: " + (
            f"bottom {settings.fixed_layers} layer(s)"
            if settings.fixed_layers is not None
            else f"layers below {settings.fixed_fraction:.2f} of the slab thickness"
        )
        if not fixed and len(layers) < 2 and len(slab) > 1:
            # Amorphous slabs have no discrete layers (every z gap is below the
            # layer tolerance); fix by height instead.
            fixed = fixed_below_fraction(slab, settings.fixed_fraction)
            source = f"reapplied: atoms below {settings.fixed_fraction:.2f} of the slab thickness (no discrete layers)"
        if fixed:
            slab.set_constraint(FixAtoms(indices=fixed))
    tags = np.ones(len(slab), dtype=int)
    tags[fixed] = 0
    slab.set_tags(tags)
    return slab, source


def ensure_fixed_bottom(atoms: Atoms, fixed_fraction: float = 0.5) -> tuple[Atoms, str]:
    """Keep constraints from the file; otherwise fix the slab bottom before an MLIP relaxation.

    The older vacancy, adsorbate and cluster-search scripts read slabs with
    ``ase.io.read``; CIF files carry no ``FixAtoms``, so without this the whole
    slab (both surfaces) would relax. ``fixed_fraction <= 0`` disables it.
    """
    if fixed_indices(atoms):
        return atoms, "file"
    if fixed_fraction <= 0:
        return atoms, "none (disabled)"
    fixed_slab, source = apply_slab_convention(atoms, SlabSettings(fixed_fraction=fixed_fraction))
    return fixed_slab, source


def supercell_in_plane(atoms: Atoms, matrix: Any) -> Atoms:
    """In-plane supercell from a 2x2 integer matrix, keeping tags and FixAtoms."""
    transform = np.asarray(matrix, dtype=int).reshape(2, 2)
    if round(float(np.linalg.det(transform))) <= 0:
        raise ValueError(f"In-plane supercell matrix {transform.tolist()} must have a positive determinant.")
    if transform[0, 1] == 0 and transform[1, 0] == 0:
        return atoms.repeat((int(transform[0, 0]), int(transform[1, 1]), 1))
    mask = np.zeros(len(atoms), dtype=int)
    mask[fixed_indices(atoms)] = 1
    source = atoms.copy()
    source.set_constraint()
    source.new_array("_fixed_mask", mask)
    full = np.eye(3, dtype=int)
    full[:2, :2] = transform
    result = make_supercell(source, full)
    fixed = np.flatnonzero(result.arrays.pop("_fixed_mask"))
    result.wrap(pbc=[True, True, False])
    if len(fixed):
        result.set_constraint(FixAtoms(indices=fixed))
    return result


def _read_bulk(path: Path, fmt: str | None) -> tuple[Any, str]:
    from pymatgen.io.ase import AseAtomsAdaptor

    if fmt is None:
        try:
            return load_bulk(path), "pymatgen-auto"
        except Exception:
            pass
    atoms, used = read_structure(path, fmt)
    return AseAtomsAdaptor.get_structure(atoms), used


def prepare_substrate(
    *,
    surface: str | Path | None = None,
    surface_format: str | None = None,
    bulk: str | Path | None = None,
    bulk_format: str | None = None,
    facet: str | None = None,
    settings: SlabSettings | None = None,
    repeat_xy: tuple[int, int] | None = None,
    calculator: str = "none",
    uma_model: str = "uma-s-1p2",
    task_name: str = "omat",
    device: str = "cuda",
    relax_steps: int = 0,
    fmax: float = 0.05,
    max_index: int = 1,
    miller_basis: str = "auto",
) -> Substrate:
    """Load a reviewed slab, or cut the explicit/most stable facet from a bulk crystal."""
    if (surface is None) == (bulk is None):
        raise ValueError("Give exactly one of a slab file (surface) or a bulk crystal (bulk).")
    settings = settings or SlabSettings()
    warnings: list[ValidationIssue] = []

    if surface is not None:
        path = Path(surface)
        atoms, used = read_structure(path, surface_format)
        atoms, normalized = orient_slab_cell(atoms)
        check_slab_cell(atoms)
        atoms = make_slab_contiguous(atoms)
        atoms, constraint_source = apply_slab_convention(atoms, settings)
        if normalized:
            warnings.append(
                ValidationIssue(
                    code="slab_cell_normalized",
                    message=(
                        "The slab was rotated so a and b lie in the xy plane and c was replaced by its component "
                        "along the surface normal; bonded distances are unchanged."
                    ),
                )
            )
        if facet is not None:
            warnings.append(
                ValidationIssue(
                    code="slab_file_takes_precedence",
                    message="A slab file was supplied; the facet argument is ignored.",
                )
            )
        record: dict[str, Any] = {
            "mode": "slab_file",
            "path": path.as_posix(),
            "format": used,
            "sha256": sha256_of(path),
            "facet": None,
            "facet_source": "slab_file",
            "constraints_source": constraint_source,
            "cell_normalized": normalized,
        }
    else:
        path = Path(bulk)  # type: ignore[arg-type]
        structure, used = _read_bulk(path, bulk_format)
        energy_model = None
        energy_fn = None
        if calculator != "none":
            calc = build_energy_calculator(calculator, uma_model, task_name, device)
            energy_fn = energy_function_from_calculator(calc, relax_steps=relax_steps, fmax=fmax)
            energy_model = {
                "calculator": calculator,
                "uma_model": uma_model if calculator == "uma" else None,
                "task_name": task_name if calculator == "uma" else None,
                "relax_steps": relax_steps,
                "fmax": fmax,
            }
        result = build_slab(
            structure,
            facet=facet,
            settings=settings,
            energy_fn=energy_fn,
            max_index=max_index,
            miller_basis=miller_basis,
        )
        if not result.validation.passed:
            codes = ", ".join(issue.code for issue in result.validation.errors)
            raise ValueError(f"The generated slab failed validation ({codes}).")
        warnings.extend(result.validation.warnings)
        atoms = result.atoms
        manifest = result.manifest()
        record = {
            "mode": "bulk",
            "path": path.as_posix(),
            "format": used,
            "sha256": sha256_of(path),
            "bulk_formula": manifest["bulk"]["formula"],
            "spacegroup": manifest["bulk"]["spacegroup_symbol"],
            "facet": manifest["facet"]["miller_index"],
            "facet_source": result.facet.source,
            "facet_reason": result.facet.reason,
            "facet_evidence": FACET_EVIDENCE.get(
                result.facet.source, "mlip_predicted" if calculator == "uma" else "heuristic"
            ),
            "miller_basis": manifest["facet"]["miller_basis"],
            "facet_screening": manifest["facet_screening"],
            "selected_termination": manifest["selected_termination"],
            "energy_model": energy_model,
            "constraints_source": "slab_generator",
        }

    if repeat_xy is not None:
        atoms = atoms.repeat((int(repeat_xy[0]), int(repeat_xy[1]), 1))
    record["repeat_xy"] = list(repeat_xy) if repeat_xy else None
    record["n_atoms"] = len(atoms)
    record["formula"] = atoms.get_chemical_formula(mode="hill")
    record["n_fixed"] = len(fixed_indices(atoms))
    record["surface_area_A2"] = round(surface_area(atoms), 4)
    record["lateral_widths_A"] = [round(width, 4) for width in lateral_widths(atoms)]
    return Substrate(atoms=atoms, record=record, warnings=warnings)


# ---------------------------------------------------------------------------
# Command-line helpers shared by the SAM and ALD-overlayer builders
# ---------------------------------------------------------------------------


def parse_ints(text: str | None) -> tuple[int, ...] | None:
    if text is None:
        return None
    return tuple(int(item) for item in text.replace(" ", "").split(",") if item)


def parse_floats(text: str | None) -> tuple[float, ...] | None:
    if text is None:
        return None
    return tuple(float(item) for item in text.replace(" ", "").split(",") if item)


def parse_export(text: str) -> list[str]:
    if text.strip().lower() == "none":
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def add_substrate_arguments(parser: argparse.ArgumentParser) -> None:
    """Substrate options: a reviewed slab file, or a bulk crystal plus an optional facet."""
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--surface", type=Path, help="Reviewed slab file (CIF by default; any ASE format).")
    source.add_argument("--bulk", type=Path, help="Bulk crystal to cut (CIF by default; any ASE format).")
    parser.add_argument("--surface-format", default=None, help="Force the slab file format (e.g. vasp, extxyz).")
    parser.add_argument("--bulk-format", default=None, help="Force the bulk file format.")
    parser.add_argument(
        "--facet",
        default=None,
        help="Miller index to cut from --bulk; omitted -> most stable facet (surface energy with --calculator, "
        "otherwise the reviewed stable-facet registry).",
    )
    parser.add_argument(
        "--calculator",
        choices=["none", "emt", "uma"],
        default="none",
        help="Energy model for most-stable-facet ranking (emt: some metals only; uma needs explicit authorization).",
    )
    parser.add_argument("--max-index", type=int, default=1)
    parser.add_argument("--uma-model", default="uma-s-1p2")
    parser.add_argument("--task-name", default="omat")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--min-slab-size", type=float, default=12.0)
    parser.add_argument("--min-vacuum-size", type=float, default=15.0)
    parser.add_argument("--min-lateral-size", type=float, default=8.0)
    parser.add_argument("--fixed-fraction", type=float, default=0.5)
    parser.add_argument("--fixed-layers", type=int, default=None)
    parser.add_argument("--repeat-xy", default=None, help="Repeat the slab in-plane, e.g. 2,2.")


def substrate_from_args(args: argparse.Namespace) -> Substrate:
    repeat = parse_ints(args.repeat_xy)
    if repeat is not None and (len(repeat) != 2 or min(repeat) < 1):
        raise ValueError("--repeat-xy needs two positive integers, e.g. 2,2.")
    settings = SlabSettings(
        min_slab_size=args.min_slab_size,
        min_vacuum_size=args.min_vacuum_size,
        min_lateral_size=args.min_lateral_size,
        fixed_fraction=args.fixed_fraction,
        fixed_layers=args.fixed_layers,
    )
    return prepare_substrate(
        surface=args.surface,
        surface_format=args.surface_format,
        bulk=args.bulk,
        bulk_format=args.bulk_format,
        facet=args.facet,
        settings=settings,
        repeat_xy=repeat,  # type: ignore[arg-type]
        calculator=args.calculator,
        uma_model=args.uma_model,
        task_name=args.task_name,
        device=args.device,
        max_index=args.max_index,
    )
