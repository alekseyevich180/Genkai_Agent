"""Relax (or single-point) given structures with an energy model.

The pipeline uses this method for intermediate relaxations (``method: relax``) and
to rank the candidates of a step by energy (``pick: lowest_energy``). Every frame of
the input file is relaxed independently (``FixAtoms`` honoured, cell fixed unless
``--relax-cell``), keeps its per-atom arrays (e.g. the ``component`` labels) and is
written in the input order to ``relaxed_structures.extxyz``; energies, forces and
convergence go to ``relax_manifest.json``.

Needs forces: ``uma`` or ``mace`` (``emt`` only for its metals and tests). The mock
``calculator=none`` is refused because its energies have no physical meaning.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.calculators.calculator import Calculator

from ..mlip.calculators import CALCULATORS, add_mace_arguments, build_calculator, evidence_for, relax
from ..structure_io import components, read_frames, sha256_of, write_frames, write_manifest

GENERATOR = "genkai.modeling.surface.screening.relax"


class RelaxError(ValueError):
    """Inputs or settings that cannot be relaxed."""


@dataclass
class RelaxSettings:
    fmax: float = 0.05
    max_steps: int = 200  # 0 = single point
    relax_cell: bool = False

    def __post_init__(self) -> None:
        if self.fmax <= 0 or self.max_steps < 0:
            raise RelaxError("fmax must be positive and max_steps >= 0.")


def _max_force(atoms: Atoms) -> float:
    forces = atoms.get_forces()  # FixAtoms zeroes the fixed rows
    return float(np.linalg.norm(forces, axis=1).max()) if len(atoms) else 0.0


def run_relax(
    structures_path: str | Path,
    settings: RelaxSettings,
    output_dir: str | Path,
    *,
    calculator: Calculator,
    calculator_name: str,
    model: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if calculator_name == "none":
        raise RelaxError("calculator=none has zero forces and meaningless energies; use uma or mace (emt for its metals).")
    outdir = Path(output_dir)
    frames = read_frames(structures_path)
    if not frames:
        raise RelaxError(f"{structures_path} contains no structure.")
    relaxed: list[Atoms] = []
    records: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        atoms = frame.copy()
        info = dict(frame.info)
        clock = time.perf_counter()
        energy = relax(atoms, calculator, fmax=settings.fmax, steps=settings.max_steps, cell=settings.relax_cell)
        max_force = _max_force(atoms)
        out = atoms.copy()  # drops the calculator; per-atom arrays and constraints stay
        out.arrays.pop("momenta", None)
        out.info = info
        relaxed.append(out)
        records.append({
            "index": index,
            "formula": out.get_chemical_formula(mode="hill"),
            "n_atoms": len(out),
            "energy_eV": round(energy, 6),
            "energy_per_atom_eV": round(energy / len(out), 6),
            "max_force_eV_A": round(max_force, 5),
            "converged": settings.max_steps == 0 or max_force <= settings.fmax * 1.0001,
            "components": dict(Counter(components(out).tolist())),
            "label": info.get("pipeline_label"),
            "seconds": round(time.perf_counter() - clock, 2),
        })
    structures_out = write_frames(outdir / "relaxed_structures.extxyz", relaxed)
    manifest = {
        "schema_version": "1.0",
        "generator": GENERATOR,
        "mode": "single-point" if settings.max_steps == 0 else "relaxation",
        "calculator": calculator_name,
        "model": model or {},
        "evidence_level": evidence_for(calculator_name),
        "scientific_calculation_started": True,
        "energies_available": True,
        "note": "Energies are comparable only between structures with the same composition and the same model.",
        "input": {"path": Path(structures_path).as_posix(), "sha256": sha256_of(structures_path), "frames": len(frames)},
        "settings": asdict(settings),
        "frames": records,
        "files": {"structures": structures_out.as_posix()},
        "validation": {"not_converged": [r["index"] for r in records if not r["converged"]]},
    }
    write_manifest(outdir / "relax_manifest.json", manifest)
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Relax (or single-point with --max-steps 0) every frame of a structure file with uma or mace."
    )
    parser.add_argument("--structures", type=Path, required=True, help="Structure file; extxyz may hold several frames.")
    parser.add_argument("--fmax", type=float, default=0.05)
    parser.add_argument("--max-steps", type=int, default=200, help="LBFGS step limit; 0 = single point.")
    parser.add_argument("--relax-cell", action="store_true", help="Also relax the cell (bulk cells; keep off for slabs).")
    parser.add_argument("--calculator", choices=CALCULATORS, default="none",
                        help="uma or mace (real MLIP, needs authorization); emt for its metals; none is refused.")
    parser.add_argument("--uma-model", default="uma-s-1p2")
    parser.add_argument("--task-name", default="omat")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--include-d3", action="store_true")
    add_mace_arguments(parser)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        settings = RelaxSettings(fmax=args.fmax, max_steps=args.max_steps, relax_cell=args.relax_cell)
        if args.calculator == "none":
            raise RelaxError("calculator=none has zero forces and meaningless energies; use uma or mace (emt for its metals).")
        calculator = build_calculator(
            args.calculator, uma_model=args.uma_model, task_name=args.task_name, device=args.device,
            include_d3=args.include_d3, mace_model=args.mace_model, mace_dtype=args.mace_dtype,
        )
        model = {"device": args.device}
        if args.calculator == "uma":
            model.update(uma_model=args.uma_model, task_name=args.task_name, include_d3=args.include_d3)
        elif args.calculator == "mace":
            model.update(mace_model=args.mace_model, mace_dtype=args.mace_dtype)
        manifest = run_relax(args.structures, settings, args.output_dir, calculator=calculator,
                             calculator_name=args.calculator, model=model)
    except (RelaxError, ValueError, FileNotFoundError, ImportError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    for row in manifest["frames"]:
        print(f"  frame {row['index']}: {row['formula']} E = {row['energy_eV']:.6f} eV, "
              f"max force {row['max_force_eV_A']} eV/A{'' if row['converged'] else ' (not converged)'}")
    print(f"Wrote {manifest['files']['structures']} ({manifest['evidence_level']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
