#!/usr/bin/env python3
"""
ase_deepmd_tools.py — Prepare ASE/DeePMD job directories and collect results.

Commands
--------
  prepare_md      Create per-structure job directories for MD simulation.
  prepare_relax   Create per-structure job directories for structure optimisation.
  collect_md      Collect trajectory files from completed MD jobs into one extxyz.
  collect_relax   Collect optimised structures from completed relax jobs into one extxyz.

Every command prints a JSON object to stdout and exits 0 on success, 1 on error.

Examples
--------
  # Prepare MD jobs for all frames in structures.extxyz
  python ase_deepmd_tools.py prepare_md \\
      --structures structures.extxyz \\
      --model_path /path/to/model.pt \\
      --stages '[{"mode":"NVT","temperature_K":300,"runtime_ps":10,"timestep_ps":0.001}]'

  # Prepare MD — model already lives on the remote node (no local copy)
  python ase_deepmd_tools.py prepare_md \\
      --structures structures.extxyz \\
      --remote_model_path /remote/data/model.pt \\
      --stages '[{"mode":"NVT","temperature_K":300,"runtime_ps":10}]'

  # Prepare relax jobs, allowing cell shape to change
  python ase_deepmd_tools.py prepare_relax \\
      --structures structures.extxyz \\
      --model_path /path/to/model.pt \\
      --relax_cell

  # Collect all trajectory frames from finished MD jobs
  python ase_deepmd_tools.py collect_md \\
      --calc_dirs /tmp/ase_jobs/md_001 /tmp/ase_jobs/md_002

  # Collect optimised structures from finished relax jobs
  python ase_deepmd_tools.py collect_relax \\
      --calc_dirs /tmp/ase_jobs/relax_001 /tmp/ase_jobs/relax_002

Notes on model handling
-----------------------
* --model_path (local)   : the model file is copied once into the batch directory
  (the common parent of all job dirs created in one prepare_* call).  Each job's
  ase_input.json references it as ``../model.pt`` — one level up.  This avoids
  redundant copies while keeping each batch self-contained for remote submission.
* --remote_model_path    : no model file is transferred; ase_input.json records the
  absolute remote path.  Use when the model is already on the HPC file system.

run_ase_job.py handling
-----------------------
* run_ase_job.py (the job runner script that lives alongside this file) is always
  copied into the batch directory alongside model.pt.  Both files are then listed
  in ``forward_common_files`` when building the DPDispatcher submission JSON so
  they are uploaded once to the remote root and shared by every task.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml
from ase.io import read, write

# ---------------------------------------------------------------------------
# Config / env helpers
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent
_DEFAULT_CONFIG = _SCRIPT_DIR / "config.yaml"
_MODEL_FILENAME = "model.pt"   # name used inside every job directory
_FROZEN_MODEL_FILENAME = "frozen_model.pth"


def _load_config(config_path: Path) -> dict:
    with open(config_path) as fh:
        return yaml.safe_load(fh)


def _freeze_model(pretrained: Path, head: str, output: Path) -> Path:
    """Freeze a multi-task DeePMD model to a single-task one via ``dp freeze``."""
    cmd = ["dp", "--pt", "freeze", "-c", str(pretrained), "--head", head, "-o", str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"dp freeze failed (exit {result.returncode}):\n{result.stderr}"
        )
    if not output.exists():
        raise FileNotFoundError(f"Freeze command ran but output not found: {output}")
    return output


def _load_env(config_path: Path) -> None:
    from dotenv import load_dotenv
    env_file = config_path.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _default_model_path() -> Optional[Path]:
    """Return the default local model path from env var ASE_DEEPMD_MODEL_PATH, or None."""
    val = os.environ.get("DEEPMD_MODEL_PATH")
    return Path(val) if val else None


def _job_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S_%f")


# ---------------------------------------------------------------------------
# prepare_md
# ---------------------------------------------------------------------------

def cmd_prepare_md(args) -> dict:
    """Create one job directory per structure for a multi-stage MD simulation."""
    config = _load_config(args.config)
    work_dir = Path(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    stages = json.loads(args.stages)
    extra = json.loads(args.extra_params) if args.extra_params else {}

    # Resolve model: explicit flag > ASE_DEEPMD_MODEL_PATH env var > remote reference
    local_model: Optional[Path] = None
    if args.model_path:
        local_model = Path(args.model_path).resolve()
        if not local_model.exists():
            raise FileNotFoundError(f"Model not found: {local_model}")
        model_ref = _MODEL_FILENAME
    elif args.remote_model_path:
        model_ref = args.remote_model_path
    else:
        env_model = _default_model_path()
        if env_model is not None:
            if not env_model.exists():
                raise FileNotFoundError(
                    f"ASE_DEEPMD_MODEL_PATH points to a missing file: {env_model}"
                )
            local_model = env_model.resolve()
            model_ref = _MODEL_FILENAME
        else:
            raise ValueError(
                "No model specified. Provide --model_path, --remote_model_path, "
                "or set ASE_DEEPMD_MODEL_PATH in .env."
            )

    frames = list(read(str(args.structures), index=":"))
    if args.frames:
        frames = [frames[i] for i in args.frames]

    # One batch directory per prepare_md call — model and runner are copied here once.
    batch_dir = work_dir / _job_id()
    batch_dir.mkdir(parents=True, exist_ok=True)

    head = args.head  # may be cleared below after freezing
    if head and head.lower() == "none":
        head = None
    if local_model is not None:
        if head:
            frozen = _freeze_model(local_model, head, batch_dir / _FROZEN_MODEL_FILENAME)
            shutil.copy2(str(frozen), str(batch_dir / _MODEL_FILENAME))
            head = None  # frozen model is single-task, no head needed at runtime
        else:
            shutil.copy2(str(local_model), str(batch_dir / _MODEL_FILENAME))
        model_ref = f"../{_MODEL_FILENAME}"  # relative from job_dir to batch_dir
    shutil.copy2(str(_SCRIPT_DIR / "run_ase_job.py"), str(batch_dir / "run_ase_job.py"))

    calc_dirs: List[str] = []
    for frame_idx, atoms in enumerate(frames):
        job_dir = batch_dir / f"md_{_job_id()}"
        job_dir.mkdir(parents=True, exist_ok=True)

        # Write structure
        struct_file = "structure.extxyz"
        write(str(job_dir / struct_file), atoms, format="extxyz")

        # Assemble ase_input.json
        ase_input = {
            "job_type": "md",
            "structure_file": struct_file,
            "model_path": model_ref,
            "head": head,
            "save_interval_steps": args.save_interval_steps,
            "traj_prefix": args.traj_prefix,
            "seed": args.seed,
            "stages": stages,
            **extra,
        }
        with open(job_dir / "ase_input.json", "w") as fp:
            json.dump(ase_input, fp, indent=2)

        calc_dirs.append(str(job_dir))

    return {
        "status": "success",
        "job_type": "md",
        "batch_dir": str(batch_dir),
        "calc_dir_list": calc_dirs,
        "num_jobs": len(calc_dirs),
    }


# ---------------------------------------------------------------------------
# prepare_relax
# ---------------------------------------------------------------------------

def cmd_prepare_relax(args) -> dict:
    """Create one job directory per structure for BFGS structure optimisation."""
    config = _load_config(args.config)
    work_dir = Path(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    extra = json.loads(args.extra_params) if args.extra_params else {}

    # Resolve model: explicit flag > ASE_DEEPMD_MODEL_PATH env var > remote reference
    local_model: Optional[Path] = None
    if args.model_path:
        local_model = Path(args.model_path).resolve()
        if not local_model.exists():
            raise FileNotFoundError(f"Model not found: {local_model}")
        model_ref = _MODEL_FILENAME
    elif args.remote_model_path:
        model_ref = args.remote_model_path
    else:
        env_model = _default_model_path()
        if env_model is not None:
            if not env_model.exists():
                raise FileNotFoundError(
                    f"ASE_DEEPMD_MODEL_PATH points to a missing file: {env_model}"
                )
            local_model = env_model.resolve()
            model_ref = _MODEL_FILENAME
        else:
            raise ValueError(
                "No model specified. Provide --model_path, --remote_model_path, "
                "or set ASE_DEEPMD_MODEL_PATH in .env."
            )

    frames = list(read(str(args.structures), index=":"))
    if args.frames:
        frames = [frames[i] for i in args.frames]

    # One batch directory per prepare_relax call — model and runner are copied here once.
    batch_dir = work_dir / _job_id()
    batch_dir.mkdir(parents=True, exist_ok=True)

    head = args.head  # may be cleared below after freezing
    if head and head.lower() == "none":
        head = None
    if local_model is not None:
        if head:
            frozen = _freeze_model(local_model, head, batch_dir / _FROZEN_MODEL_FILENAME)
            shutil.copy2(str(frozen), str(batch_dir / _MODEL_FILENAME))
            head = None  # frozen model is single-task, no head needed at runtime
        else:
            shutil.copy2(str(local_model), str(batch_dir / _MODEL_FILENAME))
        model_ref = f"../{_MODEL_FILENAME}"  # relative from job_dir to batch_dir
    shutil.copy2(str(_SCRIPT_DIR / "run_ase_job.py"), str(batch_dir / "run_ase_job.py"))

    calc_dirs: List[str] = []
    for atoms in frames:
        job_dir = batch_dir / f"relax_{_job_id()}"
        job_dir.mkdir(parents=True, exist_ok=True)

        struct_file = "structure.extxyz"
        write(str(job_dir / struct_file), atoms, format="extxyz")

        ase_input = {
            "job_type": "relax",
            "structure_file": struct_file,
            "model_path": model_ref,
            "head": head,
            "force_tolerance": args.force_tolerance,
            "max_iterations": args.max_iterations,
            "relax_cell": args.relax_cell,
            **extra,
        }
        with open(job_dir / "ase_input.json", "w") as fp:
            json.dump(ase_input, fp, indent=2)

        calc_dirs.append(str(job_dir))

    return {
        "status": "success",
        "job_type": "relax",
        "batch_dir": str(batch_dir),
        "calc_dir_list": calc_dirs,
        "num_jobs": len(calc_dirs),
    }


# ---------------------------------------------------------------------------
# collect_md
# ---------------------------------------------------------------------------

def cmd_collect_md(args) -> dict:
    """Concatenate trajectory extxyz files from all completed MD job directories."""
    calc_dirs = [Path(d) for d in args.calc_dirs]
    all_frames = []
    job_summaries = []

    for calc_dir in calc_dirs:
        status_file = calc_dir / "status.json"
        if not status_file.exists():
            job_summaries.append({
                "calc_dir": str(calc_dir),
                "status": "missing",
                "message": "status.json not found",
            })
            continue

        with open(status_file) as fp:
            status = json.load(fp)

        traj_dir = calc_dir / "trajectories"
        traj_files = sorted(traj_dir.glob("*.extxyz")) if traj_dir.exists() else []
        frames_count = 0
        for traj_file in traj_files:
            try:
                frames = list(read(str(traj_file), index=":"))
                # Tag each frame with source info
                for frame in frames:
                    frame.info["source_dir"] = str(calc_dir)
                    frame.info["source_traj"] = traj_file.name
                all_frames.extend(frames)
                frames_count += len(frames)
            except Exception as exc:
                job_summaries.append({
                    "calc_dir": str(calc_dir),
                    "traj_file": str(traj_file),
                    "status": "read_error",
                    "message": str(exc),
                })

        job_summaries.append({
            "calc_dir": str(calc_dir),
            "status": status.get("status", "unknown"),
            "trajectory_files": [str(f) for f in traj_files],
            "frames_collected": frames_count,
        })

    output_path = None
    if all_frames:
        output_dir = Path(args.output_dir) if args.output_dir else calc_dirs[0].parent
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"md_collected_{_job_id()}.extxyz")
        write(output_path, all_frames, format="extxyz")

    return {
        "status": "success",
        "total_frames": len(all_frames),
        "output_file": output_path,
        "jobs": job_summaries,
    }


# ---------------------------------------------------------------------------
# collect_relax
# ---------------------------------------------------------------------------

def cmd_collect_relax(args) -> dict:
    """Concatenate optimised structures from completed relax job directories."""
    calc_dirs = [Path(d) for d in args.calc_dirs]
    all_frames = []
    job_summaries = []

    for calc_dir in calc_dirs:
        status_file = calc_dir / "status.json"
        if not status_file.exists():
            job_summaries.append({
                "calc_dir": str(calc_dir),
                "status": "missing",
                "message": "status.json not found",
            })
            continue

        with open(status_file) as fp:
            status = json.load(fp)

        if status.get("status") != "success":
            job_summaries.append({
                "calc_dir": str(calc_dir),
                "status": status.get("status", "unknown"),
                "message": status.get("message", ""),
            })
            continue

        # Find the optimised CIF/extxyz output
        optimised_file = status.get("optimized_structure", "")
        if optimised_file:
            opt_path = (
                Path(optimised_file)
                if Path(optimised_file).is_absolute()
                else calc_dir / optimised_file
            )
            try:
                atoms = read(str(opt_path), index=0)
                atoms.info["source_dir"] = str(calc_dir)
                atoms.info["final_energy_eV"] = status.get("final_energy")
                all_frames.append(atoms)
                job_summaries.append({
                    "calc_dir": str(calc_dir),
                    "status": "success",
                    "final_energy_eV": status.get("final_energy"),
                    "optimized_structure": str(opt_path),
                })
            except Exception as exc:
                job_summaries.append({
                    "calc_dir": str(calc_dir),
                    "status": "read_error",
                    "message": str(exc),
                })
        else:
            job_summaries.append({
                "calc_dir": str(calc_dir),
                "status": "no_output",
                "message": "No optimized_structure recorded in status.json",
            })

    output_path = None
    if all_frames:
        output_dir = Path(args.output_dir) if args.output_dir else calc_dirs[0].parent
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"relax_collected_{_job_id()}.extxyz")
        write(output_path, all_frames, format="extxyz")

    return {
        "status": "success",
        "total_structures": len(all_frames),
        "output_file": output_path,
        "jobs": job_summaries,
    }


# ---------------------------------------------------------------------------
# show_model_path
# ---------------------------------------------------------------------------

def cmd_show_model_path(args) -> dict:
    """Return the resolved default model path from the ASE_DEEPMD_MODEL_PATH env var."""
    model_path = _default_model_path()
    if model_path is None:
        return {
            "status": "not_set",
            "model_path": None,
            "message": "ASE_DEEPMD_MODEL_PATH is not set in the environment or .env file.",
        }
    return {
        "status": "ok",
        "model_path": str(model_path),
        "exists": model_path.exists(),
    }


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------

def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--config", type=Path, default=_DEFAULT_CONFIG,
        help=f"Path to config.yaml (default: {_DEFAULT_CONFIG}).",
    )


def _add_model_args(p: argparse.ArgumentParser) -> None:
    grp = p.add_mutually_exclusive_group(required=False)
    grp.add_argument(
        "--model_path", type=str, default=None,
        help=(
            "Local path to the DeePMD model (.pt).  Copied into every job dir.  "
            "Falls back to ASE_DEEPMD_MODEL_PATH from .env when omitted."
        ),
    )
    grp.add_argument(
        "--remote_model_path", type=str, default=None,
        help="Absolute path to the model on the remote node.  Not transferred.",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare ASE/DeePMD job directories and collect results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── prepare_md ────────────────────────────────────────────────────────────
    p = sub.add_parser("prepare_md", help="Prepare MD job directories.")
    _add_common_args(p)
    _add_model_args(p)
    p.add_argument(
        "--structures", required=True,
        help="Path to multi-frame structure file (extxyz, POSCAR, CIF, …).",
    )
    p.add_argument(
        "--stages", required=True,
        help=(
            "JSON list of stage dicts, e.g. "
            "'[{\"mode\":\"NVT\",\"temperature_K\":300,\"runtime_ps\":1.0}]'."
        ),
    )
    p.add_argument(
        "--frames", type=int, nargs="+", default=None,
        help="Frame indices to include (default: all).",
    )
    p.add_argument("--head", type=str, default="Omat24",
                   help="Multi-task model head to freeze (default: Omat24). "
                        "Pass 'none' to skip freezing and use the model as-is.")
    p.add_argument("--save_interval_steps", type=int, default=100,
                   help="Write trajectory every N steps (default: 100).")
    p.add_argument("--traj_prefix", type=str, default="traj",
                   help="Prefix for trajectory filenames (default: traj).")
    p.add_argument("--seed", type=int, default=42,
                   help="Random seed for velocity initialisation (default: 42).")
    p.add_argument(
        "--extra_params", type=str, default=None,
        help="JSON dict of additional keys merged into ase_input.json.",
    )
    p.set_defaults(func=cmd_prepare_md)

    # ── prepare_relax ─────────────────────────────────────────────────────────
    p = sub.add_parser("prepare_relax", help="Prepare structure optimisation job directories.")
    _add_common_args(p)
    _add_model_args(p)
    p.add_argument(
        "--structures", required=True,
        help="Path to multi-frame structure file.",
    )
    p.add_argument(
        "--frames", type=int, nargs="+", default=None,
        help="Frame indices to include (default: all).",
    )
    p.add_argument("--head", type=str, default="Omat24",
                   help="Multi-task model head to freeze (default: Omat24). "
                        "Pass 'none' to skip freezing and use the model as-is.")
    p.add_argument("--force_tolerance", type=float, default=0.01,
                   help="Force convergence threshold in eV/Å (default: 0.01).")
    p.add_argument("--max_iterations", type=int, default=200,
                   help="Maximum BFGS steps (default: 200).")
    p.add_argument("--relax_cell", action="store_true", default=False,
                   help="Also relax the unit cell (ExpCellFilter).")
    p.add_argument(
        "--extra_params", type=str, default=None,
        help="JSON dict of additional keys merged into ase_input.json.",
    )
    p.set_defaults(func=cmd_prepare_relax)

    # ── collect_md ────────────────────────────────────────────────────────────
    p = sub.add_parser("collect_md",
                       help="Collect trajectory frames from completed MD jobs.")
    p.add_argument(
        "--calc_dirs", nargs="+", required=True,
        help="Paths to MD job directories (containing trajectories/ and status.json).",
    )
    p.add_argument(
        "--output_dir", type=str, default=None,
        help="Directory to write the merged extxyz (default: parent of first calc_dir).",
    )
    p.set_defaults(func=cmd_collect_md)

    # ── collect_relax ─────────────────────────────────────────────────────────
    p = sub.add_parser("collect_relax",
                       help="Collect optimised structures from completed relax jobs.")
    p.add_argument(
        "--calc_dirs", nargs="+", required=True,
        help="Paths to relax job directories (containing status.json).",
    )
    p.add_argument(
        "--output_dir", type=str, default=None,
        help="Directory to write the merged extxyz (default: parent of first calc_dir).",
    )
    p.set_defaults(func=cmd_collect_relax)

    # ── show_model_path ───────────────────────────────────────────────────────
    p = sub.add_parser(
        "show_model_path",
        help="Show the default DeePMD model path (from ASE_DEEPMD_MODEL_PATH).",
    )
    p.set_defaults(func=cmd_show_model_path)

    args = parser.parse_args()
    _load_env(_DEFAULT_CONFIG)

    try:
        result = args.func(args)
        print(json.dumps(result, indent=2, default=str))
        sys.exit(0)
    except Exception as exc:
        print(
            json.dumps({"status": "error", "message": str(exc),
                        "traceback": traceback.format_exc()}),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
