"""Energy-based search of SAM structures (MLIP screening).

Pipeline for one molecule and a user-chosen binding mode::

    references   E_slab (bottom fixed, relaxed), E_mol (isolated, in a box),
                 E_H2 when acidic H is removed instead of moved to a surface O
    stage 1      Periodic GP over the *anchored* parameters - site group,
                 tilt, azimuth: geometric placement (SamBuilder.assemble), short
                 relaxation, E_ads; the designed anchor bonds must survive
    stage 2      full relaxation of the best distinct trials -> ranked structures
    coverage     the best relaxed molecule (with its transferred H) is copied by
                 translation onto translation-equivalent site groups, the whole
                 layer is relaxed and E_ads per molecule is reported per count

E_ads(n) = E_total - E_slab - n E_mol (+ 1/2 E_H2 per removed H). Moving the
acidic H to a surface O keeps the composition, so binding modes and placements
are compared on equal terms. Copying needs translation-equivalent sites
(crystalline facets); amorphous surfaces have none and need a search per site.

``calculator="none"`` uses a mock contact score (no physical meaning) so the
pipeline can be tested locally; ``uma``/``mace`` is a real MLIP calculation and needs
authorization. MLIP energies are screening values, not DFT evidence.
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from ase import Atoms
from ase.data import covalent_radii
from ase.io import read, write

from .calculators import (
    CALCULATORS,
    MOCK_NOTE,
    build_calculator,
    evidence_for,
    is_mock,
    molecule_in_box,
    relax,
    resolve_mace_model,
)
from .sam import (
    ACIDIC_H_POLICIES,
    ANCHOR_KINDS,
    CLASH_FRACTION,
    SamBuildError,
    SamBuilder,
    SamSettings,
    _min_contact_ratio,
    resolve_anchor_group,
)
from .search_sampler import DEFAULT_SAMPLER, add_sampler_argument, make_sampler
from .sites import in_plane_mic, unwrap_group
from .structure_io import export_frames, read_molecule, sha256_of, write_frames, write_manifest
from .substrate import Substrate, add_substrate_arguments, parse_export, parse_ints, substrate_from_args, surface_area

FAILED_PLACEMENT_ENERGY = 1.0e6
LOST_BINDING_PENALTY = 10.0  # eV added to the Optuna objective when an anchor bond breaks
EV_PER_A2_TO_J_PER_M2 = 16.021766208


@dataclass
class SamSearchSettings:
    n_trials: int = 30
    top_k: int = 3
    max_tilt: float = 60.0
    screen_steps: int = 20
    max_steps: int = 200
    fmax: float = 0.05
    seed: int = 42
    binding_tolerance: float = 0.5
    coverage_counts: tuple[int, ...] = (1,)
    equivalence_tolerance: float = 0.3
    environment_radius: float = 4.5
    calculator: str = "none"
    uma_model: str = "uma-s-1p2"
    task_name: str = "omat"
    device: str = "cuda"
    include_d3: bool = False
    mace_model: str | None = None
    mace_dtype: str = "float32"
    sampler: str = DEFAULT_SAMPLER

    def __post_init__(self) -> None:
        if self.calculator == "mace":
            self.mace_model = resolve_mace_model(self.mace_model)
        if self.calculator not in CALCULATORS:
            raise SamBuildError(f"calculator must be one of {', '.join(CALCULATORS)}.")
        if self.n_trials < 1 or self.top_k < 1:
            raise SamBuildError("n_trials and top_k must be >= 1.")
        if not 0.0 <= self.max_tilt < 90.0:
            raise SamBuildError("max_tilt must satisfy 0 <= max_tilt < 90.")
        if min(self.coverage_counts) < 1:
            raise SamBuildError("coverage counts must be positive.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_json(atoms: Atoms) -> str:
    """Serialize for Optuna user attributes; extxyz keeps FixAtoms, tags and per-atom arrays (ASE json does not)."""
    buffer = io.StringIO()
    write(buffer, atoms, format="extxyz")
    return buffer.getvalue()


def _from_json(text: str) -> Atoms:
    return read(io.StringIO(text), format="extxyz")


def binding_check(atoms: Atoms, designed: Sequence[tuple[int, int]], tolerance: float) -> tuple[bool, float]:
    """All designed bonds (anchor-site, transferred H-O) within covalent sum + tolerance (minimum image)."""
    worst = 0.0
    for i, j in designed:
        distance = float(atoms.get_distance(i, j, mic=True))
        target = float(covalent_radii[atoms.numbers[i]] + covalent_radii[atoms.numbers[j]])
        worst = max(worst, distance - target)
    return worst <= tolerance, worst


def removed_hydrogens(molecules: Sequence[Any]) -> int:
    return sum(
        1 for molecule in molecules for entry in molecule.h_handling if entry["action"] in ("removed", "removed_no_acceptor")
    )


def equivalent_groups(
    slab: Atoms,
    groups: Sequence[tuple[int, ...]],
    reference: tuple[int, ...],
    tolerance: float,
    environment_radius: float,
) -> list[tuple[tuple[int, ...], np.ndarray, dict[int, int]]]:
    """Site groups equal to ``reference`` up to an in-plane translation (sites and surroundings).

    Returns (group, translation, reference-site -> group-site map), the reference itself first.
    """
    symbols = slab.get_chemical_symbols()
    positions = slab.get_positions()
    ref_sites = unwrap_group(slab, reference)
    ref_centre = ref_sites.mean(axis=0)
    deltas = in_plane_mic(slab, positions - ref_centre)
    near = np.flatnonzero(np.linalg.norm(deltas, axis=1) <= environment_radius)
    environment = [(symbols[k], deltas[k]) for k in near]

    def occupied(symbol: str, point: np.ndarray) -> int | None:
        gaps = np.linalg.norm(in_plane_mic(slab, positions - point), axis=1)
        for k in np.argsort(gaps)[:4]:
            if gaps[k] <= tolerance and symbols[k] == symbol:
                return int(k)
        return None

    result = []
    for group in groups:
        if len(group) != len(reference):
            continue
        centre = unwrap_group(slab, group).mean(axis=0)
        shift = in_plane_mic(slab, centre - ref_centre)[0]
        if abs(shift[2]) > tolerance:
            continue
        mapping: dict[int, int] = {}
        for k, site in enumerate(reference):
            match = occupied(symbols[site], ref_sites[k] + shift)
            if match is None or match not in group:
                break
            mapping[int(site)] = match
        else:
            if all(occupied(symbol, ref_centre + vector + shift) is not None for symbol, vector in environment):
                result.append((tuple(group), shift, mapping))
    result.sort(key=lambda item: (tuple(item[0]) != tuple(reference), np.linalg.norm(item[1])))
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@dataclass
class SamSearchResult:
    frames: list[Atoms]
    manifest: dict[str, Any]
    structures_path: Path
    manifest_path: Path
    exported: list[Path]


def _e_ads(total: float, n_molecules: int, n_removed_h: int, refs: dict[str, float]) -> float:
    value = total - refs["E_slab"] - n_molecules * refs["E_mol"]
    if n_removed_h:
        value += 0.5 * n_removed_h * refs["E_H2"]
    return value


def run_sam_search(
    substrate: Substrate,
    molecule_path: str | Path,
    sam_settings: SamSettings,
    search: SamSearchSettings,
    output_dir: str | Path,
    *,
    molecule_format: str | None = None,
    anchor_kind: str | None = None,
    anchor_atoms: Sequence[int] | None = None,
    export: Sequence[str] = ("cif",),
) -> SamSearchResult:
    import optuna

    outdir = Path(output_dir)
    molecule, molecule_format_used = read_molecule(molecule_path, molecule_format)
    group = resolve_anchor_group(molecule, anchor_kind, anchor_atoms)
    builder = SamBuilder(substrate.atoms, molecule, group, sam_settings)
    calc = build_calculator(
        search.calculator,
        uma_model=search.uma_model,
        task_name=search.task_name,
        device=search.device,
        include_d3=search.include_d3,
        mace_model=search.mace_model,
        mace_dtype=search.mace_dtype,
    )
    notes: list[str] = [MOCK_NOTE] if is_mock(search.calculator) else []

    # References (same calculator and settings for every energy that is compared).
    clean = builder.substrate.copy()
    refs = {"E_slab": relax(clean, calc, fmax=search.fmax, steps=search.max_steps)}
    refs["E_mol"] = relax(molecule_in_box(molecule), calc, fmax=search.fmax, steps=search.max_steps)
    # Needed whenever an acidic H leaves the system ("remove" policy, or no acceptor O found).
    h2 = molecule_in_box(Atoms("H2", positions=[[0, 0, 0], [0, 0, 0.74]]))
    refs["E_H2"] = relax(h2, calc, fmax=search.fmax, steps=search.max_steps)

    # Stage 1: Optuna over anchored parameters.
    groups = builder.groups
    previous = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial: Any) -> float:
        index = trial.suggest_int("group", 0, len(groups) - 1)
        tilt = trial.suggest_float("tilt", 0.0, search.max_tilt) if search.max_tilt > 0 else 0.0
        azimuth = trial.suggest_float("azimuth", 0.0, 360.0)
        placed = builder.assemble([(groups[index], tilt, azimuth)], seed=search.seed + trial.number)
        if placed.atoms is None:
            trial.set_user_attr("status", "placement_failed")
            return FAILED_PLACEMENT_ENERGY
        atoms = placed.atoms.copy()
        total = relax(atoms, calc, fmax=search.fmax, steps=search.screen_steps)
        e_ads = _e_ads(total, 1, removed_hydrogens(placed.molecules), refs)
        retained, worst = binding_check(atoms, placed.designed, search.binding_tolerance)
        atoms.calc = None
        trial.set_user_attr("status", "ok" if retained else "binding_lost")
        trial.set_user_attr("E_ads_screen_eV", e_ads)
        trial.set_user_attr("worst_bond_excess_A", worst)
        trial.set_user_attr("structure", _to_json(atoms))
        trial.set_user_attr("designed", [list(pair) for pair in placed.designed])
        trial.set_user_attr("removed_h", removed_hydrogens(placed.molecules))
        return e_ads + (0.0 if retained else LOST_BINDING_PENALTY)

    try:
        sampler = make_sampler(search.sampler, seed=search.seed, periodic=("azimuth",), categorical=("group",))
        study = optuna.create_study(direction="minimize", sampler=sampler)
        study.optimize(objective, n_trials=search.n_trials)
    finally:
        optuna.logging.set_verbosity(previous)

    trial_rows = []
    for trial in study.trials:
        params = trial.params
        trial_rows.append(
            {
                "trial": trial.number,
                "group": [int(i) for i in groups[params["group"]]] if "group" in params else None,
                "tilt_deg": round(params.get("tilt", 0.0), 3),
                "azimuth_deg": round(params.get("azimuth", 0.0), 3),
                "status": trial.user_attrs.get("status"),
                "E_ads_screen_eV": trial.user_attrs.get("E_ads_screen_eV"),
            }
        )

    # Stage 2: full relaxation of the best distinct trials (binding retained first).
    candidates = [t for t in study.trials if t.user_attrs.get("status") in ("ok", "binding_lost")]
    candidates.sort(key=lambda t: (t.user_attrs["status"] != "ok", t.user_attrs["E_ads_screen_eV"]))
    chosen: list[Any] = []
    for trial in candidates:
        key = (trial.params["group"], round(trial.params.get("tilt", 0.0) / 5.0), round(trial.params["azimuth"] / 15.0))
        if all(key != (c.params["group"], round(c.params.get("tilt", 0.0) / 5.0), round(c.params["azimuth"] / 15.0)) for c in chosen):
            chosen.append(trial)
        if len(chosen) == search.top_k:
            break
    if not chosen:
        raise SamBuildError("No Optuna trial produced a placement; check the binding mode, site symbols and cell size.")

    singles = []
    for rank_input in chosen:
        atoms = _from_json(rank_input.user_attrs["structure"])
        total = relax(atoms, calc, fmax=search.fmax, steps=search.max_steps)
        designed = [tuple(pair) for pair in rank_input.user_attrs["designed"]]
        retained, worst = binding_check(atoms, designed, search.binding_tolerance)
        e_ads = _e_ads(total, 1, rank_input.user_attrs["removed_h"], refs)
        atoms.calc = None
        singles.append(
            {
                "trial": rank_input.number,
                "group": [int(i) for i in groups[rank_input.params["group"]]],
                "tilt_deg": round(rank_input.params.get("tilt", 0.0), 3),
                "azimuth_deg": round(rank_input.params["azimuth"], 3),
                "E_ads_eV": e_ads,
                "binding_retained": retained,
                "worst_bond_excess_A": round(worst, 4),
                "removed_h": int(rank_input.user_attrs["removed_h"]),
                "atoms": atoms,
                "designed": designed,
            }
        )
    singles.sort(key=lambda s: (not s["binding_retained"], s["E_ads_eV"]))
    best = singles[0]

    # Coverage by copying the best relaxed molecule onto translation-equivalent sites.
    coverage_reports: list[dict[str, Any]] = []
    coverage_frames: list[Atoms] = []
    extra_counts = sorted({c for c in search.coverage_counts if c > 1})
    if extra_counts:
        reference_group = tuple(best["group"])
        equivalents = equivalent_groups(
            builder.substrate, groups, reference_group, search.equivalence_tolerance, search.environment_radius
        )
        order = _spread_order(builder.substrate, equivalents)
        for count in extra_counts:
            report: dict[str, Any] = {"requested_count": count, "equivalent_site_groups": len(equivalents)}
            chosen_groups = _disjoint(order, count)
            if len(chosen_groups) < count:
                report["error"] = (
                    f"Only {len(chosen_groups)} disjoint translation-equivalent site group(s) for count {count} "
                    f"({len(equivalents)} equivalent of {len(groups)}); sites of amorphous or low-symmetry surfaces "
                    "are not equivalent - search each molecule separately or enlarge the cell."
                )
                coverage_reports.append(report)
                continue
            layer, designed = _replicate(best["atoms"], best["designed"], chosen_groups)
            ratio = _min_contact_ratio(layer, layer.arrays["fragment_id"], designed)
            if ratio is not None and ratio < CLASH_FRACTION:
                report["error"] = f"Copied molecules overlap (contact ratio {ratio:.3f} < {CLASH_FRACTION})."
                coverage_reports.append(report)
                continue
            total = relax(layer, calc, fmax=search.fmax, steps=search.max_steps)
            retained, worst = binding_check(layer, designed, search.binding_tolerance)
            e_ads = _e_ads(total, count, count * best["removed_h"], refs)
            layer.calc = None
            layer.info.update({"task": "sam_search", "role": "sam_coverage", "molecule_count": count})
            report.update(
                {
                    "site_groups": [[int(i) for i in g] for g, _, _ in chosen_groups],
                    "E_ads_total_eV": e_ads,
                    "E_ads_per_molecule_eV": e_ads / count,
                    "density_per_nm2": round(count / (surface_area(layer) / 100.0), 4),
                    "binding_retained": retained,
                    "worst_bond_excess_A": round(worst, 4),
                }
            )
            coverage_reports.append(report)
            coverage_frames.append(layer)

    # Frames: clean (relaxed) slab, ranked single molecules, coverage layers.
    clean.calc = None
    clean.info.update({"task": "sam_search", "role": "clean_slab_relaxed"})
    frames: list[Atoms] = [clean]
    for rank, single in enumerate(singles, start=1):
        atoms = single.pop("atoms")
        single.pop("designed")
        atoms.info.update({"task": "sam_search", "role": "sam_single_ranked", "rank": rank})
        frames.append(atoms)
    frames.extend(coverage_frames)
    for frame_id, frame in enumerate(frames):
        frame.info["frame_id"] = frame_id

    structures_path = write_frames(outdir / "sam_search_structures.extxyz", frames)
    exported = export_frames(frames, outdir / "exports", "sam_search", export) if export else []
    manifest = {
        "schema_version": "1.0",
        "generator": "genkai.modeling.surface.sam_search",
        "calculator": search.calculator,
        "evidence_level": evidence_for(search.calculator),
        "energies_meaningful": not is_mock(search.calculator),
        "scientific_calculation_started": not is_mock(search.calculator),
        "note": "MLIP screening values, not DFT evidence." if not is_mock(search.calculator) else MOCK_NOTE,
        "substrate": substrate.record,
        "molecule": {
            "path": Path(molecule_path).as_posix(),
            "format": molecule_format_used,
            "sha256": sha256_of(molecule_path),
            "formula": molecule.get_chemical_formula(mode="hill"),
            "anchor_group": group.summary(molecule),
        },
        "binding": {
            "mode": sam_settings.binding_mode,
            "acidic_h_policy": builder.h_policy,
            "site_selection": builder.site_selection,
            "site_groups_available": len(groups),
        },
        "references_eV": refs,
        "energy_definition": "E_ads(n) = E_total - E_slab - n E_mol (+ 1/2 E_H2 per removed acidic H)",
        "search": asdict(search),
        "trials": trial_rows,
        "ranked_single_molecule": singles,
        "coverage": coverage_reports,
        "files": {"structures": structures_path.as_posix(), "exports": [p.as_posix() for p in exported]},
        "validation": {"notes": notes},
        "conventions": {"frames": "0 = relaxed clean slab, then ranked single-molecule structures, then coverage layers"},
    }
    manifest_path = write_manifest(outdir / "sam_search_manifest.json", manifest)
    return SamSearchResult(frames, manifest, structures_path, manifest_path, exported)


def _spread_order(slab: Atoms, equivalents: list[tuple[tuple[int, ...], np.ndarray, dict[int, int]]]) -> list:
    """Reference first, then farthest-first by in-plane distance (minimum image)."""
    if not equivalents:
        return []
    order = [equivalents[0]]
    remaining = list(equivalents[1:])
    while remaining:
        def spread(item):
            return min(
                float(np.linalg.norm(in_plane_mic(slab, item[1] - chosen[1])[0][:2])) for chosen in order
            )

        best = max(remaining, key=spread)
        order.append(best)
        remaining.remove(best)
    return order


def _disjoint(order: list, count: int) -> list:
    chosen: list = []
    used: set[int] = set()
    for item in order:
        if used & set(item[0]):
            continue
        chosen.append(item)
        used.update(item[0])
        if len(chosen) == count:
            break
    return chosen


def _replicate(single: Atoms, designed: Sequence[tuple[int, int]], placements: list) -> tuple[Atoms, list[tuple[int, int]]]:
    """Copy fragment 1 (molecule + its transferred H) by each translation; keep slab and constraints."""
    layer = single.copy()
    fragment = layer.arrays["fragment_id"]
    molecule_idx = np.flatnonzero(fragment == 1)
    slab_idx = np.flatnonzero(fragment == 0)
    index_in_copy = {int(old): k for k, old in enumerate(molecule_idx)}
    new_designed = list(designed)
    for copy_number, (group, shift, mapping) in enumerate(placements[1:], start=2):
        start = len(layer)
        piece = single[molecule_idx]
        piece.set_constraint()
        piece.positions += shift
        piece.arrays["fragment_id"][:] = copy_number
        layer.extend(piece)
        for i, j in designed:
            if int(i) in index_in_copy:
                partner = mapping.get(int(j))
                if partner is None:  # transferred H: its acceptor O is the translated slab O
                    target = layer.positions[int(j)] + shift
                    gaps = np.linalg.norm(in_plane_mic(layer, layer.positions[slab_idx] - target), axis=1)
                    partner = int(slab_idx[int(np.argmin(gaps))])
                new_designed.append((start + index_in_copy[int(i)], partner))
    tags = layer.get_tags()
    tags[len(single):] = 2
    layer.set_tags(tags)
    return layer, new_designed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Energy-based (MLIP) search of SAM structures: Optuna over anchored placements, then coverage by copying."
    )
    add_substrate_arguments(parser)
    parser.add_argument("--molecule", type=Path, required=True)
    parser.add_argument("--molecule-format", default=None)
    parser.add_argument("--anchor-kind", choices=ANCHOR_KINDS, default=None)
    parser.add_argument("--anchor-atoms", default=None)
    parser.add_argument("--binding-mode", required=True)
    parser.add_argument("--acidic-h", choices=ACIDIC_H_POLICIES, default="auto")
    parser.add_argument("--site-symbols", default=None)
    parser.add_argument("--bond-length", type=float, default=None)
    parser.add_argument("--max-span", type=float, default=None)
    parser.add_argument(
        "--search-calculator",
        choices=CALCULATORS,
        default="none",
        help="Search energy model: UMA (--uma-model/--task-name) or MACE (--mace-model); none = mock.",
    )
    parser.add_argument("--include-d3", action="store_true")
    parser.add_argument("--n-trials", type=int, default=30)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-tilt", type=float, default=60.0)
    parser.add_argument("--screen-steps", type=int, default=20, help="Relaxation steps per Optuna trial.")
    parser.add_argument("--max-steps", type=int, default=200, help="Relaxation steps for references and final structures.")
    parser.add_argument("--fmax", type=float, default=0.05)
    parser.add_argument("--coverage-counts", default="1", help="Molecule counts built by copying the best molecule, e.g. 1,2,3.")
    parser.add_argument("--binding-tolerance", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    add_sampler_argument(parser)
    parser.add_argument("--export", default="cif")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        sam_settings = SamSettings(
            binding_mode=args.binding_mode,
            coverage_counts=(1,),
            bond_length=args.bond_length,
            acidic_h=args.acidic_h,
            site_symbols=tuple(s.strip() for s in args.site_symbols.split(",")) if args.site_symbols else None,
            max_span=args.max_span,
            seed=args.seed,
        )
        search = SamSearchSettings(
            n_trials=args.n_trials,
            top_k=args.top_k,
            max_tilt=args.max_tilt,
            screen_steps=args.screen_steps,
            max_steps=args.max_steps,
            fmax=args.fmax,
            seed=args.seed,
            binding_tolerance=args.binding_tolerance,
            coverage_counts=parse_ints(args.coverage_counts) or (1,),
            calculator=args.search_calculator,
            uma_model=args.uma_model,
            task_name=args.task_name,
            device=args.device,
            include_d3=args.include_d3,
            mace_model=args.mace_model,
            mace_dtype=args.mace_dtype,
            sampler=args.sampler,
        )
        substrate = substrate_from_args(args)
        result = run_sam_search(
            substrate,
            args.molecule,
            sam_settings,
            search,
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
    for note in manifest["validation"]["notes"]:
        print(f"NOTE {note}")
    print(f"Calculator {manifest['calculator']}; references {manifest['references_eV']}")
    for rank, single in enumerate(manifest["ranked_single_molecule"], start=1):
        print(
            f"  rank {rank}: group {single['group']} tilt {single['tilt_deg']} az {single['azimuth_deg']} "
            f"E_ads {single['E_ads_eV']:.4f} eV, binding retained {single['binding_retained']}"
        )
    failed = [c for c in manifest["coverage"] if "error" in c]
    for cov in manifest["coverage"]:
        if "error" in cov:
            print(f"  coverage {cov['requested_count']}: FAILED {cov['error']}")
        else:
            print(f"  coverage {cov['requested_count']}: E_ads/N {cov['E_ads_per_molecule_eV']:.4f} eV, retained {cov['binding_retained']}")
    print(f"Wrote {result.structures_path} ({len(result.frames)} frames) and {result.manifest_path}")
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
