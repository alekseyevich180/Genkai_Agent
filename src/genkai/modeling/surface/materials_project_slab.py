from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.io import read as ase_read
from mp_api.client import MPRester
from pymatgen.core import Composition, Structure
from pymatgen.core.surface import SlabGenerator
from pymatgen.io.ase import AseAtomsAdaptor


STABLE_FACETS_BY_FORMULA: dict[str, tuple[int, ...]] = {
    "CeO2": (1, 1, 1),
    "TiO2": (1, 1, 0),
    "SnO2": (1, 1, 0),
    "RuO2": (1, 1, 0),
    "IrO2": (1, 1, 0),
}

STABLE_FACETS_BY_SPACEGROUP: dict[str, tuple[int, ...]] = {
    "Fm-3m": (1, 1, 1),
    "Im-3m": (1, 1, 0),
    "P6_3/mmc": (0, 0, 1),
    "P63/mmc": (0, 0, 1),
    "P4_2/mnm": (1, 1, 0),
    "P42/mnm": (1, 1, 0),
}


@dataclass(frozen=True)
class FacetResolution:
    miller_index: tuple[int, ...]
    source: str
    reason: str


def canonical_formula(formula: str) -> str:
    return Composition(formula).reduced_formula


def parse_miller_index(value: str | tuple[int, ...] | list[int]) -> tuple[int, ...]:
    if isinstance(value, (tuple, list)):
        values = tuple(int(item) for item in value)
    else:
        tokens = re.findall(r"-?\d+", value)
        values = tuple(int(item) for item in tokens)
    if len(values) == 4:
        h, k, i, ell = values
        if h + k + i != 0:
            raise ValueError(f"Invalid Miller-Bravais index: {value!r}")
        values = (h, k, ell)
    if len(values) != 3 or not any(values):
        raise ValueError(f"Invalid Miller index: {value!r}")
    return values


def resolve_stable_facet(
    formula: str,
    spacegroup_symbol: str | None,
    explicit_facet: str | tuple[int, ...] | list[int] | None = None,
) -> FacetResolution:
    if explicit_facet is not None:
        return FacetResolution(
            parse_miller_index(explicit_facet),
            "explicit",
            "Facet was explicitly supplied from paper evidence or user input.",
        )

    normalized_formula = canonical_formula(formula)
    if normalized_formula in STABLE_FACETS_BY_FORMULA:
        facet = STABLE_FACETS_BY_FORMULA[normalized_formula]
        return FacetResolution(
            facet,
            "stable_facet_registry",
            f"Registered commonly stable facet for {normalized_formula}.",
        )

    normalized_spg = (spacegroup_symbol or "").replace(" ", "")
    for symbol, facet in STABLE_FACETS_BY_SPACEGROUP.items():
        if normalized_spg == symbol.replace(" ", ""):
            return FacetResolution(
                facet,
                "structure_family_registry",
                f"Facet selected from the registered structure family {spacegroup_symbol}.",
            )

    raise ValueError(
        f"No stable facet is registered for {normalized_formula} ({spacegroup_symbol or 'unknown space group'}). "
        "Provide --surface-facet from paper evidence or a reviewed surface-stability source."
    )


def _document_value(document: Any, name: str, default: Any = None) -> Any:
    if isinstance(document, dict):
        return document.get(name, default)
    return getattr(document, name, default)


def _select_bulk_document(documents: list[Any]) -> Any:
    if not documents:
        raise ValueError("Materials Project returned no matching bulk structures.")

    def rank(document: Any) -> tuple[bool, float, bool, str]:
        stable = bool(_document_value(document, "is_stable", False))
        hull = _document_value(document, "energy_above_hull", float("inf"))
        theoretical = bool(_document_value(document, "theoretical", True))
        material_id = str(_document_value(document, "material_id", ""))
        return (not stable, float(hull if hull is not None else float("inf")), theoretical, material_id)

    return min(documents, key=rank)


def fetch_bulk_structure(
    *,
    formula: str | None = None,
    material_id: str | None = None,
    api_key: str | None = None,
) -> tuple[Structure, dict[str, Any]]:
    if bool(formula) == bool(material_id):
        raise ValueError("Provide exactly one of formula or material_id.")
    key = api_key or os.environ.get("MP_API_KEY")
    if not key:
        raise RuntimeError("Materials Project access requires the MP_API_KEY environment variable.")

    fields = [
        "material_id",
        "formula_pretty",
        "structure",
        "symmetry",
        "energy_above_hull",
        "is_stable",
        "theoretical",
    ]
    with MPRester(key) as mpr:
        if material_id:
            documents = mpr.materials.summary.search(material_ids=[material_id], fields=fields)
        else:
            documents = mpr.materials.summary.search(formula=formula, fields=fields)

    document = _select_bulk_document(list(documents))
    structure = _document_value(document, "structure")
    if structure is None:
        raise ValueError("Selected Materials Project document does not include a structure.")
    symmetry = _document_value(document, "symmetry")
    symmetry_symbol = _document_value(symmetry, "symbol") if symmetry is not None else None
    metadata = {
        "material_id": str(_document_value(document, "material_id")),
        "formula": str(_document_value(document, "formula_pretty", structure.composition.reduced_formula)),
        "spacegroup_symbol": symmetry_symbol,
        "energy_above_hull_eV_per_atom": _document_value(document, "energy_above_hull"),
        "is_stable": bool(_document_value(document, "is_stable", False)),
        "theoretical": bool(_document_value(document, "theoretical", False)),
    }
    return structure, metadata


def _slab_rank(slab: Any) -> tuple[bool, float, int]:
    symmetric = bool(slab.is_symmetric())
    dipole = np.asarray(getattr(slab, "dipole", [0.0, 0.0, 0.0]), dtype=float)
    return (not symmetric, float(np.linalg.norm(dipole)), len(slab))


def build_stable_slab(
    bulk_structure: Structure,
    miller_index: tuple[int, ...],
    *,
    min_slab_size: float = 12.0,
    min_vacuum_size: float = 15.0,
    repeat_xy: tuple[int, int] = (2, 2),
) -> tuple[Any, dict[str, Any]]:
    generator = SlabGenerator(
        initial_structure=bulk_structure,
        miller_index=miller_index,
        min_slab_size=min_slab_size,
        min_vacuum_size=min_vacuum_size,
        center_slab=True,
        in_unit_planes=False,
        primitive=True,
        reorient_lattice=True,
    )
    slabs = generator.get_slabs(symmetrize=False)
    if not slabs:
        raise ValueError(f"No slabs could be generated for facet {miller_index}.")
    selected_index, selected = min(enumerate(slabs), key=lambda item: _slab_rank(item[1]))
    repeated = selected * (int(repeat_xy[0]), int(repeat_xy[1]), 1)
    metadata = {
        "candidate_terminations": len(slabs),
        "selected_termination_index": selected_index,
        "termination_selection": "prefer symmetric slab, then minimum dipole norm, then atom count",
        "selected_is_symmetric": bool(selected.is_symmetric()),
        "min_slab_size_A": min_slab_size,
        "min_vacuum_size_A": min_vacuum_size,
        "repeat_xy": list(repeat_xy),
    }
    return repeated, metadata


def vacuum_gap_angstrom(atoms: Atoms) -> float:
    if len(atoms) == 0:
        return 0.0
    scaled_z = np.mod(atoms.get_scaled_positions(wrap=True)[:, 2], 1.0)
    ordered = np.sort(scaled_z)
    fractional_gaps = np.diff(np.r_[ordered, ordered[0] + 1.0])
    return float(fractional_gaps.max() * np.linalg.norm(atoms.cell.array[2]))


def validate_surface_slab(atoms_or_path: Atoms | str | Path, min_vacuum_gap: float = 5.0) -> dict[str, Any]:
    atoms = ase_read(atoms_or_path) if isinstance(atoms_or_path, (str, Path)) else atoms_or_path
    gap = vacuum_gap_angstrom(atoms)
    result = {
        "is_slab": gap >= min_vacuum_gap,
        "vacuum_gap_A": round(gap, 6),
        "required_vacuum_gap_A": min_vacuum_gap,
    }
    if not result["is_slab"]:
        raise ValueError(
            f"Surface input has only {gap:.3f} Å periodic z-gap and looks like a bulk unit cell. "
            "Generate a stable-facet slab before nanoparticle placement."
        )
    return result


def download_stable_surface(
    output_dir: str | Path,
    *,
    formula: str | None = None,
    material_id: str | None = None,
    explicit_facet: str | tuple[int, ...] | None = None,
    api_key: str | None = None,
    min_slab_size: float = 12.0,
    min_vacuum_size: float = 15.0,
    repeat_xy: tuple[int, int] = (2, 2),
) -> dict[str, Any]:
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    bulk, mp_metadata = fetch_bulk_structure(formula=formula, material_id=material_id, api_key=api_key)
    facet = resolve_stable_facet(
        mp_metadata["formula"],
        mp_metadata.get("spacegroup_symbol"),
        explicit_facet,
    )
    slab, slab_metadata = build_stable_slab(
        bulk,
        facet.miller_index,
        min_slab_size=min_slab_size,
        min_vacuum_size=min_vacuum_size,
        repeat_xy=repeat_xy,
    )

    bulk_path = outdir / "bulk_from_materials_project.cif"
    slab_path = outdir / "stable_surface_slab.vasp"
    bulk.to(filename=str(bulk_path), fmt="cif")
    slab.to(filename=str(slab_path), fmt="poscar")
    slab_check = validate_surface_slab(slab_path)
    manifest = {
        "schema_version": "1.0",
        "source": {"database": "Materials Project", **mp_metadata},
        "facet": {
            "miller_index": list(facet.miller_index),
            "selection_source": facet.source,
            "reason": facet.reason,
        },
        "slab": slab_metadata,
        "files": {"bulk_structure": str(bulk_path), "surface_slab": str(slab_path)},
        "checks": {
            "api_key_persisted": False,
            "bulk_used_directly_for_loading": False,
            "surface_is_slab": slab_check,
        },
    }
    manifest_path = outdir / "surface_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["files"]["surface_manifest"] = str(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Download an MP bulk crystal and generate a reviewed stable-facet slab.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--formula")
    source.add_argument("--material-id")
    parser.add_argument("--surface-facet", default=None, help="Explicit Miller index, e.g. 1,1,1 or 0,0,0,1.")
    parser.add_argument("--min-slab-size", type=float, default=12.0)
    parser.add_argument("--min-vacuum-size", type=float, default=15.0)
    parser.add_argument("--repeat-xy", default="2,2")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repeat_xy = tuple(int(item) for item in args.repeat_xy.split(","))
    if len(repeat_xy) != 2 or min(repeat_xy) < 1:
        raise ValueError("--repeat-xy requires two positive integers, e.g. 2,2.")
    result = download_stable_surface(
        args.output_dir,
        formula=args.formula,
        material_id=args.material_id,
        explicit_facet=args.surface_facet,
        min_slab_size=args.min_slab_size,
        min_vacuum_size=args.min_vacuum_size,
        repeat_xy=repeat_xy,
    )
    print(result["files"]["surface_slab"])
    print(result["files"]["surface_manifest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
