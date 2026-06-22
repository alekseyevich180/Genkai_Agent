#!/usr/bin/env python3
"""
Active learning structure filtering via entropy-based diversity selection.

Selects a maximally diverse subset of candidate structures from a pool using
the QUEST entropy-based descriptor. Tries GPU (CUDA) first; falls back to CPU.

All commands print a JSON object to stdout and exit 0 on success, 1 on error.

Usage:
  python active_learning.py filter-by-entropy <iter_confs> [options]

Commands:
  filter-by-entropy    Select a diverse subset of structures via entropy-based filtering.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Union

import numpy as np
from ase.atoms import Atoms
from ase.io import read, write

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _generate_work_path(create: bool = True) -> str:
    calling_function = traceback.extract_stack(limit=2)[-2].name
    current_time = time.strftime("%Y%m%d%H%M%S")
    random_string = str(uuid.uuid4())[:8]
    work_path = f"{current_time}.{calling_function}.{random_string}"
    if create:
        os.makedirs(work_path, exist_ok=True)
    return work_path


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

def _h_filter_cpu(
    iter_confs: List[Atoms],
    dset_confs: List[Atoms],
    chunk_size: int,
    max_sel: int,
    k: int,
    cutoff: float,
    batch_size: int,
    h: float,
    dtype: str,
):
    from quests.descriptor import get_descriptors
    from quests.entropy import delta_entropy, entropy

    num_ref = len(dset_confs)
    if len(dset_confs) == 0:
        if chunk_size >= len(iter_confs):
            return iter_confs, {"num_confs": len(iter_confs)}
        random.shuffle(iter_confs)
        dset_confs = iter_confs[:chunk_size]
        iter_confs = iter_confs[chunk_size:]
        num_ref = 0
        max_sel -= chunk_size

    max_iter = min(
        max_sel // chunk_size + (max_sel % chunk_size > 0),
        len(iter_confs) // chunk_size + (len(iter_confs) % chunk_size > 0),
    )
    iter_desc = get_descriptors(iter_confs, k=k, cutoff=cutoff, dtype=dtype)
    dset_desc = get_descriptors(dset_confs, k=k, cutoff=cutoff, dtype=dtype)

    atom_indices_iter: List[tuple] = []
    start = 0
    for n in [a.get_number_of_atoms() for a in iter_confs]:
        end = start + n
        atom_indices_iter.append((start, end))
        start = end

    H = entropy(dset_desc, h=h, batch_size=batch_size)
    H_list = [H]
    result: Dict[str, Any] = {"iter_00": H, "num_confs": len(dset_confs)}
    indices: List[int] = []

    for ii in range(max_iter):
        re_indices = [i for i in range(len(iter_confs)) if i not in indices]
        re_confs = [iter_confs[i] for i in re_indices]
        re_desc = [
            iter_desc[atom_indices_iter[i][0]: atom_indices_iter[i][1]]
            for i in re_indices
        ]
        x = np.vstack(re_desc)
        delta = delta_entropy(x, dset_desc, h=h, batch_size=batch_size)

        re_natoms = [a.get_number_of_atoms() for a in re_confs]
        atom_indices: List[tuple] = []
        s = 0
        for n in re_natoms:
            atom_indices.append((s, s + n))
            s += n
        delta_sums = [delta[s:e].sum() for s, e in atom_indices]
        sorted_re = [
            idx for idx, _ in sorted(
                zip(re_indices, delta_sums), key=lambda x: x[1], reverse=True
            )
        ]
        selected = sorted_re[:chunk_size]

        dset_desc_ls = [dset_desc]
        for idx in selected:
            indices.append(idx)
            dset_confs.append(iter_confs[idx])
            dset_desc_ls.append(iter_desc[atom_indices_iter[idx][0]: atom_indices_iter[idx][1]])
        dset_desc = np.vstack(dset_desc_ls)
        H = entropy(dset_desc, h=h, batch_size=batch_size)
        dH = H - H_list[-1]
        H_list.append(H)
        result.update({f"iter_{ii + 1:02d}": H, "num_confs": len(dset_confs)})
        if dH < 1e-2:
            break

    return dset_confs[num_ref:], result


def _h_filter_gpu(
    iter_confs: List[Atoms],
    dset_confs: List[Atoms],
    chunk_size: int,
    max_sel: int,
    k: int,
    cutoff: float,
    batch_size: int,
    h: float,
    dtype: str,
):
    import torch
    from quests.descriptor import get_descriptors
    from quests.gpu.entropy import delta_entropy, entropy

    device = "cuda" if torch.cuda.is_available() else "cpu"
    num_ref = len(dset_confs)
    if len(dset_confs) == 0:
        if chunk_size >= len(iter_confs):
            return iter_confs, {"num_confs": len(iter_confs)}
        random.shuffle(iter_confs)
        dset_confs = iter_confs[:chunk_size]
        iter_confs = iter_confs[chunk_size:]
        num_ref = 0
        max_sel -= chunk_size

    max_iter = min(
        max_sel // chunk_size + (max_sel % chunk_size > 0),
        len(iter_confs) // chunk_size + (len(iter_confs) % chunk_size > 0),
    )
    iter_desc = get_descriptors(iter_confs, k=k, cutoff=cutoff, dtype=dtype)
    dset_desc = get_descriptors(dset_confs, k=k, cutoff=cutoff, dtype=dtype)

    atom_indices_iter: List[tuple] = []
    start = 0
    for n in [a.get_number_of_atoms() for a in iter_confs]:
        end = start + n
        atom_indices_iter.append((start, end))
        start = end

    x = torch.tensor(dset_desc, device=device, dtype=torch.float32)
    H = float(entropy(x, h=h, batch_size=batch_size, device=device).cpu().numpy())
    H_list = [H]
    result: Dict[str, Any] = {"iter_00": H, "num_confs": len(dset_confs)}
    indices: List[int] = []

    for ii in range(max_iter):
        re_indices = [i for i in range(len(iter_confs)) if i not in indices]
        re_confs = [iter_confs[i] for i in re_indices]
        re_desc = [
            iter_desc[atom_indices_iter[i][0]: atom_indices_iter[i][1]]
            for i in re_indices
        ]
        x = torch.tensor(np.vstack(re_desc), device=device, dtype=torch.float32)
        y = torch.tensor(dset_desc, device=device, dtype=torch.float32)
        delta = delta_entropy(x, y, h=h, batch_size=batch_size, device=device).cpu().numpy()

        re_natoms = [a.get_number_of_atoms() for a in re_confs]
        atom_indices: List[tuple] = []
        s = 0
        for n in re_natoms:
            atom_indices.append((s, s + n))
            s += n
        delta_sums = [delta[s:e].sum() for s, e in atom_indices]
        sorted_re = [
            idx for idx, _ in sorted(
                zip(re_indices, delta_sums), key=lambda x: x[1], reverse=True
            )
        ]
        selected = sorted_re[:chunk_size]

        dset_desc_ls = [dset_desc]
        for idx in selected:
            indices.append(idx)
            dset_confs.append(iter_confs[idx])
            dset_desc_ls.append(iter_desc[atom_indices_iter[idx][0]: atom_indices_iter[idx][1]])
        dset_desc = np.vstack(dset_desc_ls)
        y = torch.tensor(dset_desc, device=device, dtype=torch.float32)
        H = float(entropy(y, h=h, batch_size=batch_size, device=device).cpu().numpy())
        dH = H - H_list[-1]
        H_list.append(H)
        result.update({f"iter_{ii + 1:02d}": H, "num_confs": len(dset_confs)})
        if dH < 1e-2:
            break

    return dset_confs[num_ref:], result


def filter_by_entropy_impl(
    iter_confs: Union[List[Union[Path, str]], Union[Path, str]],
    reference: Union[List[Union[Path, str]], Union[Path, str]] = [],
    chunk_size: int = 10,
    k: int = 32,
    cutoff: float = 5.0,
    batch_size: int = 1000,
    h: float = 0.015,
    max_sel: int = 50,
) -> Dict[str, Any]:
    """Entropy-based subset selection; tries GPU first, falls back to CPU."""
    try:
        if isinstance(iter_confs, list):
            loaded = [read(p, index=":") for p in iter_confs]
            iter_confs_atoms = [a for sub in loaded for a in (sub if isinstance(sub, list) else [sub])]
        else:
            raw = read(str(iter_confs), index=":")
            iter_confs_atoms = list(raw) if not isinstance(raw, Atoms) else [raw]

        if isinstance(reference, (Path, str)):
            raw = read(str(reference), index=":")
            dset_confs = list(raw) if not isinstance(raw, Atoms) else [raw]
        elif isinstance(reference, list):
            loaded = [read(p, index=":") for p in reference]
            dset_confs = [a for sub in loaded for a in (sub if isinstance(sub, list) else [sub])]
        else:
            dset_confs = []

        common_kwargs = dict(
            chunk_size=chunk_size, max_sel=max_sel, k=k,
            cutoff=cutoff, batch_size=batch_size, h=h, dtype="float32",
        )
        try:
            import torch  # noqa: F401
            select_atoms, select_result = _h_filter_gpu(
                iter_confs_atoms, dset_confs, **common_kwargs
            )
        except ImportError:
            select_atoms, select_result = _h_filter_cpu(
                iter_confs_atoms, dset_confs, **common_kwargs
            )

        work_path = Path(_generate_work_path())
        work_path.mkdir(parents=True, exist_ok=True)
        out_path = work_path / "selected.extxyz"
        write(out_path, select_atoms)

        return {
            "status": "success",
            "message": "Filter by entropy completed.",
            "selected_atoms": str(out_path.resolve()),
            "entropy": select_result,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Filter by entropy failed: {exc}",
            "selected_atoms": "",
            "entropy": {},
        }


# ---------------------------------------------------------------------------
# CLI command handler
# ---------------------------------------------------------------------------

def cmd_filter_by_entropy(args: argparse.Namespace) -> Dict[str, Any]:
    reference: Union[List[str], str] = args.reference if args.reference else []
    return filter_by_entropy_impl(
        iter_confs=args.iter_confs,
        reference=reference,
        chunk_size=args.chunk_size,
        k=args.k,
        cutoff=args.cutoff,
        batch_size=args.batch_size,
        h=args.h,
        max_sel=args.max_sel,
    )


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="active_learning",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ------------------------------------------------------------------
    # filter-by-entropy
    # ------------------------------------------------------------------
    p = sub.add_parser(
        "filter-by-entropy",
        help="Select a diverse subset of structures via entropy-based filtering.",
    )
    p.add_argument(
        "iter_confs", nargs="+",
        help="One or more candidate structure files (any ASE-readable format).",
    )
    p.add_argument(
        "--reference", nargs="*", default=[],
        help="Optional reference structure files already in the dataset.",
    )
    p.add_argument("--chunk-size", type=int, default=10,
                   help="Structures selected per iteration (default: 10).")
    p.add_argument("--k", type=int, default=32,
                   help="Number of nearest neighbours for descriptor (default: 32).")
    p.add_argument("--cutoff", type=float, default=5.0,
                   help="Descriptor cutoff radius in Å (default: 5.0).")
    p.add_argument("--batch-size", type=int, default=1000,
                   help="Batch size for entropy computation (default: 1000).")
    p.add_argument("--h", type=float, default=0.015,
                   help="Bandwidth parameter h (default: 0.015).")
    p.add_argument("--max-sel", type=int, default=50,
                   help="Maximum number of structures to select (default: 50).")
    p.set_defaults(func=cmd_filter_by_entropy)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
