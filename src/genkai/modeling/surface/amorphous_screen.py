"""Energy-based screening of amorphous surfaces and amorphous/crystal interfaces.

``surfaces`` (case 1, pure amorphous surface)::

    amorphous bulk --relax (positions + cell)--> eps_bulk per atom
    -> cut N windows of an integer number of periods (stoichiometric)
    -> (optional anneal) -> relax -> surface energy -> rank

    both faces free:  gamma = (E_slab - N eps_bulk) / (2 A)
    bottom fixed:     gamma_top = (E_relaxed - N eps_bulk) / A - gamma_unrelaxed,
                      gamma_unrelaxed = (E_unrelaxed - N eps_bulk) / (2 A)
    Non-stoichiometric cuts get no gamma (it would need chemical potentials).

``interface`` (case 2, full amorphous coverage on a crystal)::

    candidates: the best lattice matches (strained, seamless films) or random
                rotations of a cut film (any cell)
    per candidate: Optuna over the in-plane shift (dx, dy) and the gap with
                   short relaxations (same atoms -> total energies comparable)
    best shift -> (optional anneal) -> full relaxation
    rank candidates by W_adh = (E_substrate + E_film - E_interface) / A,
    because candidates differ in atom count.

Case 3 (amorphous island on a crystal) uses ``amorphous_overlayer`` (island
files) and ``cluster_search`` (Optuna placement with tilt and an MLIP).

``calculator="none"`` is a mock (no physical meaning) for local workflow
tests; ``uma`` is a real MLIP calculation and needs authorization. MLIP values
are screening estimates, not DFT evidence.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from ase import Atoms

from .amorphous_overlayer import (
    OverlayerBuildError,
    OverlayerSettings,
    build_film,
    build_film_cut,
    check_amorphous_bulk,
    composition_report,
    film_lattice_matches,
    pair_reference_distances,
)
from .amorphous_slab import AmorphousSlabSettings, build_amorphous_slab, standardize_cell
from .calculators import CALCULATORS, MOCK_NOTE, anneal, build_calculator, evidence_for, is_mock, relax
from .structure_io import export_frames, read_structure, sha256_of, write_frames, write_manifest
from .substrate import (
    Substrate,
    add_substrate_arguments,
    parse_export,
    substrate_from_args,
    supercell_in_plane,
    surface_area,
)

EV_PER_A2_TO_J_PER_M2 = 16.021766208


@dataclass
class ModelSettings:
    calculator: str = "none"
    uma_model: str = "uma-s-1p2"
    task_name: str = "omat"
    device: str = "cuda"
    include_d3: bool = False
    fmax: float = 0.05
    max_steps: int = 200
    anneal_steps: int = 0
    anneal_temperature: float = 600.0
    seed: int = 42

    def __post_init__(self) -> None:
        if self.calculator not in CALCULATORS:
            raise OverlayerBuildError(f"calculator must be one of {', '.join(CALCULATORS)}.")

    def build(self):
        return build_calculator(
            self.calculator,
            uma_model=self.uma_model,
            task_name=self.task_name,
            device=self.device,
            include_d3=self.include_d3,
        )


def _anneal_then_relax(atoms: Atoms, calc, model: ModelSettings, seed: int) -> tuple[float, bool]:
    annealed = False
    if model.anneal_steps > 0 and not is_mock(model.calculator):
        anneal(atoms, calc, temperature=model.anneal_temperature, steps=model.anneal_steps, seed=seed)
        annealed = True
    return relax(atoms, calc, fmax=model.fmax, steps=model.max_steps), annealed


def _header(model: ModelSettings) -> dict[str, Any]:
    return {
        "calculator": model.calculator,
        "evidence_level": evidence_for(model.calculator),
        "energies_meaningful": not is_mock(model.calculator),
        "scientific_calculation_started": not is_mock(model.calculator),
        "note": MOCK_NOTE if is_mock(model.calculator) else "MLIP screening values, not DFT evidence.",
        "model": asdict(model),
    }


def relax_amorphous_bulk(path: str | Path, fmt: str | None, model: ModelSettings, calc, relax_cell: bool) -> tuple[Atoms, Atoms, dict[str, Any]]:
    """Return (input bulk, relaxed bulk, record); the relaxed cell defines eps_bulk."""
    bulk, used = read_structure(path, fmt)
    bulk.pbc = True
    check_amorphous_bulk(bulk)
    relaxed = standardize_cell(bulk)
    energy = relax(relaxed, calc, fmax=model.fmax, steps=model.max_steps, cell=relax_cell)
    relaxed.calc = None
    record = {
        "path": Path(path).as_posix(),
        "format": used,
        "sha256": sha256_of(path),
        "formula": bulk.get_chemical_formula(mode="hill"),
        "n_atoms": len(bulk),
        "cell_relaxed": relax_cell,
        "volume_change": round(float(relaxed.get_volume() / bulk.get_volume() - 1.0), 5),
        "E_bulk_eV": energy,
        "eps_bulk_eV_per_atom": energy / len(relaxed),
    }
    return bulk, relaxed, record


# ---------------------------------------------------------------------------
# Case 1: pure amorphous surfaces
# ---------------------------------------------------------------------------


@dataclass
class SurfaceScreenSettings:
    periods: int | None = 2
    thickness: float | None = None
    samples: int = 4
    vacuum: float = 15.0
    min_lateral_size: float = 8.0
    both_sides_free: bool = True
    relax_cell: bool = True

    def __post_init__(self) -> None:
        if (self.periods is None) == (self.thickness is None):
            raise OverlayerBuildError("Give exactly one of periods or thickness.")
        if self.periods is not None and self.periods < 1:
            raise OverlayerBuildError("periods must be >= 1.")
        if self.samples < 1:
            raise OverlayerBuildError("samples must be >= 1.")


def screen_surfaces(
    amorphous_path: str | Path,
    settings: SurfaceScreenSettings,
    model: ModelSettings,
    output_dir: str | Path,
    *,
    amorphous_format: str | None = None,
    export: Sequence[str] = ("cif",),
) -> dict[str, Any]:
    outdir = Path(output_dir)
    calc = model.build()
    bulk, relaxed_bulk, bulk_record = relax_amorphous_bulk(amorphous_path, amorphous_format, model, calc, settings.relax_cell)
    eps = bulk_record["eps_bulk_eV_per_atom"]
    period = float(relaxed_bulk.cell.array[2, 2])
    thickness = settings.thickness if settings.thickness is not None else settings.periods * period - 1e-6
    slab_settings = AmorphousSlabSettings(
        thickness=thickness,
        vacuum=settings.vacuum,
        min_lateral_size=settings.min_lateral_size,
        fixed_fraction=0.0 if settings.both_sides_free else 0.5,
    )
    rng = np.random.default_rng(model.seed)
    rows: list[dict[str, Any]] = []
    frames: list[Atoms] = []
    for sample in range(settings.samples):
        slab, cut = build_amorphous_slab(relaxed_bulk, slab_settings, rng)
        if settings.both_sides_free:
            slab.set_constraint()
            slab.set_tags(np.ones(len(slab), dtype=int))
        area = surface_area(slab)
        stoich = composition_report(slab, relaxed_bulk)["stoichiometric"]
        slab.calc = calc
        e_unrelaxed = float(slab.get_potential_energy())
        e_relaxed, annealed = _anneal_then_relax(slab, calc, model, model.seed + sample)
        slab.calc = None
        gamma = None
        reason = None
        if stoich:
            if settings.both_sides_free:
                gamma = (e_relaxed - len(slab) * eps) / (2.0 * area)
            else:
                gamma_unrelaxed = (e_unrelaxed - len(slab) * eps) / (2.0 * area)
                gamma = (e_relaxed - len(slab) * eps) / area - gamma_unrelaxed
        else:
            reason = "non-stoichiometric cut: surface energy needs chemical potentials; use an integer number of periods"
        slab.info.update({"task": "amorphous_surface_screen", "sample": sample})
        frames.append(slab)
        rows.append(
            {
                "sample": sample,
                "z_window_start_A": cut["z_window_start_A"],
                "n_atoms": len(slab),
                "formula": slab.get_chemical_formula(mode="hill"),
                "stoichiometric": stoich,
                "annealed": annealed,
                "E_unrelaxed_eV": e_unrelaxed,
                "E_relaxed_eV": e_relaxed,
                "surface_energy_eV_A2": gamma,
                "surface_energy_J_m2": gamma * EV_PER_A2_TO_J_PER_M2 if gamma is not None else None,
                "gamma_reason": reason,
                "exposed_undercoordinated_cations": cut["exposed_undercoordinated_cations"],
            }
        )
    order = sorted(range(len(rows)), key=lambda k: (rows[k]["surface_energy_eV_A2"] is None, rows[k]["surface_energy_eV_A2"] or 0.0))
    ranked_frames = []
    for rank, k in enumerate(order, start=1):
        rows[k]["rank"] = rank
        frames[k].info["rank"] = rank
        ranked_frames.append(frames[k])
    structures_path = write_frames(outdir / "amorphous_surfaces_ranked.extxyz", ranked_frames)
    sample_paths = [write_frames(outdir / f"surface_rank_{r:02d}.extxyz", [f]).as_posix() for r, f in enumerate(ranked_frames, start=1)]
    exported = export_frames(ranked_frames, outdir / "exports", "surface_rank", export) if export else []
    manifest = {
        "schema_version": "1.0",
        "generator": "genkai.modeling.surface.amorphous_screen surfaces",
        **_header(model),
        "amorphous_bulk": bulk_record,
        "thickness_A": thickness,
        "period_A": period,
        "settings": asdict(settings),
        "surface_energy_definition": (
            "both faces free: (E - N eps_bulk) / 2A; bottom fixed: (E_relaxed - N eps_bulk)/A - (E_unrelaxed - N eps_bulk)/2A"
        ),
        "samples": [rows[k] for k in order],
        "files": {"structures": structures_path.as_posix(), "ranked": sample_paths, "exports": [p.as_posix() for p in exported]},
    }
    write_manifest(outdir / "amorphous_surfaces_manifest.json", manifest)
    return manifest


# ---------------------------------------------------------------------------
# Case 2: full amorphous coverage on a crystalline substrate
# ---------------------------------------------------------------------------


@dataclass
class InterfaceSearchSettings:
    thickness: float = 6.0
    film_fit: str = "auto"
    n_matches: int = 3
    n_rotations: int = 3
    n_trials: int = 20
    gap_min: float = 1.5
    gap_max: float = 3.0
    screen_steps: int = 20
    max_strain: float = 0.05
    max_area: float = 600.0
    relax_cell: bool = True

    def __post_init__(self) -> None:
        if self.film_fit not in ("auto", "strain", "cut"):
            raise OverlayerBuildError("film_fit must be auto, strain or cut.")
        if self.n_trials < 1 or self.n_matches < 1 or self.n_rotations < 1:
            raise OverlayerBuildError("n_trials, n_matches and n_rotations must be >= 1.")
        if not 0 < self.gap_min < self.gap_max:
            raise OverlayerBuildError("Require 0 < gap_min < gap_max.")


def _shifted(frame: Atoms, film_mask: np.ndarray, dx: float, dy: float, gap: float) -> Atoms:
    atoms = frame.copy()
    s1, s2 = atoms.cell.array[0], atoms.cell.array[1]
    positions = atoms.get_positions()
    positions[film_mask] += dx * s1 + dy * s2
    slab_top = positions[~film_mask, 2].max()
    positions[film_mask, 2] += slab_top + gap - positions[film_mask, 2].min()
    atoms.set_positions(positions)
    atoms.wrap(pbc=[True, True, False])
    return atoms


def search_interface(
    substrate: Substrate,
    amorphous_path: str | Path,
    settings: InterfaceSearchSettings,
    model: ModelSettings,
    output_dir: str | Path,
    *,
    amorphous_format: str | None = None,
    export: Sequence[str] = ("cif",),
) -> dict[str, Any]:
    import optuna

    outdir = Path(output_dir)
    calc = model.build()
    _, bulk, bulk_record = relax_amorphous_bulk(amorphous_path, amorphous_format, model, calc, settings.relax_cell)
    film_settings = OverlayerSettings(
        "full", thickness=settings.thickness, max_strain=settings.max_strain, max_area=settings.max_area
    )
    rng = np.random.default_rng(model.seed)

    candidates: list[tuple[str, Atoms, dict[str, Any]]] = []
    matches = [] if settings.film_fit == "cut" else film_lattice_matches(substrate.atoms, bulk, settings.max_strain, settings.max_area)
    if settings.film_fit == "strain" and not matches:
        raise OverlayerBuildError("No lattice match within the strain/area limits; use film_fit auto or cut.")
    for k, match in enumerate(matches[: settings.n_matches]):
        slab = supercell_in_plane(substrate.atoms, match.substrate_matrix)
        frame, report = build_film(slab, bulk, match, film_settings, rng)
        candidates.append((f"strain_{k}", frame, {**report, "lattice": match.summary()}))
    if not matches:
        reference = pair_reference_distances(bulk)
        for k in range(settings.n_rotations):
            frame, report = build_film_cut(substrate.atoms, bulk, reference, film_settings, rng)
            candidates.append((f"cut_{k}", frame, report))

    previous = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    substrate_cache: dict[tuple, float] = {}
    rows: list[dict[str, Any]] = []
    frames: list[Atoms] = []
    try:
        for index, (label, frame, build_report) in enumerate(candidates):
            film_mask = frame.arrays["ald_role"] == 1
            area = surface_area(frame)
            # References in the same in-plane cell: substrate alone and film alone.
            sub = frame[~film_mask]
            key = (len(sub), tuple(np.round(sub.cell.array[:2].ravel(), 4)))
            if key not in substrate_cache:
                substrate_cache[key] = relax(sub.copy(), calc, fmax=model.fmax, steps=model.max_steps)
            film = frame[film_mask]
            film.set_constraint()
            film_cell = film.cell.array.copy()
            film_cell[2] = [0.0, 0.0, float(np.ptp(film.positions[:, 2])) + 20.0]
            film.set_cell(film_cell)
            film.positions[:, 2] += 10.0 - film.positions[:, 2].min()
            e_film = relax(film, calc, fmax=model.fmax, steps=model.max_steps)

            def objective(trial: Any) -> float:
                dx = trial.suggest_float("dx", 0.0, 1.0)
                dy = trial.suggest_float("dy", 0.0, 1.0)
                gap = trial.suggest_float("gap", settings.gap_min, settings.gap_max)
                atoms = _shifted(frame, film_mask, dx, dy, gap)
                return relax(atoms, calc, fmax=model.fmax, steps=settings.screen_steps)

            study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=model.seed + index))
            study.optimize(objective, n_trials=settings.n_trials)
            best = study.best_params
            atoms = _shifted(frame, film_mask, best["dx"], best["dy"], best["gap"])
            e_interface, annealed = _anneal_then_relax(atoms, calc, model, model.seed + index)
            atoms.calc = None
            w_adh = (substrate_cache[key] + e_film - e_interface) / area
            atoms.info.update({"task": "amorphous_interface_search", "candidate": label})
            frames.append(atoms)
            rows.append(
                {
                    "candidate": label,
                    "film_fit": build_report.get("film_fit"),
                    "n_atoms": len(atoms),
                    "film_formula": film.get_chemical_formula(mode="hill"),
                    "area_A2": round(area, 4),
                    "best_shift": {k: round(v, 5) for k, v in best.items()},
                    "screen_trials": len(study.trials),
                    "annealed": annealed,
                    "E_interface_eV": e_interface,
                    "E_substrate_eV": substrate_cache[key],
                    "E_film_eV": e_film,
                    "W_adh_eV_A2": w_adh,
                    "W_adh_J_m2": w_adh * EV_PER_A2_TO_J_PER_M2,
                    "build": {k: v for k, v in build_report.items() if k != "composition"},
                }
            )
    finally:
        optuna.logging.set_verbosity(previous)

    order = sorted(range(len(rows)), key=lambda k: -rows[k]["W_adh_eV_A2"])
    ranked = []
    for rank, k in enumerate(order, start=1):
        rows[k]["rank"] = rank
        frames[k].info["rank"] = rank
        ranked.append(frames[k])
    structures_path = write_frames(outdir / "amorphous_interfaces_ranked.extxyz", ranked)
    exported = export_frames(ranked, outdir / "exports", "interface_rank", export) if export else []
    manifest = {
        "schema_version": "1.0",
        "generator": "genkai.modeling.surface.amorphous_screen interface",
        **_header(model),
        "substrate": substrate.record,
        "amorphous_bulk": bulk_record,
        "settings": asdict(settings),
        "adhesion_definition": "W_adh = (E_substrate + E_film - E_interface) / A; larger = more stable interface",
        "candidates": [rows[k] for k in order],
        "files": {"structures": structures_path.as_posix(), "exports": [p.as_posix() for p in exported]},
    }
    write_manifest(outdir / "amorphous_interfaces_manifest.json", manifest)
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _add_model_arguments(parser: argparse.ArgumentParser, prefix: str = "") -> None:
    parser.add_argument(f"--{prefix}calculator", dest="model_calculator", choices=CALCULATORS, default="none",
                        help="none = mock (workflow tests only); uma = real MLIP (needs authorization).")
    parser.add_argument("--include-d3", action="store_true")
    parser.add_argument("--fmax", type=float, default=0.05)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--anneal-steps", type=int, default=0, help="Langevin MD steps before the final relaxation (real models only).")
    parser.add_argument("--anneal-temperature", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--export", default="cif")
    parser.add_argument("--output-dir", type=Path, required=True)


def _model_from_args(args: argparse.Namespace) -> ModelSettings:
    return ModelSettings(
        calculator=args.model_calculator,
        uma_model=args.uma_model,
        task_name=args.task_name,
        device=args.device,
        include_d3=args.include_d3,
        fmax=args.fmax,
        max_steps=args.max_steps,
        anneal_steps=args.anneal_steps,
        anneal_temperature=args.anneal_temperature,
        seed=args.seed,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Energy-based screening of amorphous surfaces and amorphous/crystal interfaces.")
    commands = parser.add_subparsers(dest="command", required=True)

    surfaces = commands.add_parser("surfaces", help="Case 1: rank pure amorphous surfaces by surface energy.")
    surfaces.add_argument("--amorphous", type=Path, required=True)
    surfaces.add_argument("--amorphous-format", default=None)
    size = surfaces.add_mutually_exclusive_group()
    size.add_argument("--periods", type=int, default=None, help="Thickness in whole periods of the amorphous cell (stoichiometric).")
    size.add_argument("--thickness", type=float, default=None)
    surfaces.add_argument("--samples", type=int, default=4)
    surfaces.add_argument("--vacuum", type=float, default=15.0)
    surfaces.add_argument("--min-lateral-size", type=float, default=8.0)
    surfaces.add_argument("--fix-bottom", action="store_true", help="Fix the bottom half instead of relaxing both faces.")
    surfaces.add_argument("--no-cell-relax", action="store_true", help="Relax bulk positions only.")
    surfaces.add_argument("--uma-model", default="uma-s-1p2")
    surfaces.add_argument("--task-name", default="omat")
    surfaces.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    _add_model_arguments(surfaces)

    interface = commands.add_parser("interface", help="Case 2: full amorphous film on a crystal, searched by shift and gap.")
    add_substrate_arguments(interface)
    interface.add_argument("--amorphous", type=Path, required=True)
    interface.add_argument("--amorphous-format", default=None)
    interface.add_argument("--thickness", type=float, default=6.0)
    interface.add_argument("--film-fit", choices=["auto", "strain", "cut"], default="auto")
    interface.add_argument("--n-matches", type=int, default=3)
    interface.add_argument("--n-rotations", type=int, default=3)
    interface.add_argument("--n-trials", type=int, default=20)
    interface.add_argument("--gap-min", type=float, default=1.5)
    interface.add_argument("--gap-max", type=float, default=3.0)
    interface.add_argument("--screen-steps", type=int, default=20)
    interface.add_argument("--max-strain", type=float, default=0.05)
    interface.add_argument("--max-area", type=float, default=600.0)
    interface.add_argument("--no-cell-relax", action="store_true")
    _add_model_arguments(interface, prefix="search-")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        model = _model_from_args(args)
        if args.command == "surfaces":
            periods = args.periods if (args.periods is not None or args.thickness is not None) else 2
            settings = SurfaceScreenSettings(
                periods=periods if args.thickness is None else None,
                thickness=args.thickness,
                samples=args.samples,
                vacuum=args.vacuum,
                min_lateral_size=args.min_lateral_size,
                both_sides_free=not args.fix_bottom,
                relax_cell=not args.no_cell_relax,
            )
            manifest = screen_surfaces(args.amorphous, settings, model, args.output_dir,
                                       amorphous_format=args.amorphous_format, export=parse_export(args.export))
            print(f"NOTE {manifest['note']}")
            for row in manifest["samples"]:
                gamma = row["surface_energy_J_m2"]
                print(f"  rank {row['rank']}: sample {row['sample']} {row['formula']} "
                      f"gamma {'n/a (' + row['gamma_reason'] + ')' if gamma is None else f'{gamma:.4f} J/m^2'}")
        else:
            settings = InterfaceSearchSettings(
                thickness=args.thickness, film_fit=args.film_fit, n_matches=args.n_matches, n_rotations=args.n_rotations,
                n_trials=args.n_trials, gap_min=args.gap_min, gap_max=args.gap_max, screen_steps=args.screen_steps,
                max_strain=args.max_strain, max_area=args.max_area, relax_cell=not args.no_cell_relax,
            )
            substrate = substrate_from_args(args)
            manifest = search_interface(substrate, args.amorphous, settings, model, args.output_dir,
                                        amorphous_format=args.amorphous_format, export=parse_export(args.export))
            print(f"NOTE {manifest['note']}")
            for row in manifest["candidates"]:
                print(f"  rank {row['rank']}: {row['candidate']} ({row['film_fit']}) W_adh {row['W_adh_J_m2']:.4f} J/m^2, "
                      f"shift {row['best_shift']}")
    except (OverlayerBuildError, ValueError, FileNotFoundError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
