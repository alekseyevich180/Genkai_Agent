"""Pure amorphous surface slabs cut from a periodic amorphous bulk cell.

The in-plane cell of the slab is an integer supercell of the amorphous cell
itself, so the slab is exactly periodic in-plane without strain or seams. A
window of the requested thickness is cut along the surface normal, isolated
atoms left by the cut are removed, vacuum is added above, and the bottom part
(``fixed_fraction`` of the thickness, by height because amorphous slabs have
no discrete layers) is fixed. Each sample uses a different window, i.e. a
different amorphous surface.

The slabs follow the slab convention (c along z, tags 0 fixed / 1 free), so
they can be passed as ``--surface`` to the SAM, adsorbate and ALD builders.
They are unrelaxed cuts (evidence ``heuristic``); the cut surfaces are not
equilibrated and the composition is reported, never corrected.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from ase import Atoms
from ase.constraints import FixAtoms
from ase.data import covalent_radii

from .amorphous_overlayer import (
    OverlayerBuildError,
    check_amorphous_bulk,
    composition_report,
    density_g_cm3,
    remove_isolated,
)
from .sites import default_anchor_symbols, find_surface_sites
from ..structure_io import export_frames, read_structure, sha256_of, write_frames, write_manifest
from .substrate import fixed_below_fraction, lateral_widths, parse_export, parse_ints, surface_area


@dataclass
class AmorphousSlabSettings:
    thickness: float
    vacuum: float = 15.0
    min_lateral_size: float = 8.0
    repeat_xy: tuple[int, int] | None = None
    fixed_fraction: float = 0.5
    samples: int = 1
    seed: int = 42
    bottom_margin: float = 0.5

    def __post_init__(self) -> None:
        if self.thickness <= 0:
            raise OverlayerBuildError("The slab thickness must be positive.")
        if self.vacuum < 5.0:
            raise OverlayerBuildError("Use at least 5 A of vacuum.")
        if not 0.0 <= self.fixed_fraction < 1.0:
            raise OverlayerBuildError("fixed_fraction must satisfy 0 <= fixed_fraction < 1.")
        if self.samples < 1:
            raise OverlayerBuildError("samples must be >= 1.")
        if self.repeat_xy is not None and (len(self.repeat_xy) != 2 or min(self.repeat_xy) < 1):
            raise OverlayerBuildError("repeat_xy needs two positive integers.")


def standardize_cell(atoms: Atoms) -> Atoms:
    """Rigidly rotate so a lies along x and b in the xy plane (lengths and angles unchanged)."""
    rotated = atoms.copy()
    standard, _ = atoms.cell.standard_form()
    rotated.set_cell(standard, scale_atoms=True)
    return rotated


def _min_ratio(atoms: Atoms) -> float | None:
    if len(atoms) < 2:
        return None
    distances = atoms.get_all_distances(mic=True)
    radii = covalent_radii[atoms.numbers]
    ratio = distances / (radii[:, None] + radii[None, :])
    np.fill_diagonal(ratio, np.inf)
    return float(ratio.min())


def build_amorphous_slab(
    amorphous: Atoms,
    settings: AmorphousSlabSettings,
    rng: np.random.Generator,
    z0: float | None = None,
) -> tuple[Atoms, dict[str, Any]]:
    """Cut one slab; ``z0`` fixes the window start along the normal (default: random)."""
    bulk = standardize_cell(amorphous)
    a_vec, b_vec, c_vec = bulk.cell.array
    layer_height = float(c_vec[2])  # a and b lie in the xy plane, so c_z is the normal height
    if settings.repeat_xy is not None:
        reps = tuple(settings.repeat_xy)
    else:
        widths = lateral_widths(bulk)
        reps = tuple(max(1, int(np.ceil(settings.min_lateral_size / w - 1e-6))) for w in widths)
    nz = int(np.ceil(settings.thickness / layer_height)) + 1
    block = bulk.repeat((reps[0], reps[1], nz))
    # Cartesian positions keep the true geometry even for a tilted c; z is the normal coordinate.
    cartesian = block.get_positions(wrap=True)
    z = cartesian[:, 2]
    z0 = float(rng.uniform(0.0, layer_height)) if z0 is None else float(z0) % layer_height
    window = (z >= z0) & (z < z0 + settings.thickness)
    s1, s2 = block.cell.array[0], block.cell.array[1]
    positions = cartesian[window].copy()
    positions[:, 2] -= z0
    slab = Atoms(
        [s for s, keep in zip(block.get_chemical_symbols(), window) if keep],
        positions=positions,
        cell=[s1, s2, [0.0, 0.0, settings.thickness + settings.vacuum]],
        pbc=[True, True, False],
    )
    slab.wrap(pbc=[True, True, False])
    slab, isolated = remove_isolated(slab, pbc_in_plane=True)
    if len(slab) < 2:
        raise OverlayerBuildError("The cut slab is empty; increase the thickness.")
    slab.positions[:, 2] += settings.bottom_margin - float(slab.positions[:, 2].min())
    top = float(slab.positions[:, 2].max())
    slab.set_cell([s1, s2, [0.0, 0.0, top + settings.vacuum]])
    slab.pbc = True
    fixed = fixed_below_fraction(slab, settings.fixed_fraction) if settings.fixed_fraction > 0 else []
    tags = np.ones(len(slab), dtype=int)
    tags[fixed] = 0
    slab.set_tags(tags)
    if fixed:
        slab.set_constraint(FixAtoms(indices=fixed))
    thickness = float(np.ptp(slab.positions[:, 2]))
    area = surface_area(slab)
    sites = find_surface_sites(slab, default_anchor_symbols(slab))
    report = {
        "repeat_xy": list(reps),
        "z_window_start_A": round(z0, 4),
        "n_atoms": len(slab),
        "isolated_atoms_removed": isolated,
        "thickness_A": round(thickness, 4),
        "vacuum_above_A": round(float(slab.cell.array[2, 2]) - top, 4),
        "surface_area_A2": round(area, 4),
        # Volume of the cut window (same convention as the ALD film density), not the atom-centre span.
        "density_g_cm3": round(density_g_cm3(slab, area * settings.thickness), 4),
        "n_fixed": len(fixed),
        "fixed_policy": f"atoms below {settings.fixed_fraction:.2f} of the slab thickness",
        "composition": composition_report(slab, amorphous),
        "min_contact_ratio": round(_min_ratio(slab), 4) if len(slab) > 1 else None,
        "exposed_undercoordinated_cations": len(sites),
        "exposed_cation_density_per_nm2": round(len(sites) / (area / 100.0), 4),
    }
    return slab, report


@dataclass
class AmorphousSlabRunResult:
    frames: list[Atoms]
    manifest: dict[str, Any]
    structures_path: Path
    sample_paths: list[Path]
    manifest_path: Path
    exported: list[Path]


def run_amorphous_slab(
    amorphous_path: str | Path,
    settings: AmorphousSlabSettings,
    output_dir: str | Path,
    *,
    amorphous_format: str | None = None,
    export: Sequence[str] = ("cif",),
) -> AmorphousSlabRunResult:
    """Cut ``settings.samples`` amorphous slabs; write one extxyz per sample plus a combined file."""
    outdir = Path(output_dir)
    amorphous, used = read_structure(amorphous_path, amorphous_format)
    amorphous.pbc = True
    check_amorphous_bulk(amorphous)
    rng = np.random.default_rng(settings.seed)
    frames: list[Atoms] = []
    reports: list[dict[str, Any]] = []
    sample_paths: list[Path] = []
    for sample in range(settings.samples):
        slab, report = build_amorphous_slab(amorphous, settings, rng)
        slab.info.update({"task": "amorphous_slab", "role": "amorphous_slab", "sample": sample, "frame_id": sample})
        frames.append(slab)
        reports.append({"sample": sample, **report})
        sample_paths.append(write_frames(outdir / f"amorphous_slab_{sample:03d}.extxyz", [slab]))
    structures_path = write_frames(outdir / "amorphous_slab_structures.extxyz", frames)
    exported = export_frames(frames, outdir / "exports", "amorphous_slab", export) if export else []
    issues = [
        f"sample {r['sample']}: no fixed atoms" for r in reports if r["n_fixed"] == 0 and settings.fixed_fraction > 0
    ]
    manifest = {
        "schema_version": "1.0",
        "generator": "genkai.modeling.surface.builders.amorphous_slab",
        "mode": "structure-only",
        "calculator": "none",
        "evidence_level": "heuristic",
        "scientific_calculation_started": False,
        "energies_available": False,
        "note": (
            "Pure amorphous surface cut from the supplied periodic amorphous bulk; in-plane periodicity is exact, "
            "the cut surfaces are unrelaxed and the composition is not corrected."
        ),
        "amorphous": {
            "path": Path(amorphous_path).as_posix(),
            "format": used,
            "sha256": sha256_of(amorphous_path),
            "formula": amorphous.get_chemical_formula(mode="hill"),
            "n_atoms": len(amorphous),
            "cell_lengths_A": [round(v, 4) for v in amorphous.cell.lengths()],
            "density_g_cm3": round(density_g_cm3(amorphous, float(amorphous.get_volume())), 4),
            "min_contact_ratio": round(_min_ratio(amorphous), 4),
        },
        "settings": asdict(settings),
        "samples": reports,
        "files": {
            "structures": structures_path.as_posix(),
            "samples": [p.as_posix() for p in sample_paths],
            "exports": [p.as_posix() for p in exported],
        },
        "validation": {"issues": issues},
        "conventions": {
            "tags": "0 = fixed bottom, 1 = free",
            "use_as_substrate": "pass an amorphous_slab_NNN.extxyz file as --surface to the SAM, adsorbate or ALD builders",
        },
    }
    manifest_path = write_manifest(outdir / "amorphous_slab_manifest.json", manifest)
    return AmorphousSlabRunResult(frames, manifest, structures_path, sample_paths, manifest_path, exported)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cut pure amorphous surface slabs from a periodic amorphous bulk cell (geometry only)."
    )
    parser.add_argument("--amorphous", type=Path, required=True, help="Periodic amorphous bulk cell (CIF by default; any ASE format).")
    parser.add_argument("--amorphous-format", default=None)
    parser.add_argument("--thickness", type=float, required=True, help="Slab thickness in A.")
    parser.add_argument("--vacuum", type=float, default=15.0, help="Vacuum above the slab in A.")
    parser.add_argument("--min-lateral-size", type=float, default=8.0, help="Repeat the amorphous cell in-plane to this width (A).")
    parser.add_argument("--repeat-xy", default=None, help="Explicit in-plane repeats of the amorphous cell, e.g. 2,2.")
    parser.add_argument("--fixed-fraction", type=float, default=0.5, help="Fix atoms below this fraction of the thickness.")
    parser.add_argument("--samples", type=int, default=1, help="Different cut windows (different surfaces).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--export", default="cif", help="Comma-separated export formats (cif, vasp) or 'none'.")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        repeat = parse_ints(args.repeat_xy)
        settings = AmorphousSlabSettings(
            thickness=args.thickness,
            vacuum=args.vacuum,
            min_lateral_size=args.min_lateral_size,
            repeat_xy=repeat,  # type: ignore[arg-type]
            fixed_fraction=args.fixed_fraction,
            samples=args.samples,
            seed=args.seed,
        )
        result = run_amorphous_slab(
            args.amorphous, settings, args.output_dir, amorphous_format=args.amorphous_format, export=parse_export(args.export)
        )
    except (OverlayerBuildError, ValueError, FileNotFoundError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    manifest = result.manifest
    bulk = manifest["amorphous"]
    print(f"Amorphous: {bulk['formula']} ({bulk['density_g_cm3']} g/cm^3, format {bulk['format']})")
    for sample in manifest["samples"]:
        comp = sample["composition"]
        print(
            f"  sample {sample['sample']}: {comp['formula']} ({sample['n_atoms']} atoms), thickness {sample['thickness_A']} A, "
            f"anion/cation {comp['anion_to_cation_ratio']} vs {comp['reference_anion_to_cation_ratio']}, "
            f"{sample['n_fixed']} fixed, {sample['exposed_undercoordinated_cations']} exposed cation sites"
        )
    for issue in manifest["validation"]["issues"]:
        print(f"WARNING {issue}")
    print(f"Wrote {result.structures_path} and {len(result.sample_paths)} per-sample file(s); manifest {result.manifest_path}")
    return 0 if not manifest["validation"]["issues"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
