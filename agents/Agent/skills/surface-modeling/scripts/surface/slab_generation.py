"""Generate a validated surface slab from a bulk crystal with pymatgen.

Thin skill entry over ``genkai.modeling.slab``. The bulk comes from a local
file (``--bulk``) or Materials Project (``--formula`` / ``--material-id``).

Facet order: ``--facet`` -> surface-energy ranking when ``--calculator`` is
``emt`` or ``uma`` (Wulff area fraction over facets up to ``--max-index``) ->
reviewed stable-facet registry -> stop for manual review.

Outputs in ``--output-dir``: ``<prefix>.vasp`` (selective dynamics for the
fixed bottom), ``<prefix>.extxyz`` (tags: 0 fixed, 1 surface region),
``bulk_conventional.cif``, ``<prefix>_manifest.json`` and ``run_config.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from genkai.modeling.slab import (
        SlabSettings,
        build_slab,
        energy_function_from_calculator,
        write_slab_outputs,
    )
except ModuleNotFoundError:  # source checkout without an installed package
    _REPO_ROOT = Path(__file__).resolve().parents[6]
    sys.path[:0] = [str(_REPO_ROOT / "src"), str(_REPO_ROOT)]
    from genkai.modeling.slab import (
        SlabSettings,
        build_slab,
        energy_function_from_calculator,
        write_slab_outputs,
    )


FACET_EVIDENCE = {
    "explicit": "paper_extracted_or_user",
    "stable_facet_registry": "heuristic",
    "structure_family_registry": "heuristic",
}


def load_bulk(path: Path):
    from pymatgen.core import Structure

    try:
        return Structure.from_file(str(path))
    except Exception:
        from ase.io import read
        from pymatgen.io.ase import AseAtomsAdaptor

        return AseAtomsAdaptor.get_structure(read(path))


def build_calculator(name: str, uma_model: str, task_name: str, device: str) -> Any:
    if name == "none":
        return None
    if name == "emt":
        from ase.calculators.emt import EMT

        return EMT()
    from fairchem.core import FAIRChemCalculator, pretrained_mlip

    predictor = pretrained_mlip.get_predict_unit(uma_model, device=device)
    return FAIRChemCalculator(predictor, task_name=task_name)


def parse_repeat_xy(text: str) -> tuple[int, int] | None:
    if text.strip().lower() == "auto":
        return None
    values = tuple(int(item) for item in text.split(","))
    if len(values) != 2 or min(values) < 1:
        raise ValueError("--repeat-xy requires 'auto' or two positive integers, e.g. 3,3.")
    return values  # type: ignore[return-value]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = SlabSettings(
        min_slab_size=args.min_slab_size,
        min_vacuum_size=args.min_vacuum_size,
        min_lateral_size=args.min_lateral_size,
        repeat_xy=parse_repeat_xy(args.repeat_xy),
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
        from materials_project_slab import fetch_bulk_structure

        bulk, metadata = fetch_bulk_structure(formula=args.formula, material_id=args.material_id)
        source = {"type": "materials_project", **metadata}
        formula, spacegroup = metadata["formula"], metadata.get("spacegroup_symbol")

    calculator = build_calculator(args.calculator, args.uma_model, args.task_name, args.device)
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
