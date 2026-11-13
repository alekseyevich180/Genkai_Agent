"""Materials Project bulk -> stable-facet slab.

This module only fetches the bulk reference from Materials Project. Facet
resolution, conventional-cell handling, termination selection, fixed layers
and validation live in :mod:`genkai.modeling.surface.slab`; the registry names
are re-exported here for existing callers.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from ase import Atoms
from ase.io import read as ase_read
from pymatgen.core import Structure

from .slab import (
    STABLE_FACETS_BY_FORMULA,
    STABLE_FACETS_BY_SPACEGROUP,
    STRUCTURE_FAMILY_LABELS,
    FacetResolution,
    SlabSettings,
    build_slab,
    canonical_formula,
    parse_miller_index,
    resolve_stable_facet,
    stoichiometry_signature,
    vacuum_gap_angstrom,
    write_slab_outputs,
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

    from mp_api.client import MPRester

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


def _settings(
    min_slab_size: float,
    min_vacuum_size: float,
    repeat_xy: tuple[int, int] | None,
) -> SlabSettings:
    return SlabSettings(
        min_slab_size=min_slab_size,
        min_vacuum_size=min_vacuum_size,
        repeat_xy=tuple(int(value) for value in repeat_xy) if repeat_xy else None,
    )


def build_stable_slab(
    bulk_structure: Structure,
    miller_index: tuple[int, ...],
    *,
    min_slab_size: float = 12.0,
    min_vacuum_size: float = 15.0,
    repeat_xy: tuple[int, int] | None = (2, 2),
) -> tuple[Atoms, dict[str, Any]]:
    """Slab for an explicit facet; returns ASE atoms (bottom fixed) and the slab manifest."""
    result = build_slab(
        bulk_structure,
        facet=miller_index,
        settings=_settings(min_slab_size, min_vacuum_size, repeat_xy),
    )
    return result.atoms, result.manifest()


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
    repeat_xy: tuple[int, int] | None = (2, 2),
) -> dict[str, Any]:
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    bulk, mp_metadata = fetch_bulk_structure(formula=formula, material_id=material_id, api_key=api_key)
    result = build_slab(
        bulk,
        facet=explicit_facet,
        settings=_settings(min_slab_size, min_vacuum_size, repeat_xy),
        formula=mp_metadata["formula"],
        spacegroup_symbol=mp_metadata.get("spacegroup_symbol"),
        # Facets on this route come from papers or the registry: standard setting.
        miller_basis="conventional",
    )

    bulk_path = outdir / "bulk_from_materials_project.cif"
    bulk.to(filename=str(bulk_path), fmt="cif")
    slab_manifest = write_slab_outputs(result, outdir, prefix="stable_surface_slab")
    slab_path = slab_manifest["files"]["surface_slab"]
    slab_check = validate_surface_slab(slab_path)
    manifest = {
        "schema_version": "1.1",
        "source": {"database": "Materials Project", **mp_metadata},
        "facet": slab_manifest["facet"],
        "slab": {
            **slab_manifest["slab"],
            "selected_termination": slab_manifest["selected_termination"],
            "candidate_terminations": len(slab_manifest["terminations"]),
            "termination_selection": "non-polar, stoichiometric, symmetric, then fewest atoms",
            "settings": slab_manifest["settings"],
        },
        "files": {
            "bulk_structure": str(bulk_path),
            "surface_slab": slab_path,
            "surface_slab_extxyz": slab_manifest["files"]["surface_slab_extxyz"],
            "bulk_conventional": slab_manifest["files"]["bulk_conventional"],
            "slab_manifest": slab_manifest["files"]["slab_manifest"],
        },
        "checks": {
            "api_key_persisted": False,
            "bulk_used_directly_for_loading": False,
            "bulk_converted_to_conventional_cell": True,
            "surface_is_slab": slab_check,
            "validation_passed": result.validation.passed,
            "validation": result.validation.model_dump(),
        },
    }
    manifest_path = outdir / "surface_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["files"]["surface_manifest"] = str(manifest_path)
    if not result.validation.passed:
        codes = ", ".join(issue.code for issue in result.validation.errors)
        raise RuntimeError(f"Generated slab failed validation ({codes}); see {manifest_path}.")
    return manifest


def parse_repeat_xy(text: str) -> tuple[int, int] | None:
    if text.strip().lower() == "auto":
        return None
    repeat_xy = tuple(int(item) for item in text.split(","))
    if len(repeat_xy) != 2 or min(repeat_xy) < 1:
        raise ValueError("--repeat-xy requires 'auto' or two positive integers, e.g. 2,2.")
    return repeat_xy  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download an MP bulk crystal and generate a reviewed stable-facet slab.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--formula")
    source.add_argument("--material-id")
    parser.add_argument("--surface-facet", default=None, help="Explicit Miller index, e.g. 111, 1,1,1 or 0,0,0,1.")
    parser.add_argument("--min-slab-size", type=float, default=12.0)
    parser.add_argument("--min-vacuum-size", type=float, default=15.0)
    parser.add_argument("--repeat-xy", default="2,2", help="Two integers such as 2,2, or 'auto' for >= 8 A widths.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = download_stable_surface(
        args.output_dir,
        formula=args.formula,
        material_id=args.material_id,
        explicit_facet=args.surface_facet,
        min_slab_size=args.min_slab_size,
        min_vacuum_size=args.min_vacuum_size,
        repeat_xy=parse_repeat_xy(args.repeat_xy),
    )
    print(result["files"]["surface_slab"])
    print(result["files"]["surface_manifest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
