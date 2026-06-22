#!/usr/bin/env python3
"""
run_ase_job.py — Execute a single ASE/DeePMD job defined by ase_input.json.

This script is designed to be shipped to a compute node (local or remote HPC)
as a common forward file.  It reads ``ase_input.json`` from the current working
directory and performs either a molecular dynamics (MD) simulation or a
structure optimisation using ASE with a DeePMD calculator.

Usage
-----
  # From within a prepared job directory:
  python run_ase_job.py

  # With an explicit input file:
  python run_ase_job.py --input /path/to/ase_input.json

ase_input.json schema — MD
--------------------------
{
  "job_type": "md",
  "structure_file": "structure.extxyz",   // relative to CWD or absolute
  "model_path": "model.pt",               // relative to CWD or absolute
  "head": null,                           // optional multi-task head name
  "save_interval_steps": 100,
  "traj_prefix": "traj",
  "seed": 42,
  "stages": [
    {
      "mode": "NVT",          // NVT|NVT-NH|NVT-Langevin|NVT-Berendsen|NVT-Andersen
                              // NPT-aniso|NPT-tri|NVE
      "temperature_K": 300,
      "pressure": null,       // GPa — required for NPT modes
      "runtime_ps": 1.0,
      "timestep_ps": 0.0005,  // default 0.5 fs
      "tau_t_ps": 0.01,       // thermostat relaxation time (default 10 fs)
      "tau_p_ps": 0.1         // barostat relaxation time  (default 100 fs)
    }
  ]
}

ase_input.json schema — relax
------------------------------
{
  "job_type": "relax",
  "structure_file": "structure.extxyz",
  "model_path": "model.pt",
  "head": null,
  "force_tolerance": 0.01,   // eV/Å
  "max_iterations": 100,
  "relax_cell": false
}

Output files
------------
  MD:    trajectories/<prefix>_stage<N>_<mode>_<T>K[_<P>GPa].extxyz
         md_simulation.log
         status.json

  Relax: <stem>_optimized.cif
         <stem>_optimization_traj.extxyz
         optimization.log
         status.json
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import warnings

import numpy as np
from ase import units

warnings.filterwarnings("ignore", message="invalid value encountered in det",
                        category=RuntimeWarning)
from ase.io import read, write
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
from ase.optimize import BFGS
from ase.filters import ExpCellFilter


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _setup_logging(log_file: str) -> logging.FileHandler:
    handler = logging.FileHandler(log_file)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler


def _teardown_logging(handler: logging.FileHandler) -> None:
    logging.getLogger().removeHandler(handler)
    handler.close()


# ---------------------------------------------------------------------------
# Shared MD helpers
# ---------------------------------------------------------------------------

def _log_md_progress(atoms, dyn) -> None:
    epot = atoms.get_potential_energy()
    ekin = atoms.get_kinetic_energy()
    temp = ekin / (1.5 * len(atoms) * units.kB)
    logging.info(f"Step: {dyn.nsteps:6d}, E_pot: {epot:.4f} eV, T: {temp:.2f} K")


def _make_md_dynamics(atoms, stage):
    """Instantiate an ASE dynamics object for *stage* and return it."""
    mode = stage["mode"]
    temperature_K = stage.get("temperature_K")
    pressure = stage.get("pressure")
    timestep_ps = stage.get("timestep_ps", 0.0005)
    tau_t_ps = stage.get("tau_t_ps", 0.01)
    tau_p_ps = stage.get("tau_p_ps", 0.1)

    timestep_fs = timestep_ps * 1000.0

    if mode in ("NVT", "NVT-NH"):
        from ase.md.nose_hoover_chain import NoseHooverChainNVT
        return NoseHooverChainNVT(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temperature_K,
            tdamp=tau_t_ps * 1000.0 * units.fs,
        ), timestep_fs

    if mode == "NVT-Langevin" or mode == "Langevin":
        from ase.md.langevin import Langevin
        return Langevin(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temperature_K,
            friction=1.0 / (tau_t_ps * 1000.0 * units.fs),
            rng=np.random.RandomState(42),
        ), timestep_fs

    if mode == "NVT-Berendsen":
        from ase.md.nvtberendsen import NVTBerendsen
        return NVTBerendsen(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temperature_K,
            taut=tau_t_ps * 1000.0 * units.fs,
        ), timestep_fs

    if mode == "NVT-Andersen":
        from ase.md.andersen import Andersen
        return Andersen(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temperature_K,
            friction=1.0 / (tau_t_ps * 1000.0 * units.fs),
            rng=np.random.RandomState(42),
        ), timestep_fs

    if mode in ("NPT-aniso", "NPT-tri"):
        from ase.md.melchionna import MelchionnaNPT as NPT
        if pressure is None:
            raise ValueError(f"'pressure' is required for {mode} mode.")
        mask = np.eye(3, dtype=bool) if mode == "NPT-aniso" else None
        return NPT(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temperature_K,
            externalstress=pressure * units.GPa,
            ttime=tau_t_ps * 1000.0 * units.fs,
            pfactor=tau_p_ps * 1000.0 * units.fs,
            mask=mask,
        ), timestep_fs

    if mode == "NVE":
        from ase.md.verlet import VelocityVerlet
        return VelocityVerlet(
            atoms,
            timestep=timestep_fs * units.fs,
        ), timestep_fs

    raise ValueError(f"Unknown MD mode: {mode!r}")


def _run_md_stage(atoms, stage, save_interval_steps: int,
                  traj_file: str, seed: int, stage_id: int):
    """Run one MD stage and append frames to *traj_file* (extxyz)."""
    temperature_K = stage.get("temperature_K")
    pressure = stage.get("pressure")
    mode = stage["mode"]
    runtime_ps = stage["runtime_ps"]
    timestep_ps = stage.get("timestep_ps", 0.0005)

    timestep_fs = timestep_ps * 1000.0
    total_steps = max(1, int(runtime_ps * 1000.0 / timestep_fs))

    # Initialise velocities for the first stage that has a temperature target
    if stage_id == 1 and temperature_K is not None:
        MaxwellBoltzmannDistribution(
            atoms, temperature_K=temperature_K,
            rng=np.random.RandomState(seed),
        )
        from ase.md.velocitydistribution import Stationary, ZeroRotation
        Stationary(atoms)
        ZeroRotation(atoms)

    dyn, _ = _make_md_dynamics(atoms, stage)

    # Ensure trajectory directory exists; remove any stale file
    traj_path = Path(traj_file)
    traj_path.parent.mkdir(parents=True, exist_ok=True)
    if traj_path.exists():
        traj_path.unlink()

    def _write_frame():
        results = atoms.calc.results
        energy = results.get("energy", atoms.get_potential_energy())
        forces = results.get("forces", atoms.get_forces())
        stress = results.get("stress", atoms.get_stress(voigt=False))

        if (np.any(np.isnan(energy)) or np.any(np.isnan(forces))
                or np.any(np.isnan(stress))):
            raise ValueError("NaN detected in simulation outputs. Aborting.")

        snapshot = atoms.copy()
        snapshot.info["energy"] = float(np.ravel(energy)[0])
        snapshot.arrays["force"] = np.asarray(forces)
        # Strip CIF-specific info that breaks extxyz serialisation
        for key in ("occupancy", "spacegroup"):
            snapshot.info.pop(key, None)
        write(traj_file, snapshot, format="extxyz", append=True)

    dyn.attach(_write_frame, interval=save_interval_steps)
    dyn.attach(lambda: _log_md_progress(atoms, dyn), interval=10)

    logging.info(
        f"[Stage {stage_id}] {mode}: T={temperature_K} K"
        + (f", P={pressure} GPa" if pressure is not None else "")
        + f", steps={total_steps}, dt={timestep_ps} ps"
    )
    dyn.run(total_steps)
    logging.info(f"[Stage {stage_id}] Done. Trajectory: {traj_file}")
    return atoms


# ---------------------------------------------------------------------------
# MD entry point
# ---------------------------------------------------------------------------

def run_md(params: dict) -> dict:
    """Execute a multi-stage MD simulation as described in *params*.

    Returns a result dict written to status.json (success or error).
    """
    from deepmd.calculator import DP

    structure_file = params["structure_file"]
    model_path = params["model_path"]
    head = params.get("head")
    stages = params["stages"]
    save_interval_steps = int(params.get("save_interval_steps", 100))
    traj_prefix = params.get("traj_prefix", "traj")
    seed = int(params.get("seed", 42))

    log_handler = _setup_logging("md_simulation.log")
    trajectory_files = []
    i = 0

    try:
        traj_dir = Path("trajectories")
        traj_dir.mkdir(parents=True, exist_ok=True)

        logging.info(f"Loading DeePMD model: {model_path}")
        calc = DP(model=model_path, head=head)

        atoms = read(structure_file, index=0)
        atoms.calc = calc
        logging.info(f"Structure: {len(atoms)} atoms")
        logging.info(f"Number of stages: {len(stages)}")

        for i, stage in enumerate(stages):
            mode = stage.get("mode", "NVT")
            T = stage.get("temperature_K", "NA")
            P = stage.get("pressure", "NA")
            runtime_ps = stage.get("runtime_ps", 0.5)

            tag = f"stage{i + 1}_{mode}_{T}K"
            if P != "NA" and P is not None:
                tag += f"_{P}GPa"
            traj_file = traj_dir / f"{traj_prefix}_{tag}.extxyz"
            trajectory_files.append(str(traj_file))

            logging.info(
                f"Stage {i + 1}: {mode}, T={T} K, runtime={runtime_ps} ps"
            )
            atoms = _run_md_stage(
                atoms=atoms,
                stage=stage,
                save_interval_steps=save_interval_steps,
                traj_file=str(traj_file),
                seed=seed,
                stage_id=i + 1,
            )

        logging.info("MD simulation completed successfully.")
        status = {
            "status": "success",
            "message": "MD simulation completed successfully.",
            "total_stages": len(stages),
            "stages_completed": len(stages),
            "trajectory_files": trajectory_files,
            "simulation_details": {
                "num_atoms": len(atoms),
                "save_interval_steps": save_interval_steps,
                "seed": seed,
            },
        }

    except Exception as exc:
        logging.error(f"MD simulation failed: {exc}", exc_info=True)
        status = {
            "status": "error",
            "message": str(exc),
            "total_stages": len(stages),
            "stages_completed": i,
            "trajectory_files": trajectory_files,
        }

    finally:
        _teardown_logging(log_handler)

    with open("status.json", "w") as fp:
        json.dump(status, fp, indent=2)
    return status


# ---------------------------------------------------------------------------
# Relax entry point
# ---------------------------------------------------------------------------

def run_relax(params: dict) -> dict:
    """Execute a BFGS structure optimisation as described in *params*.

    Returns a result dict written to status.json (success or error).
    """
    from deepmd.calculator import DP

    structure_file = params["structure_file"]
    model_path = params["model_path"]
    head = params.get("head")
    force_tol = float(params.get("force_tolerance", 0.01))
    max_iter = int(params.get("max_iterations", 100))
    relax_cell = bool(params.get("relax_cell", False))

    stem = Path(structure_file).stem
    log_handler = _setup_logging("optimization.log")

    try:
        logging.info(f"Loading DeePMD model: {model_path}")
        calc = DP(model=model_path, head=head)

        atoms = read(structure_file, index=0)
        atoms.calc = calc
        logging.info(f"Structure: {len(atoms)} atoms")

        traj_file = f"{stem}_optimization_traj.extxyz"
        if Path(traj_file).exists():
            Path(traj_file).unlink()

        logging.info(
            f"Starting BFGS optimisation (fmax={force_tol} eV/Å, "
            f"max_steps={max_iter}, relax_cell={relax_cell})"
        )

        if relax_cell:
            logging.info("Using ExpCellFilter for cell relaxation.")
            target = ExpCellFilter(atoms)
        else:
            target = atoms

        def _write_opt_frame():
            results = atoms.calc.results
            energy = results.get("energy", atoms.get_potential_energy())
            forces = results.get("forces", atoms.get_forces())
            snapshot = atoms.copy()
            snapshot.info["energy"] = float(np.ravel(energy)[0])
            snapshot.arrays["force"] = np.asarray(forces)
            write(traj_file, snapshot, format="extxyz", append=True)

        optimizer = BFGS(target, logfile="optimization.log")
        optimizer.attach(_write_opt_frame, interval=1)
        optimizer.run(fmax=force_tol, steps=max_iter)

        output_file = f"{stem}_optimized.cif"
        write(output_file, atoms)
        final_energy = float(atoms.get_potential_energy())

        logging.info(
            f"Optimisation done in {optimizer.nsteps} steps. "
            f"Final energy: {final_energy:.6f} eV"
        )
        status = {
            "status": "success",
            "message": f"Completed in {optimizer.nsteps} steps.",
            "optimized_structure": output_file,
            "optimization_traj": traj_file,
            "final_energy": final_energy,
        }

    except Exception as exc:
        logging.error(f"Optimisation failed: {exc}", exc_info=True)
        status = {
            "status": "error",
            "message": str(exc),
            "optimized_structure": "",
            "optimization_traj": "",
            "final_energy": None,
        }

    finally:
        _teardown_logging(log_handler)

    with open("status.json", "w") as fp:
        json.dump(status, fp, indent=2)
    return status


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an ASE/DeePMD job from ase_input.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", type=Path, default=Path("ase_input.json"),
        help="Path to ase_input.json (default: ase_input.json in CWD).",
    )
    parser.add_argument(
        "--model_path", type=str, default=None,
        help=(
            "Override the model_path in ase_input.json.  "
            "Useful when the model lives at a different path than recorded "
            "at prepare time (e.g. running locally after remote preparation)."
        ),
    )
    args = parser.parse_args()

    input_path = args.input
    if not input_path.exists():
        print(
            json.dumps({"status": "error",
                        "message": f"Input file not found: {input_path}"}),
            file=sys.stderr,
        )
        sys.exit(1)

    with open(input_path) as fp:
        params = json.load(fp)

    # CLI --model_path takes precedence over whatever ase_input.json records.
    if args.model_path is not None:
        params["model_path"] = args.model_path

    job_type = params.get("job_type", "md").lower()

    if job_type == "md":
        result = run_md(params)
    elif job_type == "relax":
        result = run_relax(params)
    else:
        result = {"status": "error", "message": f"Unknown job_type: {job_type!r}"}
        with open("status.json", "w") as fp:
            json.dump(result, fp, indent=2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
