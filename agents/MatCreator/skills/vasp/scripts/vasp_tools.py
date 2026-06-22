#!/usr/bin/env python3
"""
vasp_tools.py  —  CLI for VASP input preparation and result collection.

Commands
--------
  prepare_relaxation    Prepare VASP relaxation input files from an extxyz structure.
  prepare_scf           Prepare VASP SCF input files.
  prepare_nscf_kpath    Prepare VASP NSCF (band structure, k-path) input files.
  prepare_nscf_uniform  Prepare VASP NSCF (uniform mesh / DOS) input files.
  collect_results       Collect VASP output into extxyz (energy, forces, etc.).
  read_results          Read and print calculation results (energy, band gap, etc.).

Every command prints a JSON object to stdout and exits 0 on success, 1 on error.

Examples
--------
  # Prepare relaxation inputs for all frames in Al.extxyz
  python vasp_tools.py prepare_relaxation --structure Al.extxyz

  # Prepare SCF with SOC, explicit k-mesh, and custom INCAR tags
  python vasp_tools.py prepare_scf --structure Al_relaxed.extxyz --soc \\
      --kpoints 8 8 8 --incar_tags '{"ENCUT": 600}'

  # Prepare band-structure NSCF from a previous SCF output
  python vasp_tools.py prepare_nscf_kpath --scf_dirs /tmp/vasp_server/scf_001

  # Collect SCF results into extxyz
  python vasp_tools.py collect_results --dirs /tmp/vasp_server/scf_001 /tmp/vasp_server/scf_002
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import time
import uuid

import dpdata
import numpy as np
import yaml
from ase import Atoms
from ase.io import read, write
from pymatgen.core import Element, Structure
from pymatgen.io.vasp import Kpoints, Outcar, Poscar, Potcar, VaspInput, Vasprun

# ── inlined helpers (from vasp_tools package) ────────────────────────────────

def _generate_work_path() -> str:
    """Return a unique timestamped work dir path and create it."""
    current_time = time.strftime("%Y%m%d%H%M%S")
    random_string = str(uuid.uuid4())[:8]
    work_path = f"{current_time}.collect_results.{random_string}"
    os.makedirs(work_path, exist_ok=True)
    return work_path


def _dpdata2ase_single(sys: dpdata.System) -> Atoms:
    """Convert a single-frame dpdata System to ase.Atoms."""
    atoms = Atoms(
        symbols=[sys.get_atom_names()[i] for i in sys.get_atom_types()],
        positions=sys.data["coords"][0].tolist(),
        cell=sys.data["cells"][0].tolist(),
        pbc=not sys.nopbc,
    )
    if "virial" in sys.data:
        atoms.set_array("virial", sys.data["virial"][0])
    if "forces" in sys.data:
        atoms.set_array("forces", sys.data["forces"][0])
    if "energies" in sys.data:
        atoms.info["energy"] = sys.data["energies"][0]
    return atoms


def _vasp_scf_results(work_dir_ls: List[Path]) -> dict:
    """Collect VASP OUTCAR results into a single extxyz file."""
    try:
        atoms_ls = []
        for work_dir in work_dir_ls:
            system = dpdata.LabeledSystem(
                str(work_dir.resolve() / "OUTCAR"), fmt="vasp/outcar"
            )
            atoms_ls.append(_dpdata2ase_single(system))
        out_dir = Path(_generate_work_path()).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        result_path = out_dir / "scf_result.extxyz"
        write(str(result_path), atoms_ls, format="extxyz")
        return {"status": "success", "scf_result": str(result_path)}
    except Exception as e:
        return {"status": "error", "message": str(e),
                "traceback": traceback.format_exc()}


def _read_calculation_result(calc_type: str, calculate_path: str) -> dict:
    """Read vasprun.xml / OUTCAR and return key results as a plain dict."""
    try:
        if calc_type == "relaxation":
            vasprun = Vasprun(os.path.join(calculate_path, "vasprun.xml"))
            contcar = Poscar.from_file(os.path.join(calculate_path, "CONTCAR"))
            return {
                "structure": str(contcar.structure.formula),
                "total_energy": vasprun.final_energy,
                "max_force": float(np.max(
                    np.linalg.norm(vasprun.ionic_steps[-1]["forces"], axis=1)
                )),
                "stress": vasprun.ionic_steps[-1]["stress"].tolist(),
                "ionic_steps": len(vasprun.ionic_steps),
            }
        elif calc_type == "scf":
            vasprun = Vasprun(os.path.join(calculate_path, "vasprun.xml"))
            bs = vasprun.get_band_structure()
            return {
                "structure": str(vasprun.final_structure.formula),
                "total_energy": vasprun.final_energy,
                "efermi": vasprun.efermi,
                "band_gap": bs.get_band_gap(),
                "is_metal": bs.is_metal(),
            }
        elif calc_type == "nscf":
            vasprun = Vasprun(os.path.join(calculate_path, "vasprun.xml"))
            bs = vasprun.get_band_structure()
            return {
                "structure": str(vasprun.final_structure.formula),
                "efermi": vasprun.efermi,
                "is_metal": bs.is_metal(),
                "band_gap": bs.get_band_gap(),
                "cbm": bs.get_cbm(),
                "vbm": bs.get_vbm(),
            }
        else:
            return {"status": "error", "message": f"Unknown calc_type: {calc_type}"}
    except Exception as e:
        return {"status": "error", "message": str(e),
                "traceback": traceback.format_exc()}


# ── config helpers ────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).parent
_DEFAULT_CONFIG = _SCRIPT_DIR.parent / "config.yaml"


def _load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _load_env(config_path: Path) -> None:
    from dotenv import load_dotenv
    env_file = config_path.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _resolve_work_dir(work_dir_value: str) -> Path:
    """Resolve the configured work directory, preferring the session workspace."""
    work_dir = Path(work_dir_value).expanduser()
    if work_dir.is_absolute():
        return work_dir

    session_dir = os.environ.get("MATCLAW_SESSION_DIR", "")
    if session_dir:
        return Path(session_dir).expanduser().resolve() / work_dir

    return Path.cwd() / work_dir


# ── shared helpers ────────────────────────────────────────────────────────────

def _calc_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S_%f")


def _auto_kpoints(struct: Structure, kppra_density: float) -> Tuple[int, int, int]:
    """KPPRA-style automatic k-point mesh."""
    factor = kppra_density * (
        struct.lattice.a * struct.lattice.b * struct.lattice.c / struct.lattice.volume
    ) ** (1 / 3)
    return (
        max(math.ceil(factor / struct.lattice.a), 1),
        max(math.ceil(factor / struct.lattice.b), 1),
        max(math.ceil(factor / struct.lattice.c), 1),
    )


def _build_potcar_symbols(struct: Structure, potcar_map: Dict[str, str]) -> List[str]:
    """Return ordered POTCAR symbol list matching the POSCAR species order."""
    poscar = Poscar(struct)
    unique_species: List[str] = []
    for species in poscar.structure.species:
        sym: str = species.symbol
        if not unique_species or sym != unique_species[-1]:
            if sym not in potcar_map:
                potcar_map[sym] = sym
            unique_species.append(sym)
    return [potcar_map[s] for s in unique_species]


def _write_vasp_input(
    struct: Structure,
    calc_dir: str,
    incar_dict: dict,
    kpoints: Kpoints,
    potcar_map: Optional[Dict[str, str]] = None,
) -> None:
    """Write POSCAR, INCAR, KPOINTS, POTCAR into calc_dir."""
    if potcar_map is None:
        potcar_map = {}
    potcar_symbols = _build_potcar_symbols(struct, potcar_map)
    vasp_input = VaspInput(
        poscar=Poscar(struct),
        incar=incar_dict,
        kpoints=kpoints,
        potcar=Potcar(potcar_symbols),
    )
    vasp_input.write_input(calc_dir)


def _parse_structures(structure_path: str, frames: Optional[List[int]]) -> List[Structure]:
    """Read extxyz or *.vasp (POSCAR) files; return pymatgen Structure list (via temp CIFs).

    *.vasp files always contain exactly one frame.
    extxyz files may contain multiple frames; use *frames* to select a subset.
    """
    path = Path(structure_path)
    if path.suffix.lower() == ".vasp":
        atoms_list = [read(structure_path, format="vasp")]
    else:
        atoms_list = list(read(structure_path, index=":", format="extxyz"))
    tmp_dir = Path(tempfile.mkdtemp())
    structs: List[Structure] = []
    try:
        for idx, atoms in enumerate(atoms_list):
            if frames is not None and idx not in frames:
                continue
            cif_path = tmp_dir / f"frame_{idx:04d}.cif"
            write(str(cif_path), atoms, format="cif")
            structs.append(Structure.from_file(str(cif_path)))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return structs


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_prepare_relaxation(args) -> dict:
    config = _load_config(args.config)
    work_dir = _resolve_work_dir(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    incar_tags = json.loads(args.incar_tags) if args.incar_tags else {}
    potcar_map = json.loads(args.potcar_map) if args.potcar_map else {}
    kpoint_num = tuple(args.kpoints) if args.kpoints else None

    structs = _parse_structures(args.structure, args.frames)
    calc_dir_ls = []
    for struct in structs:
        calc_dir = str(work_dir / _calc_id())
        kpt = kpoint_num or _auto_kpoints(struct, 40.0)
        kpoints = Kpoints.gamma_automatic(kpts=kpt)
        incar = dict(config["VASP_default_INCAR"]["relaxation"])
        incar.update(incar_tags)
        _write_vasp_input(struct, calc_dir, incar, kpoints, potcar_map)
        calc_dir_ls.append(calc_dir)

    return {"status": "success", "calc_dir_list": calc_dir_ls}


def cmd_prepare_scf(args) -> dict:
    config = _load_config(args.config)
    work_dir = _resolve_work_dir(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    incar_tags = json.loads(args.incar_tags) if args.incar_tags else {}
    potcar_map = json.loads(args.potcar_map) if args.potcar_map else {}
    kpoint_num = tuple(args.kpoints) if args.kpoints else None
    incar_key = "scf_soc" if args.soc else "scf_nsoc"

    structs = _parse_structures(args.structure, args.frames)
    calc_dir_ls = []
    for struct in structs:
        calc_dir = str(work_dir / _calc_id())
        kpt = kpoint_num or _auto_kpoints(struct, 40.0)
        kpoints = Kpoints.gamma_automatic(kpts=kpt)
        incar = dict(config["VASP_default_INCAR"][incar_key])
        incar.update(incar_tags)
        _write_vasp_input(struct, calc_dir, incar, kpoints, potcar_map)
        calc_dir_ls.append(calc_dir)

    return {"status": "success", "calc_dir_list": calc_dir_ls}


def cmd_prepare_nscf_kpath(args) -> dict:
    from pymatgen.symmetry.bandstructure import HighSymmKpath

    config = _load_config(args.config)
    work_dir = _resolve_work_dir(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    incar_tags = json.loads(args.incar_tags) if args.incar_tags else {}
    potcar_map = json.loads(args.potcar_map) if args.potcar_map else {}
    incar_key = "nscf_soc" if args.soc else "nscf_nsoc"
    n_kpoints = args.n_kpoints or 16

    calc_dir_ls = []
    for scf_dir in [Path(d) for d in args.scf_dirs]:
        struct = Structure.from_file(str(scf_dir / "CONTCAR"))
        calc_dir = str(work_dir / _calc_id())

        kpath_obj = HighSymmKpath(struct, symprec=0.01)
        if kpath_obj.kpath is None:
            raise ValueError(f"Cannot generate k-path for structure in {scf_dir}")

        if args.kpath is None:
            kpoints = Kpoints.automatic_linemode(n_kpoints, kpath_obj)
        else:
            from ase.dft.kpoints import BandPath
            kpts_ase: BandPath = struct.to_ase_atoms().get_cell().bandpath(
                args.kpath, npoints=n_kpoints, eps=1e-2
            )
            kpath_list = list(args.kpath)
            high_sym_points, labels = [], []
            high_sym_points.append(kpts_ase.special_points[kpath_list[0]])
            labels.append(kpath_list[0])
            for key in kpath_list[1:-1]:
                high_sym_points.append(kpts_ase.special_points[key])
                labels.append(key)
                high_sym_points.append(kpts_ase.special_points[key])
                labels.append(key)
            high_sym_points.append(kpts_ase.special_points[kpath_list[-1]])
            labels.append(kpath_list[-1])
            kpoints = Kpoints(
                comment="User specified k-path",
                style=Kpoints.supported_modes.Line_mode,
                num_kpts=n_kpoints,
                kpts=high_sym_points,
                labels=labels,
                coord_type="Reciprocal",
            )

        incar = dict(config["VASP_default_INCAR"][incar_key])
        incar.update(incar_tags)
        _write_vasp_input(struct, calc_dir, incar, kpoints, potcar_map)

        shutil.copy(str(scf_dir / "CHGCAR"), os.path.join(calc_dir, "CHGCAR"))
        wavecar = scf_dir / "WAVECAR"
        if wavecar.exists():
            shutil.copy(str(wavecar), os.path.join(calc_dir, "WAVECAR"))

        calc_dir_ls.append(calc_dir)

    return {"status": "success", "calc_dir_list": calc_dir_ls}


def cmd_prepare_nscf_uniform(args) -> dict:
    config = _load_config(args.config)
    work_dir = _resolve_work_dir(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    incar_tags = json.loads(args.incar_tags) if args.incar_tags else {}
    potcar_map = json.loads(args.potcar_map) if args.potcar_map else {}
    kpoint_num = tuple(args.kpoints) if args.kpoints else None
    incar_key = "nscf_soc" if args.soc else "nscf_nsoc"

    calc_dir_ls = []
    for scf_dir in [Path(d) for d in args.scf_dirs]:
        struct = Structure.from_file(str(scf_dir / "CONTCAR"))
        calc_dir = str(work_dir / _calc_id())

        kpt = kpoint_num or _auto_kpoints(struct, 100.0)
        kpoints = Kpoints.gamma_automatic(kpts=kpt)
        incar = dict(config["VASP_default_INCAR"][incar_key])
        incar.update(incar_tags)
        _write_vasp_input(struct, calc_dir, incar, kpoints, potcar_map)

        shutil.copy(str(scf_dir / "CHGCAR"), os.path.join(calc_dir, "CHGCAR"))
        wavecar = scf_dir / "WAVECAR"
        if wavecar.exists():
            shutil.copy(str(wavecar), os.path.join(calc_dir, "WAVECAR"))

        calc_dir_ls.append(calc_dir)

    return {"status": "success", "calc_dir_list": calc_dir_ls}


def cmd_collect_results(args) -> dict:
    return _vasp_scf_results([Path(d) for d in args.dirs])


def cmd_read_results(args) -> dict:
    result = _read_calculation_result(args.calc_type, args.calc_dir)

    def _safe(v):
        try:
            json.dumps(v)
            return v
        except (TypeError, ValueError):
            return str(v)

    return {k: _safe(v) for k, v in result.items()}


# ── argparse ──────────────────────────────────────────────────────────────────

def _add_common_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--config", type=Path, default=_DEFAULT_CONFIG,
        help=f"Path to config.yaml (default: {_DEFAULT_CONFIG})",
    )
    p.add_argument(
        "--incar_tags", type=str, default=None,
        help='JSON dict of extra INCAR overrides, e.g. \'{"ENCUT": 600}\'',
    )
    p.add_argument(
        "--potcar_map", type=str, default=None,
        help='JSON dict mapping element → POTCAR label, e.g. \'{"Bi": "Bi_d"}\'',
    )


def main():
    parser = argparse.ArgumentParser(
        description="VASP input preparation and result collection CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── prepare_relaxation ────────────────────────────────────────────────────
    p = sub.add_parser("prepare_relaxation", help="Prepare structural relaxation inputs.")
    _add_common_args(p)
    p.add_argument("--structure", required=True, help="Path to extxyz structure file.")
    p.add_argument("--frames", type=int, nargs="+", default=None,
                   help="Frame indices to include (default: all).")
    p.add_argument("--kpoints", type=int, nargs=3, default=None, metavar=("NX", "NY", "NZ"),
                   help="Explicit k-mesh. Default: auto (KPPRA density 40).")
    p.set_defaults(func=cmd_prepare_relaxation)

    # ── prepare_scf ───────────────────────────────────────────────────────────
    p = sub.add_parser("prepare_scf", help="Prepare SCF inputs.")
    _add_common_args(p)
    p.add_argument("--structure", required=True, help="Path to extxyz structure file.")
    p.add_argument("--frames", type=int, nargs="+", default=None,
                   help="Frame indices to include (default: all).")
    p.add_argument("--kpoints", type=int, nargs=3, default=None, metavar=("NX", "NY", "NZ"),
                   help="Explicit k-mesh. Default: auto (KPPRA density 40).")
    p.add_argument("--soc", action="store_true", default=False,
                   help="Use SOC INCAR preset (scf_soc). Default: scf_nsoc.")
    p.set_defaults(func=cmd_prepare_scf)

    # ── prepare_nscf_kpath ────────────────────────────────────────────────────
    p = sub.add_parser("prepare_nscf_kpath",
                       help="Prepare NSCF band-structure inputs from SCF output dirs.")
    _add_common_args(p)
    p.add_argument("--scf_dirs", nargs="+", required=True,
                   help="Paths to SCF output directories (must contain CONTCAR, CHGCAR).")
    p.add_argument("--kpath", type=str, default=None,
                   help="K-path string, e.g. 'GMKG'. Default: auto from pymatgen.")
    p.add_argument("--n_kpoints", type=int, default=None,
                   help="Number of k-points per segment (default: 16).")
    p.add_argument("--soc", action="store_true", default=False)
    p.set_defaults(func=cmd_prepare_nscf_kpath)

    # ── prepare_nscf_uniform ──────────────────────────────────────────────────
    p = sub.add_parser("prepare_nscf_uniform",
                       help="Prepare NSCF uniform-mesh (DOS) inputs from SCF output dirs.")
    _add_common_args(p)
    p.add_argument("--scf_dirs", nargs="+", required=True,
                   help="Paths to SCF output directories (must contain CONTCAR, CHGCAR).")
    p.add_argument("--kpoints", type=int, nargs=3, default=None, metavar=("NX", "NY", "NZ"),
                   help="Explicit k-mesh. Default: auto (KPPRA density 100).")
    p.add_argument("--soc", action="store_true", default=False)
    p.set_defaults(func=cmd_prepare_nscf_uniform)

    # ── collect_results ───────────────────────────────────────────────────────
    p = sub.add_parser("collect_results",
                       help="Collect VASP output (OUTCAR) into a single extxyz file.")
    p.add_argument("--dirs", nargs="+", required=True,
                   help="Paths to VASP calculation output directories.")
    p.set_defaults(func=cmd_collect_results)

    # ── read_results ──────────────────────────────────────────────────────────
    p = sub.add_parser("read_results",
                       help="Read and print calculation results (energy, band gap, etc.).")
    p.add_argument("--calc_type", required=True,
                   choices=["relaxation", "scf", "nscf"],
                   help="Calculation type.")
    p.add_argument("--calc_dir", required=True,
                   help="Path to the calculation output directory.")
    p.set_defaults(func=cmd_read_results)

    args = parser.parse_args()
    _load_env(_DEFAULT_CONFIG)

    try:
        result = args.func(args)
        print(json.dumps(result, indent=2))
        sys.exit(0)
    except Exception as e:
        print(
            json.dumps({"status": "error", "message": str(e),
                        "traceback": traceback.format_exc()}),
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
