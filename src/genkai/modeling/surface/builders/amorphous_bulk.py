"""Amorphous bulk cells from a crystal by melt-quench molecular dynamics.

    crystal (CIF, POSCAR, ...)
    -> supercell with at least ``min_atoms`` atoms, as close to cubic as possible
    -> optional isotropic scaling to a target density (amorphous oxides are usually
       5-10 % less dense than the crystal)
    -> melt:   NVT Langevin MD at ``melt_temperature``
    -> quench: linear cooling to ``final_temperature`` at ``quench_rate`` (K/ps)
    -> anneal: NVT at ``final_temperature``
    -> final relaxation of positions and, by default, the cell
    -> amorphous_bulk_NNN.extxyz + amorphous_bulk_manifest.json

Every sample starts from the same supercell with its own random velocities. The
results are periodic 3D bulk cells without vacuum or fixed atoms; pass one as
``--amorphous`` to the amorphous_slab, ALD overlayer or amorphous_screen
methods, e.g. to cut amorphous surfaces from a crystal input.

This is a real MD calculation: it needs an energy model with forces (``uma`` or
``mace``; ``emt`` only for the few metals it covers and for tests). The mock
``calculator=none`` has zero forces and is refused; ``dry_run`` writes only the
prepared supercell and the planned schedule. The structure depends on the
potential, the temperature program and the quench rate (orders of magnitude
faster than experiment), so the manifest reports diagnostics - the melt
displacement, coordination numbers and RDF peaks against the crystal, and the
energy relative to the relaxed crystal - that have to be checked against
experiment or DFT before the cells are used.
"""

from __future__ import annotations

import argparse
import itertools
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from ase import Atoms
from ase.calculators.calculator import Calculator
from ase.data import atomic_numbers, covalent_radii

from ..mlip.calculators import CALCULATORS, add_mace_arguments, build_calculator, evidence_for, relax
from ..structure_io import CLASH_RATIO, export_frames, frame_metrics, read_structure, sha256_of, write_frames, write_manifest
from .amorphous_overlayer import OverlayerBuildError, check_amorphous_bulk, density_g_cm3
from .substrate import parse_export, parse_ints

GENERATOR = "genkai.modeling.surface.builders.amorphous_bulk"
# Below this RMS displacement of the slowest element during the melt the liquid may still
# remember the crystal; it is reported as a warning, not enforced.
MIN_MELT_RMS_A = 1.5
RDF_MAX_A = 6.0
RDF_BIN_A = 0.05
BOND_CUTOFF_FACTOR = 1.25  # neighbours within 1.25 x the sum of covalent radii count as coordinated
LOG_INTERVAL = 100  # MD steps between log lines
QUENCH_SEGMENTS = 200  # the target temperature is updated this many times during the quench


class AmorphousBulkError(ValueError):
    """Input or settings that cannot produce an amorphous cell."""


@dataclass
class MeltQuenchSettings:
    supercell: tuple[int, int, int] | None = None
    min_atoms: int = 150
    density: float | None = None  # g/cm^3; None keeps the crystal density
    melt_temperature: float = 3000.0
    melt_ps: float = 10.0
    quench_rate: float = 50.0  # K/ps
    final_temperature: float = 300.0
    anneal_ps: float = 10.0
    timestep_fs: float = 1.0
    friction_per_fs: float = 0.01
    samples: int = 1
    seed: int = 42
    fmax: float = 0.05
    max_steps: int = 500
    relax_cell: bool = True
    crystal_reference: bool = True
    trajectory_interval: int = 1000  # MD steps between saved snapshots; 0 saves none

    def __post_init__(self) -> None:
        if self.supercell is not None:
            self.supercell = tuple(int(n) for n in self.supercell)  # type: ignore[assignment]
            if len(self.supercell) != 3 or min(self.supercell) < 1:
                raise AmorphousBulkError("supercell needs three positive integers, e.g. 3,3,4.")
        if self.min_atoms < 1:
            raise AmorphousBulkError("min_atoms must be >= 1.")
        if self.density is not None and self.density <= 0:
            raise AmorphousBulkError("density must be positive (g/cm^3).")
        if self.final_temperature <= 0 or self.melt_temperature <= self.final_temperature:
            raise AmorphousBulkError("melt_temperature must be above final_temperature, and both positive.")
        if self.melt_ps <= 0 or self.anneal_ps < 0 or self.quench_rate <= 0:
            raise AmorphousBulkError("melt_ps and quench_rate must be positive; anneal_ps must be >= 0.")
        if not 0 < self.timestep_fs <= 5.0:
            raise AmorphousBulkError("timestep_fs must be in (0, 5] fs.")
        if self.friction_per_fs <= 0:
            raise AmorphousBulkError("friction_per_fs must be positive.")
        if self.samples < 1:
            raise AmorphousBulkError("samples must be >= 1.")
        if self.max_steps < 0 or self.fmax <= 0:
            raise AmorphousBulkError("max_steps must be >= 0 and fmax positive.")
        if self.trajectory_interval < 0:
            raise AmorphousBulkError("trajectory_interval must be >= 0.")

    def steps(self) -> dict[str, int]:
        quench_ps = (self.melt_temperature - self.final_temperature) / self.quench_rate
        per_ps = 1000.0 / self.timestep_fs
        steps = {
            "melt": max(1, round(self.melt_ps * per_ps)),
            "quench": max(1, math.ceil(quench_ps * per_ps)),
            "anneal": round(self.anneal_ps * per_ps),
        }
        steps["total"] = sum(steps.values())
        return steps


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------


def cell_heights(atoms: Atoms) -> np.ndarray:
    """Distances between opposite cell faces (the widths that limit periodic images)."""
    return 1.0 / np.linalg.norm(atoms.cell.reciprocal(), axis=1)


def choose_supercell(crystal: Atoms, min_atoms: int) -> tuple[int, int, int]:
    """Fewest atoms >= ``min_atoms`` among near-cubic repeats (face-to-face widths within 1.5x)."""
    heights = cell_heights(crystal)
    target = (min_atoms * crystal.get_volume() / len(crystal)) ** (1.0 / 3.0)
    slack = 2
    while True:
        ranges = [range(max(1, int(target // h) - 1), int(math.ceil(target / h)) + slack + 1) for h in heights]
        candidates = []
        for reps in itertools.product(*ranges):
            count = len(crystal) * reps[0] * reps[1] * reps[2]
            if count >= min_atoms:
                widths = heights * np.array(reps)
                candidates.append((count, float(widths.max() / widths.min()), tuple(int(n) for n in reps)))
        if candidates:
            near_cubic = [c for c in candidates if c[1] <= 1.5]
            pick = min(near_cubic, key=lambda c: (c[0], c[1])) if near_cubic else min(candidates, key=lambda c: (c[1], c[0]))
            return pick[2]  # type: ignore[return-value]
        slack += 2


def scale_to_density(atoms: Atoms, density: float) -> float:
    """Scale the cell isotropically to ``density`` (g/cm^3); return the linear factor."""
    current = density_g_cm3(atoms, float(atoms.get_volume()))
    factor = (current / density) ** (1.0 / 3.0)
    atoms.set_cell(atoms.cell.array * factor, scale_atoms=True)
    return float(factor)


def prepare_supercell(crystal: Atoms, settings: MeltQuenchSettings) -> tuple[Atoms, Atoms, dict[str, Any]]:
    """Return (crystal supercell, MD start cell scaled to the target density, report)."""
    if crystal.cell.rank < 3 or not crystal.pbc.all():
        raise AmorphousBulkError("The crystal needs a full 3D periodic cell (a bulk crystal, not a slab or molecule).")
    reps = settings.supercell or choose_supercell(crystal, settings.min_atoms)
    supercell = crystal.repeat(reps)
    supercell.set_constraint()
    supercell.pbc = True
    start = supercell.copy()
    crystal_density = density_g_cm3(supercell, float(supercell.get_volume()))
    factor = scale_to_density(start, settings.density) if settings.density is not None else 1.0
    widths = cell_heights(start)
    report = {
        "repeats": list(reps),
        "n_atoms": len(supercell),
        "formula": supercell.get_chemical_formula(mode="hill"),
        "crystal_density_g_cm3": round(crystal_density, 4),
        "start_density_g_cm3": round(density_g_cm3(start, float(start.get_volume())), 4),
        "linear_scale_factor": round(factor, 6),
        "face_to_face_widths_A": [round(float(w), 3) for w in widths],
        "start_min_contact_ratio": frame_metrics(start).get("min_contact_ratio"),
    }
    return supercell, start, report


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def structure_diagnostics(atoms: Atoms) -> tuple[dict[str, Any], dict[str, list[float]]]:
    """Coordination numbers and RDF first peaks per element pair; also returns g(r) per pair."""
    from ase.neighborlist import neighbor_list

    symbols = np.array(atoms.get_chemical_symbols())
    elements = sorted(set(symbols))
    i, j, d = neighbor_list("ijd", atoms, RDF_MAX_A)
    volume = float(atoms.get_volume())
    edges = np.arange(0.0, RDF_MAX_A + RDF_BIN_A / 2, RDF_BIN_A)
    centres = 0.5 * (edges[1:] + edges[:-1])
    shell = 4.0 * np.pi * centres**2 * RDF_BIN_A
    pairs: dict[str, Any] = {}
    curves: dict[str, list[float]] = {"r_A": [round(float(r), 4) for r in centres]}
    for a, b in itertools.combinations_with_replacement(elements, 2):
        n_a, n_b = int((symbols == a).sum()), int((symbols == b).sum())
        mask = (symbols[i] == a) & (symbols[j] == b)
        counts, _ = np.histogram(d[mask], bins=edges)
        g = counts * volume / (n_a * n_b * shell) if n_a and n_b else np.zeros_like(centres)
        key = f"{a}-{b}"
        curves[key] = [round(float(v), 4) for v in g]
        cutoff = BOND_CUTOFF_FACTOR * float(covalent_radii[atomic_numbers[a]] + covalent_radii[atomic_numbers[b]])
        entry: dict[str, Any] = {"bond_cutoff_A": round(cutoff, 3)}
        bonded = mask & (d < cutoff)
        # Coordination of each centre element by the other element of the pair.
        for centre, other in ((a, b), (b, a)) if a != b else ((a, b),):
            centre_mask = (symbols[i] == centre) & (symbols[j] == other) & (d < cutoff)
            per_atom = np.bincount(i[centre_mask], minlength=len(atoms))[symbols == centre]
            values, freq = np.unique(per_atom, return_counts=True)
            entry[f"cn_{centre}_by_{other}"] = {
                "mean": round(float(per_atom.mean()), 3) if per_atom.size else None,
                "distribution": {str(int(v)): round(float(f) / per_atom.size, 3) for v, f in zip(values, freq)},
            }
        if bonded.any():
            peak = int(np.argmax(np.where(centres < cutoff, g, -1.0)))
            entry["first_peak_A"] = round(float(centres[peak]), 3)
        pairs[key] = entry
    metrics = frame_metrics(atoms)
    summary = {
        "density_g_cm3": round(density_g_cm3(atoms, volume), 4),
        "min_contact_ratio": metrics.get("min_contact_ratio"),
        "pairs": pairs,
        "definition": (
            f"coordination counts neighbours closer than {BOND_CUTOFF_FACTOR} x the sum of covalent radii; "
            f"RDF up to {RDF_MAX_A} A in {RDF_BIN_A} A bins"
        ),
    }
    return summary, curves


def _max_force(atoms: Atoms) -> float:
    return float(np.linalg.norm(atoms.get_forces(), axis=1).max()) if len(atoms) else 0.0


# ---------------------------------------------------------------------------
# Melt-quench MD
# ---------------------------------------------------------------------------


@dataclass
class _Recorder:
    atoms: Atoms
    log_path: Path
    trajectory_path: Path | None
    trajectory_interval: int
    step: int = 0
    frames: list[Atoms] = field(default_factory=list)
    temperatures: dict[str, list[float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("w", encoding="utf-8")
        self._log.write("step,stage,target_K,temperature_K,epot_eV_per_atom\n")

    def advance(self, steps: int, stage: str, target: float) -> None:
        before = self.step
        self.step += steps
        temperature = float(self.atoms.get_temperature())
        self.temperatures.setdefault(stage, []).append(temperature)
        if self.step // LOG_INTERVAL > before // LOG_INTERVAL or steps >= LOG_INTERVAL:
            epot = float(self.atoms.get_potential_energy()) / len(self.atoms)
            if not math.isfinite(epot) or not np.isfinite(self.atoms.positions).all():
                raise AmorphousBulkError(f"MD became unstable at step {self.step} ({stage}); lower the timestep or temperature.")
            self._log.write(f"{self.step},{stage},{target:.1f},{temperature:.1f},{epot:.6f}\n")
        if self.trajectory_path is not None and self.trajectory_interval and (
            self.step // self.trajectory_interval > before // self.trajectory_interval
        ):
            snapshot = self.atoms.copy()
            snapshot.arrays.pop("momenta", None)
            snapshot.wrap()
            snapshot.info = {"stage": stage, "step": self.step, "target_K": round(target, 1)}
            self.frames.append(snapshot)

    def close(self) -> None:
        self._log.close()
        if self.trajectory_path is not None and self.frames:
            write_frames(self.trajectory_path, self.frames)


def melt_quench(
    atoms: Atoms,
    calculator: Calculator,
    settings: MeltQuenchSettings,
    seed: int,
    log_path: Path,
    trajectory_path: Path | None,
) -> dict[str, Any]:
    """Run melt -> quench -> anneal in place; return melt displacement and stage temperatures."""
    from ase import units
    from ase.md.langevin import Langevin
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution, Stationary

    steps = settings.steps()
    atoms.calc = calculator
    MaxwellBoltzmannDistribution(atoms, temperature_K=settings.melt_temperature, rng=np.random.default_rng(seed))
    Stationary(atoms)
    dyn = Langevin(
        atoms,
        settings.timestep_fs * units.fs,
        temperature_K=settings.melt_temperature,
        friction=settings.friction_per_fs / units.fs,
        rng=np.random.default_rng(seed + 1),
    )
    recorder = _Recorder(atoms, log_path, trajectory_path, settings.trajectory_interval)
    try:
        start = atoms.get_positions().copy()  # MD positions are not wrapped, so this is the true displacement
        for chunk in _chunks(steps["melt"], LOG_INTERVAL):
            dyn.run(chunk)
            recorder.advance(chunk, "melt", settings.melt_temperature)
        displacement = atoms.get_positions() - start
        symbols = np.array(atoms.get_chemical_symbols())
        melt_rms = {
            str(element): round(float(np.sqrt((displacement[symbols == element] ** 2).sum(axis=1).mean())), 3)
            for element in sorted(set(atoms.get_chemical_symbols()))
        }
        segments = _chunks(steps["quench"], math.ceil(steps["quench"] / QUENCH_SEGMENTS))
        span = settings.melt_temperature - settings.final_temperature
        done = 0
        for chunk in segments:
            done += chunk
            target = settings.melt_temperature - span * done / steps["quench"]
            dyn.set_temperature(temperature_K=target)
            dyn.run(chunk)
            recorder.advance(chunk, "quench", target)
        dyn.set_temperature(temperature_K=settings.final_temperature)
        for chunk in _chunks(steps["anneal"], LOG_INTERVAL):
            dyn.run(chunk)
            recorder.advance(chunk, "anneal", settings.final_temperature)
    finally:
        recorder.close()

    def tail_mean(values: list[float]) -> float | None:
        tail = values[len(values) // 2:]
        return round(float(np.mean(tail)), 1) if tail else None

    return {
        "melt_rms_displacement_A": melt_rms,
        "mean_temperature_K": {
            "melt_second_half": tail_mean(recorder.temperatures.get("melt", [])),
            "anneal_second_half": tail_mean(recorder.temperatures.get("anneal", [])),
        },
        "md_steps": steps,
        "trajectory_frames": len(recorder.frames),
    }


def _chunks(total: int, size: int) -> list[int]:
    size = max(1, size)
    return [size] * (total // size) + ([total % size] if total % size else [])


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


@dataclass
class AmorphousBulkRunResult:
    frames: list[Atoms]
    manifest: dict[str, Any]
    initial_path: Path
    structures_path: Path | None
    sample_paths: list[Path]
    manifest_path: Path
    exported: list[Path]


def _clean_copy(atoms: Atoms, info: dict[str, Any]) -> Atoms:
    frame = atoms.copy()
    frame.arrays.pop("momenta", None)
    frame.set_constraint()
    frame.wrap()
    frame.info = info
    return frame


def run_amorphous_bulk(
    crystal_path: str | Path,
    settings: MeltQuenchSettings,
    output_dir: str | Path,
    *,
    calculator: Calculator | None,
    calculator_name: str,
    model: dict[str, Any] | None = None,
    crystal_format: str | None = None,
    export: Sequence[str] = ("cif",),
    dry_run: bool = False,
) -> AmorphousBulkRunResult:
    """Melt-quench ``settings.samples`` amorphous cells from a crystal (or only prepare with ``dry_run``)."""
    if not dry_run and (calculator is None or calculator_name == "none"):
        raise AmorphousBulkError(
            "Melt-quench needs an energy model with forces (uma or mace; emt for its metals); "
            "calculator=none has zero forces. Use dry_run to prepare the supercell only."
        )
    outdir = Path(output_dir)
    crystal, used = read_structure(crystal_path, crystal_format)
    crystal_supercell, start, prepared = prepare_supercell(crystal, settings)
    initial_path = write_frames(outdir / "amorphous_bulk_initial.extxyz", [_clean_copy(start, {"role": "initial_supercell"})])
    crystal_diag, crystal_curves = structure_diagnostics(crystal_supercell)
    curves: dict[str, Any] = {"crystal_supercell": crystal_curves}
    warnings: list[str] = []
    frames: list[Atoms] = []
    samples: list[dict[str, Any]] = []
    sample_paths: list[Path] = []
    reference: dict[str, Any] | None = None

    if not dry_run:
        assert calculator is not None
        if settings.crystal_reference:
            relaxed = crystal_supercell.copy()
            energy = relax(relaxed, calculator, fmax=settings.fmax, steps=settings.max_steps, cell=settings.relax_cell)
            reference = {
                "energy_eV": round(energy, 6),
                "energy_per_atom_eV": round(energy / len(relaxed), 6),
                "density_g_cm3": round(density_g_cm3(relaxed, float(relaxed.get_volume())), 4),
                "max_force_eV_A": round(_max_force(relaxed), 4),
                "relaxed_cell": settings.relax_cell,
            }
        for sample in range(settings.samples):
            seed = settings.seed + 1000 * sample
            atoms = start.copy()
            clock = time.perf_counter()
            md = melt_quench(
                atoms, calculator, settings, seed,
                outdir / "md" / f"md_{sample:03d}.log",
                outdir / "md" / f"md_{sample:03d}.extxyz" if settings.trajectory_interval else None,
            )
            energy = relax(atoms, calculator, fmax=settings.fmax, steps=settings.max_steps, cell=settings.relax_cell)
            max_force = _max_force(atoms)
            frame = _clean_copy(atoms, {"task": "amorphous_bulk", "role": "amorphous_bulk", "sample": sample, "frame_id": sample})
            diagnostics, sample_curves = structure_diagnostics(frame)
            curves[f"sample_{sample:03d}"] = sample_curves
            record: dict[str, Any] = {
                "sample": sample,
                "seed": seed,
                **md,
                "final_energy_eV": round(energy, 6),
                "energy_per_atom_eV": round(energy / len(frame), 6),
                "delta_e_vs_crystal_eV_per_atom": (
                    round(energy / len(frame) - reference["energy_per_atom_eV"], 6) if reference else None
                ),
                "relax": {"max_force_eV_A": round(max_force, 4), "converged": max_force <= settings.fmax * 1.0001,
                          "cell_relaxed": settings.relax_cell},
                "cell_lengths_A": [round(float(v), 4) for v in frame.cell.lengths()],
                "cell_angles_deg": [round(float(v), 3) for v in frame.cell.angles()],
                "wall_seconds": round(time.perf_counter() - clock, 1),
                "diagnostics": diagnostics,
            }
            slowest = min(md["melt_rms_displacement_A"].items(), key=lambda item: item[1])
            if slowest[1] < MIN_MELT_RMS_A:
                warnings.append(
                    f"sample {sample}: {slowest[0]} moved only {slowest[1]} A (RMS) during the melt (< {MIN_MELT_RMS_A} A); "
                    "the liquid may still remember the crystal - raise melt_temperature or melt_ps."
                )
            if record["delta_e_vs_crystal_eV_per_atom"] is not None and record["delta_e_vs_crystal_eV_per_atom"] <= 0:
                warnings.append(
                    f"sample {sample}: energy is not above the relaxed crystal "
                    f"({record['delta_e_vs_crystal_eV_per_atom']} eV/atom); check the model and the reference phase."
                )
            if not record["relax"]["converged"]:
                warnings.append(f"sample {sample}: final relaxation not converged (max force {round(max_force, 4)} eV/A).")
            ratio = diagnostics["min_contact_ratio"]
            if ratio is not None and ratio < CLASH_RATIO:
                warnings.append(f"sample {sample}: atoms too close (min contact ratio {ratio} < {CLASH_RATIO}).")
            try:
                check_amorphous_bulk(frame)
            except OverlayerBuildError as exc:
                warnings.append(f"sample {sample}: not a dense bulk ({exc})")
            frames.append(frame)
            samples.append(record)
            sample_paths.append(write_frames(outdir / f"amorphous_bulk_{sample:03d}.extxyz", [frame]))

    structures_path = write_frames(outdir / "amorphous_bulk_structures.extxyz", frames) if frames else None
    exported = export_frames(frames, outdir / "exports", "amorphous_bulk", export) if frames and export else []
    rdf_path = write_manifest(outdir / "amorphous_bulk_rdf.json", curves)
    steps = settings.steps()
    manifest = {
        "schema_version": "1.0",
        "generator": GENERATOR,
        "mode": "prepare-only" if dry_run else "melt-quench",
        "calculator": "none" if dry_run else calculator_name,
        "model": model or {},
        "evidence_level": "heuristic" if dry_run else evidence_for(calculator_name),
        "scientific_calculation_started": not dry_run,
        "energies_available": not dry_run,
        "note": (
            "Prepared supercell and planned schedule only; no MD was run." if dry_run else
            "Melt-quench MD with the stated model; the structure depends on the potential, the temperature program and "
            "the quench rate. Check the coordination numbers and RDF against experiment or DFT before use."
        ),
        "crystal": {
            "path": Path(crystal_path).as_posix(),
            "format": used,
            "sha256": sha256_of(crystal_path),
            "formula": crystal.get_chemical_formula(mode="hill"),
            "n_atoms": len(crystal),
            "density_g_cm3": round(density_g_cm3(crystal, float(crystal.get_volume())), 4),
        },
        "supercell": prepared,
        "settings": asdict(settings),
        "schedule": {
            "md_steps": steps,
            "total_md_ps": round(steps["total"] * settings.timestep_fs / 1000.0, 3),
            "quench_ps": round((settings.melt_temperature - settings.final_temperature) / settings.quench_rate, 3),
            "ensemble": "NVT Langevin (fixed cell); the final relaxation also relaxes the cell" if settings.relax_cell
            else "NVT Langevin (fixed cell); final relaxation of positions only",
        },
        "crystal_reference": reference,
        "crystal_diagnostics": crystal_diag,
        "samples": samples,
        "files": {
            "initial_supercell": initial_path.as_posix(),
            "structures": structures_path.as_posix() if structures_path else None,
            "samples": [p.as_posix() for p in sample_paths],
            "rdf": rdf_path.as_posix(),
            "md_logs": sorted(p.as_posix() for p in (outdir / "md").glob("md_*.log")) if not dry_run else [],
            "exports": [p.as_posix() for p in exported],
        },
        "validation": {"warnings": warnings},
        "conventions": {
            "cell": "periodic 3D bulk, no vacuum, no fixed atoms",
            "use_as_amorphous": "pass amorphous_bulk_NNN.extxyz as --amorphous to amorphous_slab, ald or amorphous_screen",
        },
    }
    manifest_path = write_manifest(outdir / "amorphous_bulk_manifest.json", manifest)
    return AmorphousBulkRunResult(frames, manifest, initial_path, structures_path, sample_paths, manifest_path, exported)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Amorphous bulk cells from a crystal by melt-quench MD (needs uma or mace; emt only for its metals). "
            "Use the output as --amorphous for amorphous_slab, ald or amorphous_screen."
        )
    )
    parser.add_argument("--crystal", type=Path, required=True, help="Bulk crystal (CIF by default; any ASE format).")
    parser.add_argument("--crystal-format", default=None)
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--supercell", default=None, help="Explicit repeats of the crystal cell, e.g. 3,3,4.")
    size.add_argument("--min-atoms", type=int, default=150, help="Smallest near-cubic supercell with at least this many atoms.")
    parser.add_argument("--density", type=float, default=None, help="Target density in g/cm^3 (default: crystal density).")
    parser.add_argument("--melt-temperature", type=float, default=3000.0, help="Melt temperature in K (about 1.5-2x the melting point).")
    parser.add_argument("--melt-ps", type=float, default=10.0, help="Melt duration in ps.")
    parser.add_argument("--quench-rate", type=float, default=50.0, help="Linear cooling rate in K/ps.")
    parser.add_argument("--final-temperature", type=float, default=300.0, help="Quench end and anneal temperature in K.")
    parser.add_argument("--anneal-ps", type=float, default=10.0, help="Anneal duration at the final temperature in ps.")
    parser.add_argument("--timestep", type=float, default=1.0, help="MD timestep in fs (use 0.5 with H).")
    parser.add_argument("--friction", type=float, default=0.01, help="Langevin friction in 1/fs.")
    parser.add_argument("--samples", type=int, default=1, help="Independent melt-quench runs with different velocities.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fmax", type=float, default=0.05, help="Force threshold of the final relaxation (eV/A).")
    parser.add_argument("--max-steps", type=int, default=500, help="Step limit of the final relaxation.")
    parser.add_argument("--no-cell-relax", action="store_true", help="Relax positions only at the end (keep the MD cell).")
    parser.add_argument("--no-crystal-reference", action="store_true", help="Skip relaxing the crystal supercell for the energy reference.")
    parser.add_argument("--trajectory-interval", type=int, default=1000, help="MD steps between saved snapshots (0: none).")
    parser.add_argument("--dry-run", action="store_true", help="Write the prepared supercell and the schedule only; no MD.")
    parser.add_argument("--calculator", choices=CALCULATORS, default="none",
                        help="uma or mace (real MLIP, needs authorization); emt for its metals; none is refused unless --dry-run.")
    parser.add_argument("--uma-model", default="uma-s-1p2")
    parser.add_argument("--task-name", default="omat")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--include-d3", action="store_true")
    add_mace_arguments(parser)
    parser.add_argument("--export", default="cif", help="Comma-separated export formats (cif, vasp) or 'none'.")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        settings = MeltQuenchSettings(
            supercell=parse_ints(args.supercell),  # type: ignore[arg-type]
            min_atoms=args.min_atoms,
            density=args.density,
            melt_temperature=args.melt_temperature,
            melt_ps=args.melt_ps,
            quench_rate=args.quench_rate,
            final_temperature=args.final_temperature,
            anneal_ps=args.anneal_ps,
            timestep_fs=args.timestep,
            friction_per_fs=args.friction,
            samples=args.samples,
            seed=args.seed,
            fmax=args.fmax,
            max_steps=args.max_steps,
            relax_cell=not args.no_cell_relax,
            crystal_reference=not args.no_crystal_reference,
            trajectory_interval=args.trajectory_interval,
        )
        model = {"device": args.device}
        if args.calculator == "uma":
            model.update(uma_model=args.uma_model, task_name=args.task_name, include_d3=args.include_d3)
        elif args.calculator == "mace":
            model.update(mace_model=args.mace_model, mace_dtype=args.mace_dtype)
        calculator = None
        if not args.dry_run:
            if args.calculator == "none":
                raise AmorphousBulkError(
                    "melt-quench needs an energy model with forces: pass --calculator uma or mace "
                    "(emt only for its metals), or --dry-run to prepare the supercell only."
                )
            calculator = build_calculator(
                args.calculator, uma_model=args.uma_model, task_name=args.task_name, device=args.device,
                include_d3=args.include_d3, mace_model=args.mace_model, mace_dtype=args.mace_dtype,
            )
        result = run_amorphous_bulk(
            args.crystal, settings, args.output_dir, calculator=calculator, calculator_name=args.calculator,
            model=model, crystal_format=args.crystal_format, export=parse_export(args.export), dry_run=args.dry_run,
        )
    except (AmorphousBulkError, OverlayerBuildError, ValueError, FileNotFoundError, ImportError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    manifest = result.manifest
    cell = manifest["supercell"]
    schedule = manifest["schedule"]
    print(
        f"Crystal {manifest['crystal']['formula']} -> supercell {'x'.join(map(str, cell['repeats']))} "
        f"({cell['n_atoms']} atoms), density {cell['crystal_density_g_cm3']} -> {cell['start_density_g_cm3']} g/cm^3"
    )
    print(
        f"Schedule: melt {settings.melt_temperature:g} K / {settings.melt_ps:g} ps, quench {settings.quench_rate:g} K/ps "
        f"({schedule['quench_ps']} ps), anneal {settings.final_temperature:g} K / {settings.anneal_ps:g} ps; "
        f"{schedule['md_steps']['total']} MD steps ({schedule['total_md_ps']} ps)"
    )
    if args.dry_run:
        print(f"DRY RUN: wrote {result.initial_path}; no MD was run. Manifest {result.manifest_path}")
        return 0
    for sample in manifest["samples"]:
        delta = sample["delta_e_vs_crystal_eV_per_atom"]
        pairs = sample["diagnostics"]["pairs"]
        cn = "; ".join(
            f"{name} {value['mean']}" for pair in pairs.values() for name, value in pair.items()
            if name.startswith("cn_") and value["mean"]
        )
        print(
            f"  sample {sample['sample']}: density {sample['diagnostics']['density_g_cm3']} g/cm^3, "
            f"E - E_crystal {delta if delta is not None else 'n/a'} eV/atom, "
            f"melt RMS {sample['melt_rms_displacement_A']} A, {sample['wall_seconds']} s"
        )
        print(f"    coordination: {cn}")
    for warning in manifest["validation"]["warnings"]:
        print(f"WARNING {warning}")
    print(f"Wrote {result.structures_path} and {len(result.sample_paths)} per-sample file(s); manifest {result.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
