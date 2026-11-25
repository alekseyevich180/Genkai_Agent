"""Energy models for the MLIP screening steps of the surface builders.

``build_calculator`` returns one of

* ``none`` - :class:`ContactMockCalculator`, a workflow-test stand-in: forces
  are zero (relaxations do not move atoms) and the energy is a soft pair score
  that prefers bond-length contacts and penalizes overlaps. Its energies have
  **no physical meaning**; manifests must say so.
* ``emt`` - ASE EMT (a few fcc metals plus H, C, N, O only).
* ``uma`` - a FAIRChem UMA model. The task head is checked against the
  installed fairchem version before the model is loaded (fairchem 2.7.1 has
  omol, omat, odac, oc20, oc25 and omc; no oc22).
* ``mace`` - a local MACE checkpoint through its ASE calculator. The model
  must be supplied with ``mace_model`` or the ``MACE_MODEL`` environment variable.

Running ``uma`` or ``mace`` is a real MLIP calculation and needs explicit
authorization (see AGENTS.md).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import numpy as np
from ase import Atoms
from ase.calculators.calculator import Calculator, all_changes
from ase.data import covalent_radii

from ..structure_io import sanitize_atoms_info

CALCULATORS = ("none", "emt", "uma", "mace")
MOCK_NOTE = "calculator=none: mock contact score, energies have no physical meaning"


def resolve_mace_model(model: str | Path | None = None) -> str:
    """Resolve an explicit local checkpoint; never download a model implicitly."""
    value = model or os.environ.get("MACE_MODEL")
    if not value:
        raise ValueError("MACE needs a local checkpoint: set --mace-model or MACE_MODEL.")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"MACE checkpoint does not exist: {path}")
    return str(path)


def add_mace_arguments(parser: argparse.ArgumentParser) -> None:
    """Shared options, including aliases for the older underscore-style CLI."""
    parser.add_argument(
        "--mace-model", "--mace_model", default=os.environ.get("MACE_MODEL"),
        help="Local MACE checkpoint (or set MACE_MODEL); no automatic download.",
    )
    parser.add_argument(
        "--mace-dtype", "--mace_dtype", choices=("float32", "float64"), default="float32",
        help="MACE inference precision (default: float32).",
    )


class ContactMockCalculator(Calculator):
    """Workflow-test calculator: zero forces, energy = soft pair contact score."""

    implemented_properties = ["energy", "forces"]

    def __init__(self, epsilon: float = 0.05, cutoff_factor: float = 2.0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.epsilon = epsilon
        self.cutoff_factor = cutoff_factor

    def calculate(self, atoms=None, properties=("energy",), system_changes=all_changes):
        super().calculate(atoms, properties, system_changes)
        from ase.neighborlist import neighbor_list

        probe = self.atoms.copy()
        probe.set_constraint()
        radii = covalent_radii[probe.numbers]
        cutoff = float(self.cutoff_factor * 2.0 * radii.max()) if len(probe) else 0.0
        i, j, d = neighbor_list("ijd", probe, cutoff) if len(probe) > 1 and cutoff > 0 else ([], [], [])
        energy = 0.0
        if len(d):
            sigma = radii[i] + radii[j]
            keep = d < self.cutoff_factor * sigma
            ratio = sigma[keep] / np.maximum(d[keep], 1e-6)
            # Lennard-Jones-like well at d = sigma; each pair is listed twice.
            energy = 0.5 * float((self.epsilon * (ratio**12 - 2.0 * ratio**6)).sum())
        self.results["energy"] = energy
        self.results["forces"] = np.zeros((len(self.atoms), 3))


def available_uma_tasks() -> list[str] | None:
    """Task heads of the installed fairchem, or None if fairchem is not importable."""
    try:
        from fairchem.core.units.mlip_unit.api.inference import UMATask
    except Exception:
        return None
    return [task.value for task in UMATask]


def validate_uma_task(task_name: str) -> None:
    """Fail before loading a model when the task head does not exist in this fairchem."""
    tasks = available_uma_tasks()
    if tasks is not None and task_name not in tasks:
        raise ValueError(
            f"UMA task head {task_name!r} is not available in the installed fairchem "
            f"(available: {', '.join(tasks)}); choose one explicitly with the task-name option."
        )


def build_calculator(
    name: str,
    *,
    uma_model: str = "uma-s-1p2",
    task_name: str = "omat",
    device: str = "cuda",
    include_d3: bool = False,
    checkpoint: str | None = None,
    mace_model: str | Path | None = None,
    mace_dtype: str = "float32",
) -> Calculator:
    if name == "none":
        return ContactMockCalculator()
    if name == "emt":
        from ase.calculators.emt import EMT

        return EMT()
    if name not in ("uma", "mace"):
        raise ValueError(f"Unknown calculator {name!r}; choose from {', '.join(CALCULATORS)}.")
    if name == "mace":
        if checkpoint:
            raise ValueError("--checkpoint is for UMA; use --mace-model for MACE.")
        model_path = resolve_mace_model(mace_model)
        if mace_dtype not in ("float32", "float64"):
            raise ValueError("mace_dtype must be float32 or float64.")
        try:
            from mace.calculators import MACECalculator
        except ImportError as exc:
            raise ImportError("MACE is unavailable in this Python environment; use the MACE launcher or install Genkai[mace].") from exc
        calc: Calculator = MACECalculator(model_paths=model_path, device=device, default_dtype=mace_dtype)
    else:
        validate_uma_task(task_name)
        try:
            from fairchem.core import FAIRChemCalculator, pretrained_mlip
        except ImportError as exc:
            raise ImportError("UMA is unavailable in this Python environment; use the UMA launcher or install Genkai[mlip].") from exc
        if checkpoint or Path(uma_model).is_file():
            checkpoint = checkpoint or uma_model
            calc = FAIRChemCalculator.from_model_checkpoint(checkpoint, task_name=task_name, device=device)
        else:
            predictor = pretrained_mlip.get_predict_unit(uma_model, device=device)
            calc = FAIRChemCalculator(predictor, task_name=task_name)
    if include_d3:
        from ase.calculators.dftd3 import DFTD3

        calc = DFTD3(dft=calc)
    return calc


def relax(atoms: Atoms, calculator: Calculator, *, fmax: float = 0.05, steps: int = 200, cell: bool = False) -> float:
    """LBFGS relaxation in place (FixAtoms honoured); ``cell=True`` also relaxes the cell."""
    from ase.optimize import LBFGS

    sanitize_atoms_info(atoms)
    atoms.calc = calculator
    if steps > 0 and not isinstance(calculator, ContactMockCalculator):  # the mock has zero forces and no stress
        if cell:
            from ase.filters import FrechetCellFilter

            LBFGS(FrechetCellFilter(atoms), logfile=None).run(fmax=fmax, steps=steps)
        else:
            LBFGS(atoms, logfile=None).run(fmax=fmax, steps=steps)
    return float(atoms.get_potential_energy())


def anneal(atoms: Atoms, calculator: Calculator, *, temperature: float, steps: int, timestep_fs: float = 1.0, seed: int = 0) -> None:
    """Langevin MD in place (FixAtoms honoured); a no-op for zero steps."""
    if steps <= 0:
        return
    from ase import units
    from ase.md.langevin import Langevin
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    sanitize_atoms_info(atoms)
    atoms.calc = calculator
    MaxwellBoltzmannDistribution(atoms, temperature_K=temperature, rng=np.random.default_rng(seed))
    Langevin(atoms, timestep_fs * units.fs, temperature_K=temperature, friction=0.02, rng=np.random.default_rng(seed + 1)).run(steps)


def is_mock(name: str) -> bool:
    return name == "none"


def evidence_for(name: str) -> str:
    return {"none": "mock", "emt": "empirical_potential", "uma": "mlip_predicted", "mace": "mlip_predicted"}[name]


def molecule_in_box(molecule: Atoms, padding: float = 12.0) -> Atoms:
    """Isolated molecule centred in a cubic periodic box (for gas-phase reference energies)."""
    boxed = sanitize_atoms_info(molecule.copy())
    boxed.set_constraint()
    extent = float(np.ptp(boxed.positions, axis=0).max()) if len(boxed) > 1 else 0.0
    size = max(20.0, extent + padding)
    boxed.set_cell([size, size, size])
    boxed.pbc = True
    boxed.center()
    return boxed
