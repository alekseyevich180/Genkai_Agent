import argparse
import itertools
import math
import random
from pathlib import Path

import numpy as np
import pandas as pd
from ase import Atoms
from ase.calculators.calculator import Calculator, all_changes
from ase.io import read, write
from ase.optimize import LBFGS


CONFIG = {
    # Input/output
    "input": "CeO2 (1 1 1).cif",
    "output_dir": "output_vacancy_landscape",
    "structure_prefix": "ov",
    "write_all_structures": True,
    # Vacancy sampling
    "vacancy_counts": "1,2,3,4,5",
    "samples_per_count": 20,
    "z_frac_min": 0.0,
    "z_frac_max": 1.0,
    "seed": 7,
    # Energy descriptor
    "mu_o": 0.0,
    # Calculator
    "calculator": "none",  # "uma" for real runs, "none" for workflow tests
    "uma_model": "uma-s-1p2",
    "device": "cuda",
    "task_name": "omat",
    "include_d3": False,
    # Relaxation
    "fmax": 0.05,
    "max_steps": 200,
    # Fast local test without UMA
    "smoke_test": {
        "output_dir": "output_vacancy_landscape_smoke",
        "vacancy_counts": "1,2",
        "samples_per_count": 3,
        "calculator": "none",
        "max_steps": 0,
        "write_all_structures": True,
    },
}


class CompositionTestCalculator(Calculator):
    implemented_properties = ["energy", "forces"]

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        symbols = self.atoms.get_chemical_symbols()
        energy = -4.0 * symbols.count("Ce") - 2.0 * symbols.count("O")
        self.results["energy"] = float(energy)
        self.results["forces"] = np.zeros((len(symbols), 3), dtype=float)


def build_calculator(calculator_name: str, uma_model: str, device: str, task_name: str, include_d3: bool):
    if calculator_name == "none":
        return CompositionTestCalculator()

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


def oxygen_indices(atoms: Atoms, symbol: str = "O", z_frac_min: float = 0.0, z_frac_max: float = 1.0) -> list[int]:
    scaled = atoms.get_scaled_positions(wrap=True)
    indices = [
        atom.index
        for atom in atoms
        if atom.symbol == symbol and z_frac_min <= scaled[atom.index, 2] <= z_frac_max
    ]
    if not indices:
        symbols = sorted(set(atoms.get_chemical_symbols()))
        raise ValueError(
            f"No {symbol} atoms found in z fractional range [{z_frac_min}, {z_frac_max}]. "
            f"Available symbols: {', '.join(symbols)}"
        )
    return indices


def parse_vacancy_counts(text: str | None, oxygen_count: int) -> list[int]:
    if not text:
        return [1]

    counts = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        count = int(item)
        if count < 1 or count >= oxygen_count:
            raise ValueError(f"Vacancy count must be between 1 and {oxygen_count - 1}: {count}")
        counts.append(count)

    return sorted(set(counts))


def sample_vacancy_sets(
    candidates: list[int],
    vacancy_count: int,
    samples: int,
    rng: random.Random,
) -> list[tuple[int, ...]]:
    total_combinations = math.comb(len(candidates), vacancy_count)
    if total_combinations <= samples:
        return list(itertools.combinations(candidates, vacancy_count))

    selected: set[tuple[int, ...]] = set()
    while len(selected) < samples:
        selected.add(tuple(sorted(rng.sample(candidates, vacancy_count))))
    return sorted(selected)


def remove_vacancies(atoms: Atoms, vacancy_set: tuple[int, ...]) -> Atoms:
    defect = atoms.copy()
    for index in sorted(vacancy_set, reverse=True):
        del defect[index]
    return defect


def vacancy_position_features(atoms: Atoms, vacancy_set: tuple[int, ...]) -> dict[str, float]:
    scaled = atoms.get_scaled_positions(wrap=True)[list(vacancy_set)]
    cart = atoms.positions[list(vacancy_set)]
    mean_scaled = scaled.mean(axis=0)
    mean_cart = cart.mean(axis=0)
    return {
        "vacancy_x_frac": float(mean_scaled[0]),
        "vacancy_y_frac": float(mean_scaled[1]),
        "vacancy_z_frac": float(mean_scaled[2]),
        "vacancy_x_ang": float(mean_cart[0]),
        "vacancy_y_ang": float(mean_cart[1]),
        "vacancy_z_ang": float(mean_cart[2]),
    }


def plot_landscape(table: pd.DataFrame, output_path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)

    sc = axes[0].scatter(
        table["vacancy_concentration"],
        table["vacancy_z_frac"],
        c=table["E_vac_eV"],
        cmap="viridis_r",
        s=70,
        edgecolors="black",
        linewidths=0.4,
    )
    axes[0].set_xlabel("Vacancy concentration")
    axes[0].set_ylabel("Mean vacancy z position (fractional)")
    axes[0].set_title("Concentration-position landscape")
    fig.colorbar(sc, ax=axes[0], label="E_vac (eV)")

    for count, group in table.groupby("vacancy_count"):
        axes[1].scatter(
            group["vacancy_concentration"],
            group["E_vac_eV"],
            label=f"m={count}",
            s=60,
            edgecolors="black",
            linewidths=0.4,
        )
    axes[1].set_xlabel("Vacancy concentration")
    axes[1].set_ylabel("E_vac (eV)")
    axes[1].set_title("Vacancy formation energy")
    axes[1].legend(frameon=False)

    fig.savefig(output_path, dpi=300)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Construct an oxygen-vacancy energy landscape from an oxide-surface CIF using UMA."
    )
    parser.add_argument("--input", type=Path, default=Path(CONFIG["input"]))
    parser.add_argument("--output-dir", type=Path, default=Path(CONFIG["output_dir"]))
    parser.add_argument("--structure-prefix", type=str, default=CONFIG["structure_prefix"])
    parser.add_argument(
        "--vacancy-counts",
        type=str,
        default=CONFIG["vacancy_counts"],
        help="Comma-separated numbers of O vacancies.",
    )
    parser.add_argument("--samples-per-count", type=int, default=CONFIG["samples_per_count"])
    parser.add_argument("--mu-o", type=float, default=CONFIG["mu_o"], help="Oxygen chemical potential in eV.")
    parser.add_argument(
        "--z-frac-min",
        type=float,
        default=CONFIG["z_frac_min"],
        help="Minimum fractional z for selectable O sites.",
    )
    parser.add_argument(
        "--z-frac-max",
        type=float,
        default=CONFIG["z_frac_max"],
        help="Maximum fractional z for selectable O sites.",
    )
    parser.add_argument("--calculator", type=str, default=CONFIG["calculator"], choices=["uma", "none"])
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a fast mock calculation to test vacancy generation, CSV output, and plotting without UMA.",
    )
    parser.add_argument("--uma-model", type=str, default=CONFIG["uma_model"])
    parser.add_argument("--device", type=str, default=CONFIG["device"], choices=["cuda", "cpu"])
    parser.add_argument("--task-name", type=str, default=CONFIG["task_name"])
    parser.add_argument("--include-d3", action="store_true", default=CONFIG["include_d3"])
    parser.add_argument("--fmax", type=float, default=CONFIG["fmax"])
    parser.add_argument("--max-steps", type=int, default=CONFIG["max_steps"])
    parser.add_argument("--seed", type=int, default=CONFIG["seed"])
    parser.add_argument("--write-all-structures", action="store_true", default=CONFIG["write_all_structures"])
    args = parser.parse_args()

    if args.smoke_test:
        for key, value in CONFIG["smoke_test"].items():
            if key == "output_dir":
                value = Path(value)
            setattr(args, key, value)

    if args.samples_per_count < 1:
        raise ValueError("--samples-per-count must be >= 1")
    if not 0.0 <= args.z_frac_min <= args.z_frac_max <= 1.0:
        raise ValueError("--z-frac-min and --z-frac-max must satisfy 0 <= min <= max <= 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    structures_dir = args.output_dir / "structures"
    structures_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    clean = read(args.input)
    all_o_indices = oxygen_indices(clean)
    o_indices = oxygen_indices(clean, z_frac_min=args.z_frac_min, z_frac_max=args.z_frac_max)
    vacancy_counts = parse_vacancy_counts(args.vacancy_counts, len(o_indices))

    print(f"Input structure: {args.input}")
    print(f"Output directory: {args.output_dir}")
    print(f"Atoms: {len(clean)}, total oxygen atoms: {len(all_o_indices)}")
    print(
        f"Selectable oxygen atoms: {len(o_indices)} "
        f"(z_frac range {args.z_frac_min:.3f}-{args.z_frac_max:.3f})"
    )
    print(f"Vacancy counts: {vacancy_counts}")
    print(f"Calculator: {args.calculator}")
    if args.calculator == "uma":
        print(f"UMA model: {args.uma_model}, task: {args.task_name}, device: {args.device}")
    else:
        print("Using mock calculator: energies are simulated and only valid for workflow testing.")

    calculator = build_calculator(args.calculator, args.uma_model, args.device, args.task_name, args.include_d3)

    clean_relaxed = clean.copy()
    clean_energy = optimize_energy(clean_relaxed, calculator, args.fmax, args.max_steps)
    clean_path = args.output_dir / "clean_relaxed.cif"
    write(clean_path, clean_relaxed)
    print(f"Clean relaxed energy: {clean_energy:.8f} eV")

    records = []
    trial_id = 0
    for vacancy_count in vacancy_counts:
        vacancy_sets = sample_vacancy_sets(o_indices, vacancy_count, args.samples_per_count, rng)
        for vacancy_set in vacancy_sets:
            trial_id += 1
            defect = remove_vacancies(clean_relaxed, vacancy_set)
            defect_energy = optimize_energy(defect, calculator, args.fmax, args.max_steps)
            e_vac = defect_energy - clean_energy + vacancy_count * args.mu_o
            concentration = vacancy_count / len(all_o_indices)

            structure_name = f"{args.structure_prefix}_{trial_id}.cif"
            structure_path = structures_dir / structure_name
            if args.write_all_structures:
                write(structure_path, defect)

            record = {
                "trial_id": trial_id,
                "vacancy_count": vacancy_count,
                "vacancy_concentration": concentration,
                "vacancy_indices": " ".join(str(i) for i in vacancy_set),
                "E_clean_eV": clean_energy,
                "E_defect_eV": defect_energy,
                "mu_O_eV": args.mu_o,
                "E_vac_eV": e_vac,
                "E_vac_per_vacancy_eV": e_vac / vacancy_count,
                "structure_path": str(structure_path) if args.write_all_structures else "",
            }
            record.update(vacancy_position_features(clean_relaxed, vacancy_set))
            records.append(record)
            print(
                f"trial={trial_id:04d} m={vacancy_count} "
                f"conc={concentration:.4f} E_vac={e_vac:.8f} eV"
            )

    table = pd.DataFrame(records).sort_values("E_vac_eV").reset_index(drop=True)
    csv_path = args.output_dir / "vacancy_energy_landscape.csv"
    table.to_csv(csv_path, index=False)

    best = table.iloc[0]
    best_indices = tuple(int(x) for x in str(best["vacancy_indices"]).split())
    best_structure = remove_vacancies(clean_relaxed, best_indices)
    best_energy = optimize_energy(best_structure, calculator, args.fmax, args.max_steps)
    best_path = args.output_dir / "stable_vacancy_structure.cif"
    write(best_path, best_structure)

    plot_path = args.output_dir / "vacancy_energy_landscape.png"
    plot_landscape(table, plot_path)

    print("\nFinished oxygen-vacancy landscape.")
    print(f"CSV: {csv_path}")
    print(f"Plot: {plot_path}")
    print(f"Stable structure: {best_path}")
    print(
        "Best candidate: "
        f"m={int(best['vacancy_count'])}, "
        f"concentration={best['vacancy_concentration']:.6f}, "
        f"indices={best['vacancy_indices']}, "
        f"E_vac={best['E_vac_eV']:.8f} eV, "
        f"relaxed_energy={best_energy:.8f} eV"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
