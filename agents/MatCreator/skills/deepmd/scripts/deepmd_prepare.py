#!/usr/bin/env python3
"""deepmd_prepare.py — Preparation-phase script for DeePMD-kit training jobs.

Converts raw structure data (xyz / extxyz / POSCAR / …) into deepmd/npy format
and writes an input.json ready for ``dp train``.

Sub-commands
------------
  prepare-training            Train a new DP model from scratch (se_atten_v2 descriptor)
  prepare-finetune            Single-task finetune of a pretrained DPA model
  prepare-finetune-multitask  Multi-task finetune of a pretrained DPA model

After running any sub-command the ``--workdir`` directory contains:

  input.json                  Training configuration consumed by ``dp [--pt] train``
  train_data/                 deepmd/npy training split
  valid_data/                 deepmd/npy validation split (when split_ratio > 0)
  <model_name>.pt             Symlink (or copy) to the base model (finetune only)

Execution (local)
-----------------
  cd <workdir>

  # From-scratch:
  dp --pt train input.json
  dp --pt freeze -o frozen_model.pb        # TF export, optional

  # Finetune (single-task):
  dp --pt train input.json \\
      --finetune <model_name>.pt --use-pretrain-script \\
      [--model-branch <head>]

  # Finetune (multi-task):
  dp --pt train input.json \\
      --finetune <model_name>.pt --use-pretrain-script

Execution (remote — via bohr skill)
------------------------------------
  See deepmd.md for the bohrium_submit.py invocation.

Data conversion for dp test
----------------------------
  python deepmd_prepare.py convert-data \\
      --data  test.extxyz            \\
      --outdir <out_dir>             \\
      [--mixed_type]                 \\
      [--head <head_name>]           \\
      [--nframes 100]

  # Then run dp test on each system dir printed in the JSON output:
  dp --pt test -m model.ckpt.pt -s <system_dir> [-n <nframes>] [--head <head>]
"""

import argparse
import glob
import json
import logging
import random
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from ase.atoms import Atoms
from ase.io import read
import dpdata

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full periodic-table element list — used as universal type_map
# ---------------------------------------------------------------------------
ALL_TYPES: List[str] = [
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni",
    "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr",
    "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd",
    "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe",
    "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd",
    "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
    "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn",
    "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm",
    "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr",
    "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn",
    "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
]

# ---------------------------------------------------------------------------
# Configuration templates
# ---------------------------------------------------------------------------
_DP_TEMPLATE: Dict[str, Any] = {
    "model": {
        "descriptor": {
            "type": "se_atten_v2",
            "sel": "auto",
            "resnet_dt": False,
            "axis_neuron": 12,
            "attn": 128,
            "attn_layer": 0,
            "attn_dotr": True,
            "seed": 1111,
        },
        "fitting_net": {"seed": 1111},
    },
    "learning_rate": {},
    "loss": {},
    "training": {
        "training_data": {
            "systems": [],
            "batch_size": "auto",
            "auto_prob": "prob_sys_size",
        },
        "numb_steps": 100,
        "warmup_steps": 0,
        "gradient_max_norm": 5.0,
        "seed": 2912457061,
        "disp_file": "lcurve.out",
        "disp_freq": 100,
        "save_freq": 2000,
    },
}

_DPA_TEMPLATE: Dict[str, Any] = {
    "model": {},
    "learning_rate": {
        "type": "exp",
        "decay_steps": 10,
        "start_lr": 0.001,
        "stop_lr": 3.51e-08,
    },
    "loss": {
        "type": "ener",
        "start_pref_e": 0.02,
        "limit_pref_e": 1,
        "start_pref_f": 1000,
        "limit_pref_f": 1,
        "start_pref_v": 0,
        "limit_pref_v": 0,
    },
    "training": {
        "training_data": {
            "systems": [],
            "batch_size": "auto",
            "auto_prob": "prob_sys_size",
        },
        "numb_steps": 100,
        "warmup_steps": 0,
        "gradient_max_norm": 5.0,
        "seed": 2912457061,
        "disp_file": "lcurve.out",
        "disp_freq": 100,
        "save_freq": 2000,
    },
}

_MULTITASK_TEMPLATE: Dict[str, Any] = {
    "model": {
        "shared_dict": {
            "dpa2_descriptor": {
                "type": "dpa2",
                "repinit": {
                    "tebd_dim": 8,
                    "rcut": 6.0,
                    "rcut_smth": 0.5,
                    "nsel": 120,
                    "neuron": [25, 50, 100],
                    "axis_neuron": 12,
                    "activation_function": "tanh",
                    "three_body_sel": 40,
                    "three_body_rcut": 4.0,
                    "three_body_rcut_smth": 3.5,
                    "use_three_body": True,
                },
                "repformer": {
                    "rcut": 4.0,
                    "rcut_smth": 3.5,
                    "nsel": 40,
                    "nlayers": 6,
                    "g1_dim": 128,
                    "g2_dim": 32,
                    "attn2_hidden": 32,
                    "attn2_nhead": 4,
                    "attn1_hidden": 128,
                    "attn1_nhead": 4,
                    "axis_neuron": 4,
                    "update_h2": False,
                    "update_g1_has_conv": True,
                    "update_g1_has_grrg": True,
                    "update_g1_has_drrd": True,
                    "update_g1_has_attn": False,
                    "update_g2_has_g1g1": False,
                    "update_g2_has_attn": True,
                    "update_style": "res_residual",
                    "update_residual": 0.01,
                    "update_residual_init": "norm",
                    "attn2_has_gate": True,
                    "use_sqrt_nnei": True,
                    "g1_out_conv": True,
                    "g1_out_mlp": True,
                },
                "add_tebd_to_repinit_out": False,
                "concat_output_tebd": True,
                "precision": "default",
                "smooth": True,
            },
            "type_map_all": ALL_TYPES,
        },
        "model_dict": {},
    },
    "learning_rate": {
        "type": "exp",
        "decay_steps": 10,
        "start_lr": 0.001,
        "stop_lr": 3.51e-08,
    },
    "loss_dict": {},
    "training": {
        "model_prob": {},
        "data_dict": {},
        "numb_steps": 100,
        "warmup_steps": 0,
        "gradient_max_norm": 5.0,
        "seed": 2912457061,
        "disp_file": "lcurve.out",
        "disp_freq": 100,
        "save_freq": 2000,
    },
}


# ---------------------------------------------------------------------------
# Data utilities
# ---------------------------------------------------------------------------

def _load_atoms(paths: List[Path]) -> List[Atoms]:
    frames: List[Atoms] = []
    for p in paths:
        frames.extend(read(str(p), index=":"))
    logger.info("Loaded %d frames from %d file(s)", len(frames), len(paths))
    return frames


def _split(
    atoms: List[Atoms],
    ratio: float,
    shuffle: bool,
    seed: Optional[int],
) -> Tuple[List[Atoms], Optional[List[Atoms]]]:
    if ratio <= 0 or len(atoms) <= 1:
        return atoms, None
    ratio = max(0.0, min(1.0, ratio))
    n_valid = min(int(round(len(atoms) * ratio)), len(atoms) - 1)
    if n_valid == 0:
        return atoms, None
    indices = list(range(len(atoms)))
    if shuffle:
        random.Random(seed).shuffle(indices)
    valid_idx = set(indices[:n_valid])
    train = [atoms[i] for i in indices if i not in valid_idx]
    valid = [atoms[i] for i in sorted(valid_idx)]
    logger.info("Split → %d train / %d valid", len(train), len(valid))
    return train, valid


def _ase_to_labeled(atoms: Atoms) -> dpdata.LabeledSystem:
    symbols = atoms.get_chemical_symbols()
    names = list(dict.fromkeys(symbols))
    numbs = [symbols.count(n) for n in names]
    types = np.array([names.index(s) for s in symbols], dtype=int)
    data: Dict[str, Any] = {
        "atom_names": names,
        "atom_numbs": numbs,
        "atom_types": types,
        "cells": np.array([atoms.cell.array]),
        "coords": np.array([atoms.get_positions()]),
        "orig": np.zeros(3),
        "nopbc": not np.any(atoms.get_pbc()),
        "energies": np.array([atoms.get_potential_energy()]),
        "forces": np.array([atoms.get_forces()]),
    }
    if "virial" in atoms.arrays:
        data["virial"] = np.array([atoms.arrays["virial"]])
    return dpdata.LabeledSystem.from_dict({"data": data})


def _export(atoms: List[Atoms], out_dir: Path, mixed_type: bool) -> List[Path]:
    if not atoms:
        raise ValueError("No structures to export to deepmd/npy.")
    out_dir.mkdir(parents=True, exist_ok=True)
    ms = dpdata.MultiSystems()
    for a in atoms:
        ms.append(_ase_to_labeled(a))
    fmt = "deepmd/npy/mixed" if mixed_type else "deepmd/npy"
    ms.to(fmt, str(out_dir))
    paths = [
        Path(p).parent
        for p in glob.glob(str(out_dir) + "/**/type.raw", recursive=True)
    ]
    logger.info("Exported %d system(s) → %s", len(paths), out_dir)
    return paths


def _rand32() -> int:
    return random.randrange(2**32)


def _randomise_seeds(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg = json.loads(json.dumps(cfg))
    mdl = cfg.get("model", {})
    if "model_dict" in mdl:
        for v in mdl["model_dict"].values():
            v["fitting_net"]["seed"] = _rand32()
    else:
        desc = mdl.get("descriptor", {})
        if desc.get("type") not in ("dpa1", "dpa2"):
            desc["seed"] = _rand32()
        if "fitting_net" in mdl:
            mdl["fitting_net"]["seed"] = _rand32()
    cfg["training"]["seed"] = _rand32()
    return cfg


def _place_model(base_model: Path, workdir: Path, copy: bool) -> Path:
    src = base_model.expanduser().resolve()
    dest = workdir / src.name
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    if copy:
        shutil.copy2(src, dest)
        logger.info("Copied base model → %s", dest)
    else:
        dest.symlink_to(src)
        logger.info("Symlinked base model → %s", dest)
    return dest


def _apply_lr(cfg: Dict[str, Any], args) -> None:
    cfg["learning_rate"]["type"] = args.lr_type
    cfg["learning_rate"]["decay_steps"] = args.decay_steps
    cfg["learning_rate"]["start_lr"] = args.start_lr
    cfg["learning_rate"]["stop_lr"] = args.stop_lr


def _apply_loss(cfg: Dict[str, Any], section: str, args) -> None:
    cfg[section]["type"] = args.loss_type
    cfg[section]["start_pref_e"] = args.start_pref_e
    cfg[section]["limit_pref_e"] = args.limit_pref_e
    cfg[section]["start_pref_f"] = args.start_pref_f
    cfg[section]["limit_pref_f"] = args.limit_pref_f
    cfg[section]["start_pref_v"] = args.start_pref_v
    cfg[section]["limit_pref_v"] = args.limit_pref_v


def _set_data(
    cfg: Dict[str, Any],
    train_paths: List[Path],
    valid_paths: Optional[List[Path]],
    workdir: Path,
) -> None:
    cfg["training"]["training_data"]["systems"] = [
        str(p.relative_to(workdir)) for p in train_paths
    ]
    cfg["training"]["training_data"]["batch_size"] = "auto"
    cfg["training"]["training_data"]["auto_prob"] = "prob_sys_size"
    if valid_paths:
        cfg["training"]["validation_data"] = {
            "systems": [str(p.relative_to(workdir)) for p in valid_paths],
            "batch_size": 1,
        }
    else:
        cfg["training"].pop("validation_data", None)


# ---------------------------------------------------------------------------
# Sub-command implementations
# ---------------------------------------------------------------------------

def cmd_prepare_training(args) -> None:
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    atoms = _load_atoms([Path(p) for p in args.train_data])
    train_atoms, valid_atoms = _split(atoms, args.split_ratio, not args.no_shuffle, args.seed)

    train_paths = _export(train_atoms, workdir / "train_data", args.mixed_type)
    valid_paths = (
        _export(valid_atoms, workdir / "valid_data", args.mixed_type)
        if valid_atoms else None
    )

    cfg = _randomise_seeds(_DP_TEMPLATE)
    cfg["training"]["numb_steps"] = args.numb_steps
    _apply_lr(cfg, args)
    _apply_loss(cfg, "loss", args)
    cfg["model"]["descriptor"]["rcut"] = args.rcut
    cfg["model"]["descriptor"]["rcut_smth"] = args.rcut_smth
    cfg["model"]["descriptor"]["neuron"] = list(args.descriptor_neuron)
    cfg["model"]["fitting_net"]["neuron"] = list(args.neuron)
    cfg["model"]["fitting_net"]["resnet_dt"] = args.resnet_dt
    cfg["model"]["type_map"] = args.type_map if args.type_map else ALL_TYPES
    _set_data(cfg, train_paths, valid_paths, workdir)

    _write_input(workdir, cfg)

    dp_flag = "--pt " if args.impl == "pytorch" else ""
    exec_cmd = f"dp {dp_flag}train input.json"
    _print_result(workdir, "dp-training", exec_cmd, args.numb_steps)


def cmd_prepare_finetune(args) -> None:
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    atoms = _load_atoms([Path(p) for p in args.train_data])
    train_atoms, valid_atoms = _split(atoms, args.split_ratio, not args.no_shuffle, args.seed)

    train_paths = _export(train_atoms, workdir / "train_data", args.mixed_type)
    valid_paths = (
        _export(valid_atoms, workdir / "valid_data", args.mixed_type)
        if valid_atoms else None
    )

    cfg = json.loads(json.dumps(_DPA_TEMPLATE))
    cfg["training"]["numb_steps"] = args.numb_steps
    _apply_lr(cfg, args)
    _apply_loss(cfg, "loss", args)
    cfg["model"]["type_map"] = args.type_map if args.type_map else ALL_TYPES
    _set_data(cfg, train_paths, valid_paths, workdir)

    model_dest = _place_model(Path(args.base_model), workdir, args.copy_model)

    _write_input(workdir, cfg)

    exec_cmd = (
        f"dp --pt train input.json --finetune {model_dest.name} --use-pretrain-script"
    )
    head = args.head
    if head and head.lower() != "none":
        exec_cmd += f" --model-branch {head}"
    _print_result(workdir, "dpa-finetune", exec_cmd, args.numb_steps)


def cmd_prepare_finetune_multitask(args) -> None:
    workdir = Path(args.workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)

    # Parse task specs: "task_name:file1,file2,..."
    task_data: Dict[str, List[Path]] = {}
    for spec in args.task_data:
        if ":" not in spec:
            logger.error("Invalid task spec (expected 'name:file1,file2'): %s", spec)
            sys.exit(1)
        name, files_str = spec.split(":", 1)
        task_data[name] = [Path(f) for f in files_str.split(",") if f]

    cfg = json.loads(json.dumps(_MULTITASK_TEMPLATE))
    cfg["training"]["numb_steps"] = args.numb_steps
    _apply_lr(cfg, args)

    for task_name, task_files in task_data.items():
        atoms = _load_atoms(task_files)
        train_atoms, valid_atoms = _split(
            atoms, args.split_ratio, not args.no_shuffle, args.seed
        )

        train_paths = _export(
            train_atoms, workdir / f"train_data_{task_name}", args.mixed_type
        )
        valid_paths = (
            _export(valid_atoms, workdir / f"valid_data_{task_name}", args.mixed_type)
            if valid_atoms else None
        )

        cfg["model"]["model_dict"][task_name] = {
            "type_map": "type_map_all",
            "descriptor": "dpa2_descriptor",
            "fitting_net": {
                "neuron": list(args.neuron),
                "resnet_dt": args.resnet_dt,
                "seed": _rand32(),
            },
        }
        cfg["loss_dict"][task_name] = {
            "type": args.loss_type,
            "start_pref_e": args.start_pref_e,
            "limit_pref_e": args.limit_pref_e,
            "start_pref_f": args.start_pref_f,
            "limit_pref_f": args.limit_pref_f,
            "start_pref_v": args.start_pref_v,
            "limit_pref_v": args.limit_pref_v,
        }
        cfg["training"]["model_prob"][task_name] = args.model_prob
        cfg["training"]["data_dict"][task_name] = {
            "training_data": {
                "systems": [str(p.relative_to(workdir)) for p in train_paths],
                "batch_size": "auto",
                "auto_prob": "prob_sys_size",
            }
        }
        if valid_paths:
            cfg["training"]["data_dict"][task_name]["validation_data"] = {
                "systems": [str(p.relative_to(workdir)) for p in valid_paths],
                "batch_size": 1,
            }

    model_dest = _place_model(Path(args.base_model), workdir, args.copy_model)

    _write_input(workdir, cfg)

    exec_cmd = (
        f"dp --pt train input.json --finetune {model_dest.name} --use-pretrain-script"
    )
    _print_result(workdir, "dpa-finetune-multitask", exec_cmd, args.numb_steps)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _write_input(workdir: Path, cfg: Dict[str, Any]) -> None:
    path = workdir / "input.json"
    with open(path, "w") as f:
        json.dump(cfg, f, indent=4)
    logger.info("Wrote %s", path)


def _print_result(
    workdir: Path, mode: str, exec_cmd: str, numb_steps: int
) -> None:
    result = {
        "status": "prepared",
        "workdir": str(workdir),
        "mode": mode,
        "input_json": str(workdir / "input.json"),
        "numb_steps": numb_steps,
        "execution_command": exec_cmd,
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# convert-data sub-command
# ---------------------------------------------------------------------------

def cmd_convert_data(args) -> None:
    """Convert ASE-readable frames to deepmd/npy for use with ``dp test``."""
    outdir = Path(args.outdir).resolve()
    atoms = _load_atoms([Path(p) for p in args.data])
    if not atoms:
        logger.error("No frames loaded from provided files.")
        sys.exit(1)

    system_paths = _export(atoms, outdir, args.mixed_type)

    test_cmds = []
    for sp in system_paths:
        cmd = f"dp --pt test -m <model.ckpt.pt> -s {sp}"
        if args.head and args.head.lower() != "none":
            cmd += f" --head {args.head}"
        if args.nframes:
            cmd += f" -n {args.nframes}"
        test_cmds.append(cmd)

    result = {
        "status": "converted",
        "outdir": str(outdir),
        "num_frames": len(atoms),
        "system_dirs": [str(p) for p in system_paths],
        "dp_test_commands": test_cmds,
    }
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Argument parsers
# ---------------------------------------------------------------------------

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--workdir", required=True, metavar="DIR",
        help="Output working directory (created if needed)",
    )
    p.add_argument(
        "--numb_steps", type=int, default=1000, metavar="N",
        help="Total training steps (default: 1000)",
    )
    p.add_argument("--lr_type", default="exp",
                   help="Learning rate scheduler type (default: exp)")
    p.add_argument("--decay_steps", type=int, default=100, metavar="N",
                   help="LR decay interval in steps (default: 100)")
    p.add_argument("--start_lr", type=float, default=0.001,
                   help="Starting learning rate (default: 0.001)")
    p.add_argument("--stop_lr", type=float, default=3.51e-8,
                   help="Stopping learning rate (default: 3.51e-8)")
    p.add_argument("--loss_type", default="ener",
                   help="Loss function type (default: ener)")
    p.add_argument("--start_pref_e", type=float, default=0.02)
    p.add_argument("--limit_pref_e", type=float, default=1.0)
    p.add_argument("--start_pref_f", type=float, default=1000.0)
    p.add_argument("--limit_pref_f", type=float, default=1.0)
    p.add_argument("--start_pref_v", type=float, default=0.0)
    p.add_argument("--limit_pref_v", type=float, default=0.0)
    p.add_argument(
        "--split_ratio", type=float, default=0.1, metavar="F",
        help="Validation split fraction 0–1 (default: 0.1; 0 = no split)",
    )
    p.add_argument(
        "--no_shuffle", action="store_true",
        help="Disable shuffling before train/valid split",
    )
    p.add_argument("--seed", type=int, default=None, metavar="N",
                   help="Random seed for reproducible data splitting")
    p.add_argument("--mixed_type", action="store_true",
                   help="Export data in deepmd/npy/mixed format")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepmd_prepare.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # ── prepare-training ────────────────────────────────────────────
    pt = sub.add_parser(
        "prepare-training",
        help="Prepare workdir for training a DP model from scratch",
    )
    pt.add_argument(
        "--train_data", nargs="+", required=True, metavar="FILE",
        help="Structure files readable by ASE (xyz, extxyz, POSCAR, …)",
    )
    pt.add_argument(
        "--type_map", nargs="+", default=None, metavar="ELEMENT",
        help="Element type map (default: full periodic table)",
    )
    pt.add_argument(
        "--impl", default="pytorch", choices=["pytorch", "tensorflow"],
        help="Backend (default: pytorch)",
    )
    pt.add_argument("--rcut", type=float, default=8.0,
                    help="Cutoff radius in Å (default: 8.0)")
    pt.add_argument("--rcut_smth", type=float, default=0.5,
                    help="Smooth cutoff start in Å (default: 0.5)")
    pt.add_argument(
        "--descriptor_neuron", type=int, nargs="+", default=[25, 50, 100],
        metavar="N",
        help="Neurons per descriptor layer (default: 25 50 100)",
    )
    pt.add_argument(
        "--neuron", type=int, nargs="+", default=[240, 240, 240], metavar="N",
        help="Neurons per fitting-net layer (default: 240 240 240)",
    )
    pt.add_argument("--resnet_dt", action="store_true",
                    help="Enable ResNet dt in fitting network")
    _add_common(pt)
    pt.set_defaults(func=cmd_prepare_training)

    # ── prepare-finetune ────────────────────────────────────────────
    pf = sub.add_parser(
        "prepare-finetune",
        help="Prepare workdir for single-task DPA finetuning",
    )
    pf.add_argument(
        "--train_data", nargs="+", required=True, metavar="FILE",
        help="Structure files readable by ASE",
    )
    pf.add_argument(
        "--base_model", required=True, metavar="PATH",
        help="Pretrained DPA model file (.pt)",
    )
    pf.add_argument(
        "--head", default="Omat24", metavar="NAME",
        help="Model branch/head to initialise from (default: Omat24). "
             "Pass 'none' to reinitialise the fitting net.",
    )
    pf.add_argument(
        "--type_map", nargs="+", default=None, metavar="ELEMENT",
        help="Element type map (default: full periodic table)",
    )
    pf.add_argument(
        "--copy_model", action="store_true",
        help="Copy (not symlink) the base model into workdir — required for remote submission",
    )
    _add_common(pf)
    pf.set_defaults(func=cmd_prepare_finetune)

    # ── prepare-finetune-multitask ──────────────────────────────────
    pm = sub.add_parser(
        "prepare-finetune-multitask",
        help="Prepare workdir for multi-task DPA finetuning",
    )
    pm.add_argument(
        "--task_data", nargs="+", required=True, metavar="TASK:FILE1,FILE2",
        help=(
            "Task data specs, one entry per task: 'task_name:file1.xyz,file2.xyz'. "
            "Repeat for each task."
        ),
    )
    pm.add_argument(
        "--base_model", required=True, metavar="PATH",
        help="Pretrained DPA multi-task model file (.pt)",
    )
    pm.add_argument(
        "--neuron", type=int, nargs="+", default=[240, 240, 240], metavar="N",
        help="Neurons per fitting-net layer for all tasks (default: 240 240 240)",
    )
    pm.add_argument("--resnet_dt", action="store_true",
                    help="Enable ResNet dt in all fitting networks")
    pm.add_argument(
        "--model_prob", type=float, default=1.0,
        help="Task sampling probability applied equally to all tasks (default: 1.0)",
    )
    pm.add_argument(
        "--copy_model", action="store_true",
        help="Copy (not symlink) the base model into workdir — required for remote submission",
    )
    _add_common(pm)
    pm.set_defaults(func=cmd_prepare_finetune_multitask)

    # ── convert-data ────────────────────────────────────────────────
    cd = sub.add_parser(
        "convert-data",
        help="Convert ASE-readable structure files to deepmd/npy for dp test",
    )
    cd.add_argument(
        "--data", nargs="+", required=True, metavar="FILE",
        help="Structure files readable by ASE (xyz, extxyz, POSCAR, …)",
    )
    cd.add_argument(
        "--outdir", required=True, metavar="DIR",
        help="Output directory for deepmd/npy system directories",
    )
    cd.add_argument(
        "--mixed_type", action="store_true",
        help="Export in deepmd/npy/mixed format (allows variable composition)",
    )
    cd.add_argument(
        "--head", default="Omat24", metavar="NAME",
        help="Model head to embed in the printed dp test command (default: Omat24)",
    )
    cd.add_argument(
        "--nframes", type=int, default=None, metavar="N",
        help="Number of frames to test; embedded in the printed dp test command (optional)",
    )
    cd.set_defaults(func=cmd_convert_data)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
