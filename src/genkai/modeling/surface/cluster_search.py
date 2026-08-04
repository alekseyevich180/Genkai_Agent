from __future__ import annotations

import argparse
import io
import random
from collections import Counter
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.filters import ExpCellFilter, StrainFilter
from ase.io import read, write
from ase.optimize import LBFGS
CALCULATOR = None


def normalize_symbols(symbols: list[str] | None) -> list[str]:
    if not symbols:
        return []

    normalized = []
    for symbol in symbols:
        cleaned = symbol.strip().strip(",")
        if not cleaned:
            continue
        normalized.append(cleaned[0].upper() + cleaned[1:].lower())
    return normalized


def format_symbol_counts(atoms: Atoms) -> str:
    counts = Counter(atoms.get_chemical_symbols())
    return ", ".join(f"{symbol}:{counts[symbol]}" for symbol in sorted(counts))


def build_calculator(uma_model: str, device: str, include_d3: bool, checkpoint: Path | None = None):
    import torch
    from fairchem.core import FAIRChemCalculator

    torch.set_float32_matmul_precision("medium")
    torch.backends.cuda.matmul.allow_tf32 = True
    model_ref = str(checkpoint) if checkpoint is not None else uma_model
    calc = FAIRChemCalculator.from_model_checkpoint(model_ref, task_name="oc22", device=device)

    if include_d3:
        from ase.calculators.dftd3 import DFTD3

        calc = DFTD3(dft=calc)

    return calc


def get_opt_energy(
    atoms: Atoms,
    calculator,
    fmax: float = 1e-3,
    opt_mode: str = "normal",
    max_steps: int | None = None,
) -> float:
    atoms.calc = calculator
    if opt_mode == "scale":
        optimizer = LBFGS(StrainFilter(atoms, mask=[1, 1, 1, 0, 0, 0]), logfile=None)
    elif opt_mode == "all":
        optimizer = LBFGS(ExpCellFilter(atoms), logfile=None)
    else:
        optimizer = LBFGS(atoms, logfile=None)
    optimizer.run(fmax=fmax, steps=max_steps)
    return atoms.get_total_energy()


def atoms_to_json(atoms: Atoms) -> str:
    buffer = io.StringIO()
    write(buffer, atoms, format="json")
    return buffer.getvalue()


def json_to_atoms(atoms_str: str) -> Atoms:
    return read(io.StringIO(atoms_str), format="json")


def get_geometric_center(atoms: Atoms) -> np.ndarray:
    return np.mean(atoms.positions, axis=0)


def load_slab(surface_path: Path, calculator, fmax: float, max_steps: int | None) -> tuple[Atoms, float]:
    slab = read(surface_path)
    energy = get_opt_energy(slab, calculator, fmax=fmax, opt_mode="normal", max_steps=max_steps)
    return slab, energy


def get_active_indices(
    atoms: Atoms, active_symbols: list[str], structure_path: Path | None = None
) -> list[int]:
    active_symbol_set = set(normalize_symbols(active_symbols))
    indices = [idx for idx, atom in enumerate(atoms) if atom.symbol in active_symbol_set]
    if not indices:
        available_symbols = sorted(set(atoms.get_chemical_symbols()))
        hint = ""
        if structure_path is not None and structure_path.suffix.lower() in {".vasp", ".poscar", ".contcar"}:
            hint = (
                " Hint: VASP/POSCAR files do not store element labels per atom. "
                "If you replaced atoms in the slab, you must also update the species/count header "
                "and regroup atoms by element so ASE reads the modified species correctly."
            )
        raise ValueError(
            "No active-site atoms found for symbols: "
            f"{', '.join(active_symbol_set)}. "
            f"Available symbols in slab: {', '.join(available_symbols)}. "
            f"Symbol counts: {format_symbol_counts(atoms)}."
            f"{hint}"
        )
    return indices


def load_cluster(
    cluster_path: Path,
    calculator,
    fmax: float,
    max_steps: int | None,
) -> tuple[Atoms, float]:
    cluster = read(cluster_path)
    energy = get_opt_energy(cluster, calculator, fmax=fmax, max_steps=max_steps)
    cluster.positions -= get_geometric_center(cluster)
    return cluster, energy


def estimate_bottom_plane_normal(cluster: Atoms, z_tolerance: float = 0.35) -> np.ndarray:
    positions = np.asarray(cluster.positions, dtype=float)
    if len(positions) < 3:
        return np.array([0.0, 0.0, 1.0])

    min_z = float(np.min(positions[:, 2]))
    bottom_mask = positions[:, 2] <= (min_z + z_tolerance)
    bottom_positions = positions[bottom_mask]
    if len(bottom_positions) < 3:
        sorted_indices = np.argsort(positions[:, 2])[: min(3, len(positions))]
        bottom_positions = positions[sorted_indices]
    if len(bottom_positions) < 3:
        return np.array([0.0, 0.0, 1.0])

    centered = bottom_positions - np.mean(bottom_positions, axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1]
    norm = np.linalg.norm(normal)
    if norm < 1e-8:
        return np.array([0.0, 0.0, 1.0])
    normal = normal / norm
    if normal[2] < 0.0:
        normal = -normal
    return normal


def get_min_slab_cluster_distance(combined: Atoms, n_slab_atoms: int) -> float:
    slab_positions = combined.positions[:n_slab_atoms]
    cluster_positions = combined.positions[n_slab_atoms:]
    deltas = slab_positions[:, None, :] - cluster_positions[None, :, :]
    return float(np.linalg.norm(deltas, axis=2).min())


def place_cluster_on_slab(
    cluster: Atoms,
    slab: Atoms,
    trial: optuna.Trial,
    placement_mode: str,
    active_indices: list[int],
    site_radius: float,
    z_min: float,
    z_max: float,
) -> Atoms:
    placed = cluster.copy()
    geometric_center = get_geometric_center(placed)
    bottom_normal = estimate_bottom_plane_normal(placed)
    spin_angle = trial.suggest_float("spin_angle", -180.0, 180.0)
    placed.rotate(spin_angle, v=bottom_normal, center=geometric_center)

    slab_top_z = float(np.max(slab.positions[:, 2]))
    if placement_mode == "active":
        site_choice = trial.suggest_int("site_index", 0, len(active_indices) - 1)
        dx = trial.suggest_float("dx", -site_radius, site_radius)
        dy = trial.suggest_float("dy", -site_radius, site_radius)
        anchor_position = slab.positions[active_indices[site_choice]]
        x_pos = float(anchor_position[0] + dx)
        y_pos = float(anchor_position[1] + dy)
        reference_z = max(slab_top_z, float(anchor_position[2]))
    else:
        x_frac = trial.suggest_float("x_frac", 0.0, 1.0)
        y_frac = trial.suggest_float("y_frac", 0.0, 1.0)
        xy_position = np.matmul([x_frac, y_frac, 0.0], slab.cell.array)[:2]
        x_pos = float(xy_position[0])
        y_pos = float(xy_position[1])
        reference_z = slab_top_z

    z_gap = trial.suggest_float("z_gap", z_min, z_max)
    geometric_center = get_geometric_center(placed)
    min_cluster_z = float(np.min(placed.positions[:, 2]))
    placed.translate(
        [
            x_pos - float(geometric_center[0]),
            y_pos - float(geometric_center[1]),
            reference_z + z_gap - min_cluster_z,
        ]
    )
    return placed


def objective(trial: optuna.Trial) -> float:
    slab = json_to_atoms(trial.study.user_attrs["slab"])
    e_slab = float(trial.study.user_attrs["E_slab"])
    cluster = json_to_atoms(trial.study.user_attrs["cluster"])
    e_cluster = float(trial.study.user_attrs["E_cluster"])
    placement_mode = str(trial.study.user_attrs["placement_mode"])
    active_indices = list(trial.study.user_attrs["active_indices"])
    site_radius = float(trial.study.user_attrs["site_radius"])
    z_min = float(trial.study.user_attrs["z_min"])
    z_max = float(trial.study.user_attrs["z_max"])
    detach_cutoff = float(trial.study.user_attrs["detach_cutoff"])
    penalty_energy = float(trial.study.user_attrs["penalty_energy"])
    max_steps = int(trial.study.user_attrs["max_steps"])
    fmax = float(trial.study.user_attrs["fmax"])

    placed_cluster = place_cluster_on_slab(
        cluster=cluster,
        slab=slab,
        trial=trial,
        placement_mode=placement_mode,
        active_indices=active_indices,
        site_radius=site_radius,
        z_min=z_min,
        z_max=z_max,
    )

    combined = slab + placed_cluster
    e_total = get_opt_energy(combined, CALCULATOR, fmax=fmax, max_steps=max_steps)
    adsorption_energy = e_total - e_slab - e_cluster
    structure_json = atoms_to_json(combined)
    trial.set_user_attr("structure", structure_json)

    min_distance = get_min_slab_cluster_distance(combined, len(slab))
    trial.set_user_attr("min_slab_cluster_distance", min_distance)
    if min_distance > detach_cutoff:
        trial.set_user_attr("detached", True)
        return penalty_energy + min_distance
    trial.set_user_attr("detached", False)

    return adsorption_energy


def get_ranked_valid_trials(study: optuna.Study) -> list[optuna.trial.FrozenTrial]:
    valid_trials = []
    for trial in study.trials:
        if trial.value is None:
            continue
        if trial.user_attrs.get("detached", False):
            continue
        if "structure" not in trial.user_attrs:
            continue
        valid_trials.append(trial)
    valid_trials.sort(key=lambda trial: float(trial.value))
    return valid_trials


def select_trials_for_dft(
    ranked_trials: list[optuna.trial.FrozenTrial],
    top_pool_size: int,
    top_pick_count: int,
    tail_bin_size: int,
    tail_pick_per_bin: int,
    final_selection_count: int,
    seed: int,
) -> list[dict]:
    if final_selection_count < 1:
        raise ValueError("--selection_count must be >= 1.")
    if top_pool_size < 0:
        raise ValueError("--top_pool_size must be >= 0.")
    if top_pick_count < 0:
        raise ValueError("--top_pick_count must be >= 0.")
    if tail_bin_size < 1:
        raise ValueError("--tail_bin_size must be >= 1.")
    if tail_pick_per_bin < 0:
        raise ValueError("--tail_pick_per_bin must be >= 0.")

    rng = random.Random(seed)
    top_pool = ranked_trials[:top_pool_size]
    if top_pick_count > len(top_pool):
        raise ValueError(
            f"Requested {top_pick_count} top-pool picks, but only {len(top_pool)} valid trials are available."
        )
    if final_selection_count < top_pick_count:
        raise ValueError(
            "--selection_count must be >= --top_pick_count so the top-pool picks can always be retained."
        )

    top_selected = rng.sample(top_pool, top_pick_count) if top_pick_count else []
    top_selected_by_number = {trial.number: trial for trial in top_selected}

    tail_trials = ranked_trials[top_pool_size:]
    tail_selected: list[tuple[optuna.trial.FrozenTrial, int, int]] = []
    if tail_pick_per_bin:
        for bin_start in range(0, len(tail_trials), tail_bin_size):
            bin_end = min(bin_start + tail_bin_size, len(tail_trials))
            tail_bin = tail_trials[bin_start:bin_end]
            if not tail_bin:
                continue
            picks = min(tail_pick_per_bin, len(tail_bin))
            for trial in rng.sample(tail_bin, picks):
                tail_selected.append((trial, top_pool_size + bin_start + 1, top_pool_size + bin_end))

    selected_tail_count = max(0, final_selection_count - len(top_selected))
    if selected_tail_count > len(tail_selected):
        raise ValueError(
            "Not enough tail candidates to satisfy the requested selection count. "
            "Adjust the selection parameters or increase --n_trials."
        )

    chosen_tail = rng.sample(tail_selected, selected_tail_count) if selected_tail_count else []

    selected_rows = []
    for trial in sorted(top_selected, key=lambda item: float(item.value)):
        selected_rows.append(
            {
                "trial": trial,
                "selection_group": "top_pool",
                "rank_range": f"1-{top_pool_size}",
            }
        )
    for trial, rank_start, rank_end in sorted(chosen_tail, key=lambda item: float(item[0].value)):
        if trial.number in top_selected_by_number:
            continue
        selected_rows.append(
            {
                "trial": trial,
                "selection_group": "tail_bin",
                "rank_range": f"{rank_start}-{rank_end}",
            }
        )

    selected_rows.sort(key=lambda item: float(item["trial"].value))
    return selected_rows


def export_selected_candidates(
    selected_trials: list[dict],
    mlip_output_dir: Path,
    vasp_dir: Path,
) -> None:
    for index, item in enumerate(selected_trials, start=1):
        trial = item["trial"]
        structure = json_to_atoms(trial.user_attrs["structure"])
        cif_path = mlip_output_dir / f"{index:02d}_trial_{trial.number:03d}.cif"
        write(cif_path, structure)

        write(vasp_dir / f"{index}.vasp", structure, format="vasp", direct=True, sort=True, vasp5=True)


def main():
    global CALCULATOR

    import optuna
    import pandas as pd

    parser = argparse.ArgumentParser(
        description="Search stable adsorption structures for a prebuilt cluster on a surface using Optuna."
    )
    parser.add_argument("--surface", type=Path, required=True, help="Surface structure file readable by ASE.")
    parser.add_argument("--cluster", type=Path, required=True, help="Prebuilt cluster structure readable by ASE.")
    parser.add_argument("--output_dir", type=Path, default=Path("output_nanocluster"))
    parser.add_argument("--n_trials", type=int, default=100)
    parser.add_argument("--fmax", type=float, default=1e-4)
    parser.add_argument("--uma_model", type=str, default="uma-s-1p2")
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--device", type=str, default="cuda", choices=["cuda", "cpu"])
    parser.add_argument(
        "--placement_mode",
        type=str,
        default="cell",
        choices=["cell", "active"],
        help="cell: scan the full surface cell; active: scan near selected surface atoms.",
    )
    parser.add_argument("--active_symbols", nargs="+", default=None)
    parser.add_argument("--site_radius", type=float, default=2.5)
    parser.add_argument("--z_min", type=float, default=1.5, help="Minimum initial cluster-surface gap in Angstrom.")
    parser.add_argument("--z_max", type=float, default=4.5, help="Maximum initial cluster-surface gap in Angstrom.")
    parser.add_argument("--detach_cutoff", type=float, default=6.0)
    parser.add_argument("--penalty_energy", type=float, default=1e6)
    parser.add_argument("--max_steps", type=int, default=200)
    parser.add_argument("--include_d3", action="store_true")
    parser.add_argument("--candidate_pool_size", type=int, default=100)
    parser.add_argument("--selection_count", type=int, default=10)
    parser.add_argument("--top_pool_size", type=int, default=10)
    parser.add_argument("--top_pick_count", type=int, default=6)
    parser.add_argument("--tail_bin_size", type=int, default=10)
    parser.add_argument("--tail_pick_per_bin", type=int, default=1)
    parser.add_argument("--selection_random_seed", type=int, default=42)
    args = parser.parse_args()

    args.active_symbols = normalize_symbols(args.active_symbols)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.placement_mode == "active" and not args.active_symbols:
        raise ValueError("--placement_mode active requires --active_symbols.")

    CALCULATOR = build_calculator(args.uma_model, args.device, args.include_d3, args.checkpoint)
    input_surface = read(args.surface)
    input_cluster = read(args.cluster)

    print(f"Loading and relaxing surface: {args.surface}")
    slab, e_slab = load_slab(args.surface, CALCULATOR, args.fmax, args.max_steps)
    print(f"Surface symbols: {format_symbol_counts(slab)}")
    print(f"Relaxed slab energy: {e_slab:.6f} eV")

    active_indices: list[int] = []
    if args.placement_mode == "active":
        active_indices = get_active_indices(slab, args.active_symbols, args.surface)
        print(f"Active symbols: {', '.join(args.active_symbols)}")
        print(f"Number of active atoms: {len(active_indices)}")
    else:
        print("Placement mode: full cell scan")

    print(f"\nLoading cluster: {args.cluster}\n")
    cluster, e_cluster = load_cluster(
        cluster_path=args.cluster,
        calculator=CALCULATOR,
        fmax=args.fmax,
        max_steps=args.max_steps,
    )
    print(f"Cluster atom count: {len(cluster)}")
    print(f"Cluster symbols: {format_symbol_counts(cluster)}")
    print(f"Relaxed cluster energy: {e_cluster:.6f} eV")

    structure_output_dir = args.output_dir / "mlip_output"
    structure_output_dir.mkdir(parents=True, exist_ok=True)
    vasp_dir = args.output_dir / "vasp"
    vasp_dir.mkdir(parents=True, exist_ok=True)
    write(structure_output_dir / "initial_surface.cif", input_surface)
    write(structure_output_dir / "initial_cluster.cif", input_cluster)

    study = optuna.create_study(direction="minimize")
    study.set_user_attr("slab", atoms_to_json(slab))
    study.set_user_attr("E_slab", e_slab)
    study.set_user_attr("cluster", atoms_to_json(cluster))
    study.set_user_attr("E_cluster", e_cluster)
    study.set_user_attr("placement_mode", args.placement_mode)
    study.set_user_attr("active_indices", active_indices)
    study.set_user_attr("site_radius", args.site_radius)
    study.set_user_attr("z_min", args.z_min)
    study.set_user_attr("z_max", args.z_max)
    study.set_user_attr("detach_cutoff", args.detach_cutoff)
    study.set_user_attr("penalty_energy", args.penalty_energy)
    study.set_user_attr("max_steps", args.max_steps)
    study.set_user_attr("fmax", args.fmax)
    study.optimize(objective, n_trials=args.n_trials)

    best_structure = json_to_atoms(study.best_trial.user_attrs["structure"])
    write(structure_output_dir / "mlip_best_structure.cif", best_structure)

    energy_rows = []
    for trial in study.trials:
        energy_rows.append(
            {
                "trial": trial.number,
                "energy": trial.value,
                "detached": trial.user_attrs.get("detached", False),
                "min_slab_cluster_distance": trial.user_attrs.get("min_slab_cluster_distance"),
            }
        )
    pd.DataFrame(energy_rows).to_csv(structure_output_dir / "mlip_energy_table.csv", index=False)

    ranked_trials = get_ranked_valid_trials(study)[: args.candidate_pool_size]
    selected_trials = select_trials_for_dft(
        ranked_trials=ranked_trials,
        top_pool_size=args.top_pool_size,
        top_pick_count=args.top_pick_count,
        tail_bin_size=args.tail_bin_size,
        tail_pick_per_bin=args.tail_pick_per_bin,
        final_selection_count=args.selection_count,
        seed=args.selection_random_seed,
    )
    export_selected_candidates(selected_trials, structure_output_dir, vasp_dir)

    print(f"Selected MLIP structures written to {structure_output_dir}")
    print(f"VASP inputs written to {vasp_dir}")


if __name__ == "__main__":
    main()
