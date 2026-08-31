import argparse
from dataclasses import dataclass
import io
import random
from pathlib import Path
from typing import Literal

import numpy as np
import optuna
import pandas as pd
from ase import Atoms
from ase.calculators.calculator import Calculator, all_changes
from ase.io import read, write
from ase.optimize import LBFGS
from scipy.optimize import Bounds, LinearConstraint, milp


CONFIG = {
    # Input/output
    "surface": "CeO2 (1 1 1).cif",
    "molecule": "4-acid.vasp",
    "output_dir": "output",
    "structure_prefix": "ads",
    # Site detection
    "site_symbols": "Ce",
    "site_z_tolerance": 1.2,
    "max_sites": None,
    "site_group_size": 1,
    # Single-molecule Optuna search
    "n_trials_single": 60,
    "site_radius": 1.0,
    "z_gap_min": 1.4,
    "z_gap_max": 3.5,
    # Coverage generation
    "coverage_counts": None,  # None means 1..max_adsorbates
    "patterns": "uniform,clustered,stripe,island,random",
    "random_repeats": 5,
    "seed": 42,
    # Energy descriptor
    "calculator": "uma",  # "uma" for real runs, "none" for workflow tests
    "uma_model": "uma-s-1p2",
    "device": "cuda",
    "task_name": "omat",
    "include_d3": False,
    # Relaxation
    "fmax": 0.05,
    "max_steps": 200,
    # Fast local test without UMA
    "smoke_test": {
        "output_dir": "output_adsorbate_landscape_smoke",
        "n_trials_single": 8,
        "coverage_counts": "1,2,3",
        "random_repeats": 2,
        "calculator": "none",
        "max_steps": 0,
    },
}


@dataclass(frozen=True)
class AdsorbateLandscapeConfig:
    surface: Path
    molecule: Path
    output_dir: Path
    site_symbols: str
    coverage_counts: str | None
    patterns: str = "uniform,clustered,random"
    structure_prefix: str = "ads"
    site_z_tolerance: float = 1.2
    max_sites: int | None = None
    site_group_size: int = 1
    n_trials_single: int = 60
    site_radius: float = 1.0
    z_gap_min: float = 1.4
    z_gap_max: float = 3.5
    random_repeats: int = 5
    seed: int = 42
    calculator: Literal["none", "uma"] = "none"
    uma_model: str = "uma-s-1p2"
    device: Literal["cuda", "cpu"] = "cuda"
    task_name: str = "omat"
    include_d3: bool = False
    fmax: float = 0.05
    max_steps: int = 0


@dataclass(frozen=True)
class AdsorbateLandscapeResult:
    structure_paths: tuple[Path, ...]
    csv_path: Path
    plot_path: Path
    best_candidate_path: Path


class AdsorptionTestCalculator(Calculator):
    implemented_properties = ["energy", "forces"]

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        symbols = self.atoms.get_chemical_symbols()
        energy = -4.0 * symbols.count("Ce") - 2.0 * symbols.count("O") - 0.5 * symbols.count("C")
        energy -= 0.1 * symbols.count("H")
        positions = self.atoms.positions
        ce_indices = [idx for idx, symbol in enumerate(symbols) if symbol == "Ce"]
        ads_like_indices = [idx for idx, symbol in enumerate(symbols) if symbol in {"C", "O", "H"}]
        attraction_weight = {"C": 0.08, "O": 0.06, "H": 0.015}
        for ads_idx in ads_like_indices:
            weight = attraction_weight[symbols[ads_idx]]
            for ce_idx in ce_indices:
                distance = np.linalg.norm(positions[ads_idx] - positions[ce_idx])
                energy -= weight * np.exp(-((distance - 3.0) / 1.2) ** 2)
        for i, atom_i in enumerate(ads_like_indices):
            for atom_j in ads_like_indices[i + 1 :]:
                distance = np.linalg.norm(positions[atom_i] - positions[atom_j])
                if distance > 1e-8:
                    energy += 0.01 * np.exp(-(distance / 4.0) ** 2)
        self.results["energy"] = float(energy)
        self.results["forces"] = np.zeros((len(symbols), 3), dtype=float)


def build_calculator(calculator_name: str, uma_model: str, device: str, task_name: str, include_d3: bool):
    if calculator_name == "none":
        return AdsorptionTestCalculator()

    import torch
    from fairchem.core import FAIRChemCalculator, pretrained_mlip

    torch.set_float32_matmul_precision("medium")
    torch.backends.cuda.matmul.allow_tf32 = True

    predictor = pretrained_mlip.get_predict_unit(uma_model, device=device)
    calc = FAIRChemCalculator(predictor, task_name=task_name)

    if include_d3:
        from ase.calculators.dftd3 import DFTD3

        calc = DFTD3(dft=calc)

    return calc


def optimize_energy(atoms: Atoms, calculator, fmax: float, max_steps: int | None) -> float:
    atoms.calc = calculator
    opt = LBFGS(atoms, logfile=None)
    opt.run(fmax=fmax, steps=max_steps)
    return float(atoms.get_potential_energy())


def atoms_to_json(atoms: Atoms) -> str:
    buffer = io.StringIO()
    write(buffer, atoms, format="json")
    return buffer.getvalue()


def json_to_atoms(text: str) -> Atoms:
    return read(io.StringIO(text), format="json")


def parse_symbols(text: str) -> list[str]:
    return [item.strip().capitalize() for item in text.split(",") if item.strip()]


def parse_int_list(text: str | None) -> list[int] | None:
    if text is None:
        return None
    values = []
    for item in text.split(","):
        item = item.strip()
        if item:
            values.append(int(item))
    return sorted(set(values))


def parse_patterns(text: str) -> list[str]:
    allowed = {"uniform", "clustered", "stripe", "island", "random"}
    patterns = [item.strip().lower() for item in text.split(",") if item.strip()]
    invalid = sorted(set(patterns) - allowed)
    if invalid:
        raise ValueError(f"Unknown patterns: {', '.join(invalid)}")
    return patterns


def get_surface_sites(slab: Atoms, site_symbols: list[str], z_tolerance: float, max_sites: int | None) -> list[int]:
    candidate_indices = [atom.index for atom in slab if atom.symbol in site_symbols]
    if not candidate_indices:
        available = sorted(set(slab.get_chemical_symbols()))
        raise ValueError(f"No site atoms found for {site_symbols}. Available symbols: {available}")

    z_values = slab.positions[candidate_indices, 2]
    top_z = float(np.max(z_values))
    sites = [idx for idx in candidate_indices if slab.positions[idx, 2] >= top_z - z_tolerance]
    sites = sorted(sites, key=lambda idx: (slab.positions[idx, 1], slab.positions[idx, 0]))
    if max_sites is not None:
        sites = sites[:max_sites]
    return sites


def build_site_groups(slab: Atoms, site_indices: list[int], group_size: int) -> list[tuple[int, ...]]:
    if group_size < 1:
        raise ValueError("--site-group-size must be >= 1")
    if group_size > len(site_indices):
        raise ValueError(
            f"--site-group-size {group_size} is larger than the number of detected sites {len(site_indices)}."
        )
    if group_size == 1:
        return [(idx,) for idx in site_indices]

    site_positions = slab.positions[site_indices]
    groups = set()
    for local_idx, site_index in enumerate(site_indices):
        distances = np.linalg.norm(site_positions - site_positions[local_idx], axis=1)
        nearest = np.argsort(distances)[:group_size]
        groups.add(tuple(sorted(site_indices[int(i)] for i in nearest)))
    return sorted(groups)


def group_positions(slab: Atoms, site_groups: list[tuple[int, ...]]) -> np.ndarray:
    return np.array([slab.positions[list(group)].mean(axis=0) for group in site_groups])


def center_molecule(molecule: Atoms) -> Atoms:
    mol = molecule.copy()
    mol.positions -= mol.positions.mean(axis=0)
    return mol


def place_molecule(
    molecule: Atoms,
    site_position: np.ndarray,
    spin_angle: float,
    z_gap: float,
    dx: float = 0.0,
    dy: float = 0.0,
) -> Atoms:
    placed = center_molecule(molecule)
    placed.rotate(spin_angle, v=[0.0, 0.0, 1.0], center=[0.0, 0.0, 0.0])
    min_z = float(np.min(placed.positions[:, 2]))
    placed.translate(
        [
            float(site_position[0] + dx),
            float(site_position[1] + dy),
            float(site_position[2] + z_gap - min_z),
        ]
    )
    return placed


def min_adsorbate_surface_distance(combined: Atoms, n_slab: int) -> float:
    slab_pos = combined.positions[:n_slab]
    ads_pos = combined.positions[n_slab:]
    deltas = slab_pos[:, None, :] - ads_pos[None, :, :]
    return float(np.linalg.norm(deltas, axis=2).min())


def run_single_adsorbate_search(
    slab: Atoms,
    molecule: Atoms,
    site_groups: list[tuple[int, ...]],
    e_slab: float,
    e_mol: float,
    calculator,
    args,
) -> tuple[Atoms, dict]:
    positions = group_positions(slab, site_groups)

    def objective(trial: optuna.Trial) -> float:
        group_id = trial.suggest_int("group_id", 0, len(site_groups) - 1)
        spin_angle = trial.suggest_float("spin_angle", -180.0, 180.0)
        dx = trial.suggest_float("dx", -args.site_radius, args.site_radius)
        dy = trial.suggest_float("dy", -args.site_radius, args.site_radius)
        z_gap = trial.suggest_float("z_gap", args.z_gap_min, args.z_gap_max)
        mol = place_molecule(molecule, positions[group_id], spin_angle, z_gap, dx, dy)
        combined = slab + mol
        e_total = optimize_energy(combined, calculator, args.fmax, args.max_steps)
        e_ads = e_total - e_slab - e_mol
        trial.set_user_attr("structure", atoms_to_json(combined))
        trial.set_user_attr("group_id", group_id)
        trial.set_user_attr("site_group", " ".join(str(idx) for idx in site_groups[group_id]))
        trial.set_user_attr("spin_angle", spin_angle)
        trial.set_user_attr("dx", dx)
        trial.set_user_attr("dy", dy)
        trial.set_user_attr("z_gap", z_gap)
        trial.set_user_attr("min_distance", min_adsorbate_surface_distance(combined, len(slab)))
        return e_ads

    sampler = optuna.samplers.TPESampler(seed=args.seed)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.optimize(objective, n_trials=args.n_trials_single)
    best = study.best_trial
    return json_to_atoms(best.user_attrs["structure"]), {
        "E_ads_single_eV": float(best.value),
        "group_id": int(best.user_attrs["group_id"]),
        "site_group": str(best.user_attrs["site_group"]),
        "spin_angle": float(best.user_attrs["spin_angle"]),
        "dx": float(best.user_attrs["dx"]),
        "dy": float(best.user_attrs["dy"]),
        "z_gap": float(best.user_attrs["z_gap"]),
        "min_distance": float(best.user_attrs["min_distance"]),
        "n_trials": len(study.trials),
    }


def farthest_site_selection(site_xy: np.ndarray, count: int) -> list[int]:
    selected = [int(np.argmin(np.linalg.norm(site_xy - site_xy.mean(axis=0), axis=1)))]
    while len(selected) < count:
        distances = np.full(len(site_xy), np.inf)
        for idx in selected:
            distances = np.minimum(distances, np.linalg.norm(site_xy - site_xy[idx], axis=1))
        distances[selected] = -np.inf
        selected.append(int(np.argmax(distances)))
    return selected


def clustered_site_selection(site_xy: np.ndarray, count: int) -> list[int]:
    center = site_xy.mean(axis=0)
    start = int(np.argmin(np.linalg.norm(site_xy - center, axis=1)))
    distances = np.linalg.norm(site_xy - site_xy[start], axis=1)
    return [int(i) for i in np.argsort(distances)[:count]]


def stripe_site_selection(site_xy: np.ndarray, count: int) -> list[int]:
    y = site_xy[:, 1]
    row_center = float(np.median(y))
    row_order = np.argsort(np.abs(y - row_center))
    row_candidates = sorted(row_order[: max(count, min(len(row_order), count * 2))], key=lambda idx: site_xy[idx, 0])
    return [int(i) for i in row_candidates[:count]]


def island_site_selection(site_xy: np.ndarray, count: int) -> list[int]:
    center = site_xy.mean(axis=0)
    distances = np.linalg.norm(site_xy - center, axis=1)
    near = np.argsort(distances)[: max(count, min(len(site_xy), count * 2))]
    angles = np.arctan2(site_xy[near, 1] - center[1], site_xy[near, 0] - center[0])
    ordered = near[np.argsort(angles)]
    return [int(i) for i in ordered[:count]]


def choose_pattern_sites(
    pattern: str,
    site_positions: np.ndarray,
    count: int,
    rng: random.Random,
) -> list[int]:
    site_xy = site_positions[:, :2]
    if count > len(site_positions):
        raise ValueError(f"Requested {count} adsorbates but only {len(site_positions)} sites are available.")
    if pattern == "uniform":
        return farthest_site_selection(site_xy, count)
    if pattern == "clustered":
        return clustered_site_selection(site_xy, count)
    if pattern == "stripe":
        return stripe_site_selection(site_xy, count)
    if pattern == "island":
        return island_site_selection(site_xy, count)
    if pattern == "random":
        return sorted(rng.sample(range(len(site_positions)), count))
    raise ValueError(f"Unknown pattern: {pattern}")


def ordered_pattern_candidates(pattern: str, positions: np.ndarray, rng: random.Random) -> list[int]:
    site_xy = positions[:, :2]
    if pattern == "uniform":
        return farthest_site_selection(site_xy, len(positions))
    if pattern == "clustered":
        return clustered_site_selection(site_xy, len(positions))
    if pattern == "stripe":
        return stripe_site_selection(site_xy, len(positions))
    if pattern == "island":
        return island_site_selection(site_xy, len(positions))
    if pattern == "random":
        order = list(range(len(positions)))
        rng.shuffle(order)
        return order
    raise ValueError(f"Unknown pattern: {pattern}")


def choose_pattern_groups(
    pattern: str,
    positions: np.ndarray,
    site_groups: list[tuple[int, ...]],
    count: int,
    rng: random.Random,
) -> list[int]:
    order = ordered_pattern_candidates(pattern, positions, rng)
    rank = {group_id: idx for idx, group_id in enumerate(order)}
    selected = solve_non_overlapping_site_groups(
        site_groups,
        count=count,
        preference_costs=[float(rank[idx]) for idx in range(len(site_groups))],
    )
    if len(selected) != count:
        raise ValueError(
            f"Could not select {count} non-overlapping site groups for pattern={pattern}. "
            "Reduce coverage or site group size."
        )
    return sorted(selected, key=rank.__getitem__)


def solve_non_overlapping_site_groups(
    site_groups: list[tuple[int, ...]],
    *,
    count: int | None = None,
    preference_costs: list[float] | None = None,
) -> list[int]:
    if not site_groups:
        return []
    unique_sites = sorted({site for group in site_groups for site in group})
    site_row = {site: idx for idx, site in enumerate(unique_sites)}
    incidence = np.zeros((len(unique_sites), len(site_groups)), dtype=float)
    for group_id, group in enumerate(site_groups):
        for site in group:
            incidence[site_row[site], group_id] = 1.0

    constraints = [LinearConstraint(incidence, 0.0, 1.0)]
    if count is not None:
        constraints.append(
            LinearConstraint(np.ones((1, len(site_groups))), float(count), float(count))
        )
    objective = (
        np.asarray(preference_costs, dtype=float)
        if preference_costs is not None
        else -np.ones(len(site_groups), dtype=float)
    )
    result = milp(
        c=objective,
        integrality=np.ones(len(site_groups), dtype=int),
        bounds=Bounds(0.0, 1.0),
        constraints=constraints,
        options={"disp": False},
    )
    if not result.success or result.x is None:
        return []
    return [idx for idx, value in enumerate(result.x) if value >= 0.5]


def maximum_non_overlapping_site_groups(site_groups: list[tuple[int, ...]]) -> int:
    return len(solve_non_overlapping_site_groups(site_groups))


def build_coverage_structure(
    slab: Atoms,
    molecule: Atoms,
    site_groups: list[tuple[int, ...]],
    selected_group_ids: list[int],
    placement: dict,
) -> Atoms:
    combined = slab.copy()
    positions = group_positions(slab, site_groups)
    for group_id in selected_group_ids:
        mol = place_molecule(
            molecule=molecule,
            site_position=positions[group_id],
            spin_angle=placement["spin_angle"],
            z_gap=placement["z_gap"],
            dx=placement["dx"],
            dy=placement["dy"],
        )
        combined += mol
    return combined


def plot_adsorbate_landscape(table: pd.DataFrame, output_path: Path) -> None:
    import matplotlib.pyplot as plt

    pattern_order = ["uniform", "clustered", "stripe", "island", "random"]
    pattern_order = [pattern for pattern in pattern_order if pattern in set(table["pattern"])]
    pattern_to_y = {pattern: idx for idx, pattern in enumerate(pattern_order)}
    plot_table = table.copy()
    plot_table["pattern_y"] = plot_table["pattern"].map(pattern_to_y)

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 5.0), constrained_layout=True)

    sc = axes[0].scatter(
        plot_table["coverage"],
        plot_table["pattern_y"],
        c=plot_table["E_ads_per_molecule_eV"],
        cmap="viridis_r",
        s=90,
        edgecolors="black",
        linewidths=0.4,
    )
    axes[0].set_xlabel("Adsorbate coverage")
    axes[0].set_ylabel("Adsorbate distribution")
    axes[0].set_title("Coverage-distribution landscape")
    axes[0].set_yticks(range(len(pattern_order)))
    axes[0].set_yticklabels(pattern_order)
    fig.colorbar(sc, ax=axes[0], label="E_ads per molecule (eV)")

    for pattern, group in table.groupby("pattern"):
        axes[1].scatter(group["coverage"], group["E_ads_per_molecule_eV"], label=pattern, s=64)
    axes[1].set_xlabel("Adsorbate coverage")
    axes[1].set_ylabel("E_ads per molecule (eV)")
    axes[1].set_title("Energy trend")
    axes[1].legend(frameon=False)
    fig.savefig(output_path, dpi=300)
    plt.close(fig)


def run_adsorbate_landscape(
    config: AdsorbateLandscapeConfig,
) -> AdsorbateLandscapeResult:
    args = config
    args.output_dir.mkdir(parents=True, exist_ok=True)
    structures_dir = args.output_dir / "structures"
    structures_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    site_symbols = parse_symbols(args.site_symbols)
    patterns = parse_patterns(args.patterns)

    slab = read(args.surface)
    molecule = read(args.molecule)
    site_indices = get_surface_sites(slab, site_symbols, args.site_z_tolerance, args.max_sites)
    site_groups = build_site_groups(slab, site_indices, args.site_group_size)
    site_group_positions = group_positions(slab, site_groups)
    max_adsorbates = maximum_non_overlapping_site_groups(site_groups)
    coverage_counts = parse_int_list(args.coverage_counts)
    if coverage_counts is None:
        coverage_counts = list(range(1, max_adsorbates + 1))
    coverage_counts = [count for count in coverage_counts if 1 <= count <= max_adsorbates]
    if not coverage_counts:
        raise ValueError("No valid coverage counts remain after applying site count limits.")

    print(f"Surface: {args.surface}")
    print(f"Molecule: {args.molecule}")
    print(f"Output directory: {args.output_dir}")
    print(f"Site symbols: {', '.join(site_symbols)}")
    print(f"Detected adsorption sites: {len(site_indices)}")
    print(f"Site group size per molecule: {args.site_group_size}")
    print(f"Candidate site groups: {len(site_groups)}")
    print(f"Maximum adsorbates in this site model: {max_adsorbates}")
    print(f"Coverage counts: {coverage_counts}")
    print(f"Patterns: {', '.join(patterns)}")
    print(f"Calculator: {args.calculator}")
    if args.calculator == "none":
        print("Using mock calculator: energies are simulated and only valid for workflow testing.")
    else:
        print(f"UMA model: {args.uma_model}, task: {args.task_name}, device: {args.device}")

    calculator = build_calculator(args.calculator, args.uma_model, args.device, args.task_name, args.include_d3)
    e_slab = optimize_energy(slab, calculator, args.fmax, args.max_steps)
    e_mol = optimize_energy(molecule, calculator, args.fmax, args.max_steps)
    write(args.output_dir / "surface_relaxed.cif", slab)
    write(args.output_dir / "molecule_relaxed.cif", molecule)

    single_best, placement = run_single_adsorbate_search(
        slab=slab,
        molecule=molecule,
        site_groups=site_groups,
        e_slab=e_slab,
        e_mol=e_mol,
        calculator=calculator,
        args=args,
    )
    write(args.output_dir / "single_adsorbate_best.cif", single_best)

    rows = []
    structure_paths: list[Path] = []
    structure_id = 0
    for count in coverage_counts:
        for pattern in patterns:
            repeats = args.random_repeats if pattern == "random" else 1
            for repeat in range(1, repeats + 1):
                selected_groups = choose_pattern_groups(pattern, site_group_positions, site_groups, count, rng)
                structure = build_coverage_structure(slab, molecule, site_groups, selected_groups, placement)
                e_total = optimize_energy(structure, calculator, args.fmax, args.max_steps)
                e_ads_total = e_total - e_slab - count * e_mol
                coverage = count / max_adsorbates
                structure_id += 1
                structure_path = structures_dir / f"{args.structure_prefix}_{structure_id}.cif"
                write(structure_path, structure)
                structure_paths.append(structure_path)
                rows.append(
                    {
                        "structure_id": structure_id,
                        "pattern": pattern,
                        "repeat": repeat,
                        "adsorbate_count": count,
                        "max_adsorbates": max_adsorbates,
                        "coverage": coverage,
                        "site_group_size": args.site_group_size,
                        "group_ids": " ".join(str(i) for i in selected_groups),
                        "site_groups": ";".join(
                            " ".join(str(site) for site in site_groups[group_id]) for group_id in selected_groups
                        ),
                        "E_slab_eV": e_slab,
                        "E_mol_eV": e_mol,
                        "E_total_eV": e_total,
                        "E_ads_total_eV": e_ads_total,
                        "E_ads_per_molecule_eV": e_ads_total / count,
                        "structure_path": str(structure_path),
                    }
                )
                print(
                    f"id={structure_id:04d} pattern={pattern} n={count} "
                    f"coverage={coverage:.3f} E_ads/N={e_ads_total / count:.8f} eV"
                )

    table = pd.DataFrame(rows).sort_values("E_ads_per_molecule_eV").reset_index(drop=True)
    csv_path = args.output_dir / "adsorbate_coverage_landscape.csv"
    table.to_csv(csv_path, index=False)
    plot_path = args.output_dir / "adsorbate_coverage_landscape.png"
    plot_adsorbate_landscape(table, plot_path)

    best = table.iloc[0]
    best_structure = read(best["structure_path"])
    best_filename = (
        "workflow_test_best_candidate.cif"
        if args.calculator == "none"
        else "stable_adsorbate_coverage_structure.cif"
    )
    best_path = args.output_dir / best_filename
    write(best_path, best_structure)

    site_table = pd.DataFrame(
        {
            "site_rank": range(1, len(site_indices) + 1),
            "atom_index": site_indices,
            "x_ang": slab.positions[site_indices, 0],
            "y_ang": slab.positions[site_indices, 1],
            "z_ang": slab.positions[site_indices, 2],
        }
    )
    site_table.to_csv(args.output_dir / "adsorption_sites.csv", index=False)
    group_table = pd.DataFrame(
        {
            "group_id": range(len(site_groups)),
            "site_group": [" ".join(str(site) for site in group) for group in site_groups],
            "x_ang": site_group_positions[:, 0],
            "y_ang": site_group_positions[:, 1],
            "z_ang": site_group_positions[:, 2],
        }
    )
    group_table.to_csv(args.output_dir / "adsorption_site_groups.csv", index=False)

    print("\nFinished adsorbate coverage landscape.")
    print(f"Single adsorbate best: {args.output_dir / 'single_adsorbate_best.cif'}")
    print(f"Sites: {args.output_dir / 'adsorption_sites.csv'}")
    print(f"Site groups: {args.output_dir / 'adsorption_site_groups.csv'}")
    print(f"CSV: {csv_path}")
    print(f"Plot: {plot_path}")
    best_label = "Workflow-test best candidate" if args.calculator == "none" else "Stable structure"
    print(f"{best_label}: {best_path}")
    print(
        "Best candidate: "
        f"pattern={best['pattern']}, "
        f"adsorbate_count={int(best['adsorbate_count'])}, "
        f"coverage={best['coverage']:.6f}, "
        f"E_ads/N={best['E_ads_per_molecule_eV']:.8f} eV"
    )
    return AdsorbateLandscapeResult(
        structure_paths=tuple(structure_paths),
        csv_path=csv_path,
        plot_path=plot_path,
        best_candidate_path=best_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Construct adsorbate coverage landscapes using UMA and Optuna.")
    parser.add_argument("--surface", type=Path, default=Path(CONFIG["surface"]))
    parser.add_argument("--molecule", type=Path, default=Path(CONFIG["molecule"]))
    parser.add_argument("--output-dir", type=Path, default=Path(CONFIG["output_dir"]))
    parser.add_argument("--structure-prefix", type=str, default=CONFIG["structure_prefix"])
    parser.add_argument("--site-symbols", type=str, default=CONFIG["site_symbols"])
    parser.add_argument("--site-z-tolerance", type=float, default=CONFIG["site_z_tolerance"])
    parser.add_argument("--max-sites", type=int, default=CONFIG["max_sites"])
    parser.add_argument("--site-group-size", type=int, default=CONFIG["site_group_size"])
    parser.add_argument("--n-trials-single", type=int, default=CONFIG["n_trials_single"])
    parser.add_argument("--site-radius", type=float, default=CONFIG["site_radius"])
    parser.add_argument("--z-gap-min", type=float, default=CONFIG["z_gap_min"])
    parser.add_argument("--z-gap-max", type=float, default=CONFIG["z_gap_max"])
    parser.add_argument("--coverage-counts", type=str, default=CONFIG["coverage_counts"])
    parser.add_argument("--patterns", type=str, default=CONFIG["patterns"])
    parser.add_argument("--random-repeats", type=int, default=CONFIG["random_repeats"])
    parser.add_argument("--seed", type=int, default=CONFIG["seed"])
    parser.add_argument("--calculator", type=str, default=CONFIG["calculator"], choices=["uma", "none"])
    parser.add_argument("--uma-model", type=str, default=CONFIG["uma_model"])
    parser.add_argument("--device", type=str, default=CONFIG["device"], choices=["cuda", "cpu"])
    parser.add_argument("--task-name", type=str, default=CONFIG["task_name"])
    parser.add_argument("--include-d3", action="store_true", default=CONFIG["include_d3"])
    parser.add_argument("--fmax", type=float, default=CONFIG["fmax"])
    parser.add_argument("--max-steps", type=int, default=CONFIG["max_steps"])
    parser.add_argument("--smoke-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.smoke_test:
        for key, value in CONFIG["smoke_test"].items():
            if key == "output_dir":
                value = Path(value)
            setattr(args, key, value)
    del args.smoke_test
    run_adsorbate_landscape(AdsorbateLandscapeConfig(**vars(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
