#!/usr/bin/env python3
"""
lobster_tools.py - stage and summarize LOBSTER calculations.

Commands
--------
prepare_input         Stage a LOBSTER directory from a finished VASP SCF run.
prepare_input_cp2k    Stage a LOBSTER directory from prepared CP2K outputs.
prepare_input_qe      Stage a LOBSTER directory from prepared Quantum ESPRESSO outputs.
write_basis_template  Emit a JSON template for basis-functions mapping.
write_file_manifest   Emit a JSON template for explicit staged-file manifests.
write_vasp_incar      Emit a VASP INCAR template suitable for LOBSTER.
read_results          Summarize one finished LOBSTER calculation directory.
collect_results       Summarize several finished LOBSTER calculation directories.

Every command prints JSON to stdout and exits 0 on success, 1 on error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CONFIG = _SCRIPT_DIR.parent / "config.yaml"
_REQUIRED_VASP_FILES = ("POSCAR", "POTCAR", "INCAR", "KPOINTS", "WAVECAR", "CHGCAR")
_SUPPORTED_CODES = ("vasp", "cp2k", "qe")


def _load_config(config_path: Path) -> dict[str, Any]:
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "work_dir" not in data:
        raise ValueError(f"Missing 'work_dir' in config: {config_path}")
    return data


def _resolve_work_dir(work_dir_value: str) -> Path:
    work_dir = Path(work_dir_value).expanduser()
    if work_dir.is_absolute():
        return work_dir

    session_dir = os.environ.get("MATCLAW_SESSION_DIR", "")
    if session_dir:
        return Path(session_dir).expanduser().resolve() / work_dir

    return Path.cwd().resolve() / work_dir


def _calc_id() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S_%f")


def _parse_poscar_species(poscar_path: Path) -> list[str]:
    lines = [line.strip() for line in poscar_path.read_text(encoding="utf-8").splitlines()]
    if len(lines) < 7:
        raise ValueError(f"POSCAR looks too short: {poscar_path}")

    species_line = lines[5].split()
    count_line = lines[6].split()

    if species_line and all(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", token) for token in species_line):
        if not count_line or not all(token.lstrip("+-").isdigit() for token in count_line):
            raise ValueError(f"POSCAR species/count lines are not in expected VASP 5 format: {poscar_path}")
        return species_line

    raise ValueError(
        "Could not parse species from POSCAR. This skill currently expects VASP 5 style POSCAR files."
    )


def _load_basis_mapping(raw_json: str | None, basis_file: str | None) -> dict[str, str]:
    mapping: dict[str, str] = {}

    if raw_json:
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            raise ValueError("--basis-functions must decode to a JSON object")
        mapping.update({str(k): str(v) for k, v in data.items()})

    if basis_file:
        path = Path(basis_file).expanduser().resolve()
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("--basis-file must contain a JSON/YAML object")
        mapping.update({str(k): str(v) for k, v in data.items()})

    return mapping


def _ensure_required_files(scf_dir: Path) -> list[str]:
    missing = [name for name in _REQUIRED_VASP_FILES if not (scf_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"SCF directory is missing required VASP files: {', '.join(missing)}"
        )
    return list(_REQUIRED_VASP_FILES)


def _load_manifest(raw_json: str | None, manifest_file: str | None) -> dict[str, str]:
    manifest: dict[str, str] = {}

    if raw_json:
        data = json.loads(raw_json)
        if not isinstance(data, dict):
            raise ValueError("--file-manifest must decode to a JSON object")
        manifest.update({str(k): str(v) for k, v in data.items()})

    if manifest_file:
        path = Path(manifest_file).expanduser().resolve()
        text = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("--manifest-file must contain a JSON/YAML object")
        manifest.update({str(k): str(v) for k, v in data.items()})

    return manifest


def _stage_file(src: Path, dst: Path, copy_files: bool) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if copy_files:
        shutil.copy2(src, dst)
    else:
        dst.symlink_to(src.resolve())


def _build_lobsterin(
    species: list[str],
    basis_mapping: dict[str, str],
    basis_set: str,
    task: str,
    orbitalwise: bool,
) -> str:
    missing_species = [sp for sp in species if sp not in basis_mapping or not basis_mapping[sp].strip()]
    if missing_species:
        raise ValueError(
            "Missing basis functions for species: "
            + ", ".join(missing_species)
            + ". Use --basis-functions or --basis-file."
        )

    lines = [
        "COHPstartEnergy -15.0",
        "COHPendEnergy 5.0",
        f"basisSet {basis_set}",
        "gaussianSmearingWidth 0.05",
        "",
    ]

    for sp in species:
        lines.append(f"basisfunctions {sp} {basis_mapping[sp].strip()}")

    lines.append("")

    task_key = task.strip().lower()
    if task_key == "standard":
        lines.append("cohpGenerator from 0.1 to 6.0")
        lines.append("saveProjectionToFile")
    elif task_key == "onlycohp":
        lines.append("skipDOS")
        lines.append("cohpGenerator from 0.1 to 6.0")
    elif task_key == "onlydos":
        lines.append("skipCOHP")
    elif task_key == "onlycoop":
        lines.append("skipDOS")
        lines.append("COOPGenerator from 0.1 to 6.0")
    else:
        raise ValueError(f"Unsupported --task value: {task}")

    if orbitalwise:
        lines.append("orbitalwise")

    return "\n".join(lines) + "\n"


def _build_generic_lobsterin(
    species: list[str],
    basis_mapping: dict[str, str],
    basis_set: str,
    task: str,
    orbitalwise: bool,
    code: str,
) -> str:
    header = [f"# Generated for {code.upper()} -> LOBSTER staging"]
    return "\n".join(header) + "\n" + _build_lobsterin(
        species=species,
        basis_mapping=basis_mapping,
        basis_set=basis_set,
        task=task,
        orbitalwise=orbitalwise,
    )


def _load_species_list(raw_species: str | None, species_file: str | None) -> list[str]:
    species: list[str] = []
    if raw_species:
        species.extend(token for token in raw_species.split() if token)
    if species_file:
        path = Path(species_file).expanduser().resolve()
        suffix = path.suffix.lower()
        text = path.read_text(encoding="utf-8")
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            data = [line.strip() for line in text.splitlines() if line.strip()]
        if not isinstance(data, list):
            raise ValueError("--species-file must contain a list")
        species.extend(str(item) for item in data if str(item).strip())

    deduped: list[str] = []
    for item in species:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _stage_manifest_files(source_dir: Path, calc_dir: Path, manifest: dict[str, str], copy_files: bool) -> list[str]:
    if not manifest:
        raise ValueError("A non-empty file manifest is required")

    staged_files: list[str] = []
    for target_name, source_name in manifest.items():
        source_path = (source_dir / source_name).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Required source file not found: {source_path}")
        dest_path = calc_dir / target_name
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        _stage_file(source_path, dest_path, copy_files=copy_files)
        staged_files.append(target_name)
    return staged_files


def _prepare_generic_input(
    *,
    code: str,
    source_dir_arg: str,
    basis_functions: str | None,
    basis_file: str | None,
    manifest_json: str | None,
    manifest_file: str | None,
    species_arg: str | None,
    species_file: str | None,
    basis_set: str,
    task: str,
    orbitalwise: bool,
    copy_files: bool,
    config_path: Path,
) -> dict[str, Any]:
    if code not in _SUPPORTED_CODES:
        raise ValueError(f"Unsupported code: {code}")

    config = _load_config(config_path)
    work_dir = _resolve_work_dir(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    source_dir = Path(source_dir_arg).expanduser().resolve()
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    species = _load_species_list(species_arg, species_file)
    if not species:
        raise ValueError("Species list is required. Use --species or --species-file.")

    basis_mapping = _load_basis_mapping(basis_functions, basis_file)
    manifest = _load_manifest(manifest_json, manifest_file)

    calc_dir = work_dir / f"lobster_{code}_{source_dir.name}_{_calc_id()}"
    calc_dir.mkdir(parents=True, exist_ok=False)

    staged_files = _stage_manifest_files(source_dir, calc_dir, manifest, copy_files=copy_files)
    lobsterin_text = _build_generic_lobsterin(
        species=species,
        basis_mapping=basis_mapping,
        basis_set=basis_set,
        task=task,
        orbitalwise=orbitalwise,
        code=code,
    )
    (calc_dir / "lobsterin").write_text(lobsterin_text, encoding="utf-8")

    return {
        "status": "success",
        "code": code,
        "calc_dir": str(calc_dir.resolve()),
        "source_dir": str(source_dir),
        "staged_files": staged_files + ["lobsterin"],
        "species": species,
        "basis_functions": {sp: basis_mapping[sp] for sp in species},
        "file_manifest": manifest,
        "copy_files": bool(copy_files),
        "task": task,
    }


def _parse_lobsterout_spillings(lobsterout_path: Path) -> dict[str, float | None]:
    text = lobsterout_path.read_text(encoding="utf-8", errors="replace")

    def extract(pattern: str) -> float | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return float(match.group(1)) if match else None

    return {
        "charge_spilling_percent": extract(r"abs\.\s*charge\s*spilling:\s*([0-9.]+)"),
        "total_spilling_percent": extract(r"abs\.\s*total\s*spilling:\s*([0-9.]+)"),
    }


def _parse_basisfunctions(lobsterin_path: Path) -> dict[str, str]:
    basis_functions: dict[str, str] = {}
    for line in lobsterin_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("basisfunctions "):
            continue
        _, rest = stripped.split(None, 1)
        species, basis = rest.split(None, 1)
        basis_functions[species] = basis.strip()
    return basis_functions


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _parse_icohplist(icohp_path: Path) -> list[dict[str, Any]]:
    bonds: list[dict[str, Any]] = []
    for raw_line in icohp_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if "distance" in lowered or "translation" in lowered or "spin" in lowered:
            continue

        tokens = line.split()
        if len(tokens) < 5:
            continue

        numeric_positions = [idx for idx, token in enumerate(tokens) if _safe_float(token) is not None]
        if len(numeric_positions) < 2:
            continue

        icohp_idx = numeric_positions[-1]
        length_idx = numeric_positions[-2]
        if length_idx <= 1:
            continue

        bond_index = tokens[0]
        atom1 = tokens[1]
        atom2 = tokens[2]
        length = _safe_float(tokens[length_idx])
        icohp = _safe_float(tokens[icohp_idx])
        translation = " ".join(tokens[3:length_idx]) if length_idx > 3 else None

        bonds.append(
            {
                "bond_index": bond_index,
                "atom1": atom1,
                "atom2": atom2,
                "translation": translation,
                "length": length,
                "icohp": icohp,
            }
        )
    return bonds


def _summarize_calc_dir(calc_dir: Path) -> dict[str, Any]:
    if not calc_dir.exists():
        raise FileNotFoundError(f"Calculation directory not found: {calc_dir}")

    result: dict[str, Any] = {
        "calc_dir": str(calc_dir.resolve()),
        "status": "success",
    }

    lobsterin_path = calc_dir / "lobsterin"
    if lobsterin_path.exists():
        result["basis_functions"] = _parse_basisfunctions(lobsterin_path)

    lobsterout_path = calc_dir / "lobsterout"
    if lobsterout_path.exists():
        result.update(_parse_lobsterout_spillings(lobsterout_path))

    icohp_path = calc_dir / "ICOHPLIST.lobster"
    if icohp_path.exists():
        bonds = _parse_icohplist(icohp_path)
        result["bond_count"] = len(bonds)
        if bonds:
            valid_bonds = [bond for bond in bonds if bond.get("icohp") is not None]
            if valid_bonds:
                result["most_bonding_pair"] = min(valid_bonds, key=lambda bond: bond["icohp"])
            result["bonds"] = bonds[:10]
    else:
        result["bond_count"] = 0

    return result


def cmd_prepare_input(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_config(args.config)
    work_dir = _resolve_work_dir(config["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    scf_dir = Path(args.scf_dir).expanduser().resolve()
    if not scf_dir.exists():
        raise FileNotFoundError(f"SCF directory not found: {scf_dir}")

    staged_files = _ensure_required_files(scf_dir)
    species = _parse_poscar_species(scf_dir / "POSCAR")
    basis_mapping = _load_basis_mapping(args.basis_functions, args.basis_file)

    calc_dir = work_dir / f"lobster_{scf_dir.name}_{_calc_id()}"
    calc_dir.mkdir(parents=True, exist_ok=False)

    for name in staged_files:
        _stage_file(scf_dir / name, calc_dir / name, copy_files=args.copy_files)

    lobsterin_text = _build_lobsterin(
        species=species,
        basis_mapping=basis_mapping,
        basis_set=args.basis_set,
        task=args.task,
        orbitalwise=args.orbitalwise,
    )
    (calc_dir / "lobsterin").write_text(lobsterin_text, encoding="utf-8")

    return {
        "status": "success",
        "calc_dir": str(calc_dir.resolve()),
        "scf_dir": str(scf_dir),
        "staged_files": staged_files + ["lobsterin"],
        "species": species,
        "basis_functions": {sp: basis_mapping[sp] for sp in species},
        "copy_files": bool(args.copy_files),
        "task": args.task,
    }


def cmd_write_basis_template(args: argparse.Namespace) -> dict[str, Any]:
    scf_dir = Path(args.scf_dir).expanduser().resolve()
    if not scf_dir.exists():
        raise FileNotFoundError(f"SCF directory not found: {scf_dir}")

    species = _parse_poscar_species(scf_dir / "POSCAR")
    template = {sp: "" for sp in species}

    output_path: Path | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(template, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return {
        "status": "success",
        "scf_dir": str(scf_dir),
        "species": species,
        "basis_template": template,
        "output_path": str(output_path) if output_path else None,
    }


def cmd_write_vasp_incar(args: argparse.Namespace) -> dict[str, Any]:
    lines = [
        "# Static calculation for LOBSTER",
        "ISPIN = 1",
        f"ENCUT = {args.encut}",
        "ALGO = Normal",
        f"EDIFF = {args.ediff}",
        f"NELM = {args.nelm}",
        f"ISMEAR = {args.ismear}",
        f"SIGMA = {args.sigma}",
        "",
        "IBRION = -1",
        "NSW = 0",
        "ISIF = 2",
        "",
        f"NPAR = {args.npar}",
        "LREAL = Auto",
        "NSIM = 1",
        "LPLANE = .TRUE.",
        "",
        "IVDW = 12",
        "",
        "LWAVE = .TRUE.",
        f"LCHARG = {'.TRUE.' if args.lcharg else '.FALSE.'}",
        "NEDOS = 1000",
        "LORBIT = 12",
        "ISYM = -1",
        "LELF = .FALSE.",
        "LVTOT = .FALSE.",
        "LVHAR = .FALSE.",
    ]
    if args.nbands is not None:
        lines.append(f"NBANDS = {args.nbands}")

    content = "\n".join(lines) + "\n"
    output_path: Path | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

    return {
        "status": "success",
        "incar_template": content,
        "output_path": str(output_path) if output_path else None,
        "notes": [
            "Template follows the user's LOBSTER-oriented static VASP settings.",
            "Set NBANDS explicitly for the target system before production use.",
            "If you need CHGCAR for downstream inspection, pass --lcharg.",
        ],
    }


def cmd_write_file_manifest(args: argparse.Namespace) -> dict[str, Any]:
    code = args.code.lower()
    if code not in {"cp2k", "qe"}:
        raise ValueError("--code must be one of: cp2k, qe")

    if code == "cp2k":
        template = {
            "lobster_projection_data": "PROJECTION_DATA",
            "structure_file": "geometry.xyz",
            "main_output": "cp2k.out",
        }
    else:
        template = {
            "lobster_projection_data": "prefix.save",
            "structure_file": "pwscf.in",
            "main_output": "pwscf.out",
        }

    output_path: Path | None = None
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(template, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return {
        "status": "success",
        "code": code,
        "file_manifest_template": template,
        "output_path": str(output_path) if output_path else None,
        "notes": [
            "Edit the values so they match the actual files produced in your environment.",
            "The keys become staged filenames inside the LOBSTER run directory.",
        ],
    }


def cmd_prepare_input_cp2k(args: argparse.Namespace) -> dict[str, Any]:
    return _prepare_generic_input(
        code="cp2k",
        source_dir_arg=args.source_dir,
        basis_functions=args.basis_functions,
        basis_file=args.basis_file,
        manifest_json=args.file_manifest,
        manifest_file=args.manifest_file,
        species_arg=args.species,
        species_file=args.species_file,
        basis_set=args.basis_set,
        task=args.task,
        orbitalwise=args.orbitalwise,
        copy_files=args.copy_files,
        config_path=args.config,
    )


def cmd_prepare_input_qe(args: argparse.Namespace) -> dict[str, Any]:
    return _prepare_generic_input(
        code="qe",
        source_dir_arg=args.source_dir,
        basis_functions=args.basis_functions,
        basis_file=args.basis_file,
        manifest_json=args.file_manifest,
        manifest_file=args.manifest_file,
        species_arg=args.species,
        species_file=args.species_file,
        basis_set=args.basis_set,
        task=args.task,
        orbitalwise=args.orbitalwise,
        copy_files=args.copy_files,
        config_path=args.config,
    )


def cmd_read_results(args: argparse.Namespace) -> dict[str, Any]:
    return _summarize_calc_dir(Path(args.calc_dir).expanduser().resolve())


def cmd_collect_results(args: argparse.Namespace) -> dict[str, Any]:
    summaries = [_summarize_calc_dir(Path(calc_dir).expanduser().resolve()) for calc_dir in args.dirs]
    return {
        "status": "success",
        "count": len(summaries),
        "results": summaries,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and summarize LOBSTER calculations.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare_input", help="Stage one LOBSTER calculation directory.")
    prepare.add_argument("--scf_dir", required=True, help="Completed VASP SCF directory.")
    prepare.add_argument("--basis-functions", help="JSON mapping of species to basis functions.")
    prepare.add_argument("--basis-file", help="Path to JSON or YAML basis mapping file.")
    prepare.add_argument("--basis-set", default="pbeVaspFit2015", help="LOBSTER basisSet value.")
    prepare.add_argument(
        "--task",
        default="standard",
        choices=["standard", "onlycohp", "onlydos", "onlycoop"],
        help="Minimal LOBSTER workflow to write into lobsterin.",
    )
    prepare.add_argument("--orbitalwise", action="store_true", help="Add orbitalwise output to lobsterin.")
    prepare.add_argument("--copy-files", action="store_true", help="Copy VASP files instead of symlinking them.")
    prepare.add_argument("--config", type=Path, default=_DEFAULT_CONFIG, help="Path to config.yaml.")
    prepare.set_defaults(func=cmd_prepare_input)

    prepare_cp2k = subparsers.add_parser(
        "prepare_input_cp2k",
        help="Stage one LOBSTER calculation directory from prepared CP2K outputs.",
    )
    prepare_cp2k.add_argument("--source_dir", required=True, help="Directory containing CP2K outputs to stage.")
    prepare_cp2k.add_argument("--species", help="Whitespace-separated species list, e.g. 'Ir O'.")
    prepare_cp2k.add_argument("--species-file", help="Path to JSON/YAML/text species list.")
    prepare_cp2k.add_argument("--basis-functions", help="JSON mapping of species to basis functions.")
    prepare_cp2k.add_argument("--basis-file", help="Path to JSON or YAML basis mapping file.")
    prepare_cp2k.add_argument("--file-manifest", help="JSON object mapping staged filenames to source filenames.")
    prepare_cp2k.add_argument("--manifest-file", help="Path to JSON/YAML file-manifest.")
    prepare_cp2k.add_argument("--basis-set", default="pbeVaspFit2015", help="LOBSTER basisSet value.")
    prepare_cp2k.add_argument(
        "--task",
        default="standard",
        choices=["standard", "onlycohp", "onlydos", "onlycoop"],
        help="Minimal LOBSTER workflow to write into lobsterin.",
    )
    prepare_cp2k.add_argument("--orbitalwise", action="store_true", help="Add orbitalwise output to lobsterin.")
    prepare_cp2k.add_argument("--copy-files", action="store_true", help="Copy files instead of symlinking them.")
    prepare_cp2k.add_argument("--config", type=Path, default=_DEFAULT_CONFIG, help="Path to config.yaml.")
    prepare_cp2k.set_defaults(func=cmd_prepare_input_cp2k)

    prepare_qe = subparsers.add_parser(
        "prepare_input_qe",
        help="Stage one LOBSTER calculation directory from prepared Quantum ESPRESSO outputs.",
    )
    prepare_qe.add_argument("--source_dir", required=True, help="Directory containing QE outputs to stage.")
    prepare_qe.add_argument("--species", help="Whitespace-separated species list, e.g. 'Ir O'.")
    prepare_qe.add_argument("--species-file", help="Path to JSON/YAML/text species list.")
    prepare_qe.add_argument("--basis-functions", help="JSON mapping of species to basis functions.")
    prepare_qe.add_argument("--basis-file", help="Path to JSON or YAML basis mapping file.")
    prepare_qe.add_argument("--file-manifest", help="JSON object mapping staged filenames to source filenames.")
    prepare_qe.add_argument("--manifest-file", help="Path to JSON/YAML file-manifest.")
    prepare_qe.add_argument("--basis-set", default="pbeVaspFit2015", help="LOBSTER basisSet value.")
    prepare_qe.add_argument(
        "--task",
        default="standard",
        choices=["standard", "onlycohp", "onlydos", "onlycoop"],
        help="Minimal LOBSTER workflow to write into lobsterin.",
    )
    prepare_qe.add_argument("--orbitalwise", action="store_true", help="Add orbitalwise output to lobsterin.")
    prepare_qe.add_argument("--copy-files", action="store_true", help="Copy files instead of symlinking them.")
    prepare_qe.add_argument("--config", type=Path, default=_DEFAULT_CONFIG, help="Path to config.yaml.")
    prepare_qe.set_defaults(func=cmd_prepare_input_qe)

    template = subparsers.add_parser("write_basis_template", help="Generate a species-to-basis JSON template.")
    template.add_argument("--scf_dir", required=True, help="Completed VASP SCF directory.")
    template.add_argument("--output", help="Optional path to write the JSON template.")
    template.set_defaults(func=cmd_write_basis_template)

    manifest = subparsers.add_parser("write_file_manifest", help="Generate a file-manifest JSON template for CP2K or QE.")
    manifest.add_argument("--code", required=True, choices=["cp2k", "qe"], help="Upstream code interface.")
    manifest.add_argument("--output", help="Optional path to write the JSON template.")
    manifest.set_defaults(func=cmd_write_file_manifest)

    write_incar = subparsers.add_parser("write_vasp_incar", help="Generate a VASP INCAR template for LOBSTER.")
    write_incar.add_argument("--output", help="Optional path to write the INCAR template.")
    write_incar.add_argument("--encut", type=int, default=400, help="Plane-wave cutoff energy in eV.")
    write_incar.add_argument("--ediff", default="1E-5", help="Electronic convergence threshold.")
    write_incar.add_argument("--nelm", type=int, default=300, help="Maximum SCF electronic steps.")
    write_incar.add_argument("--ismear", type=int, default=1, help="Smearing method.")
    write_incar.add_argument("--sigma", type=float, default=0.05, help="Smearing width in eV.")
    write_incar.add_argument("--npar", type=int, default=10, help="NPAR setting.")
    write_incar.add_argument("--nbands", type=int, help="Explicit NBANDS for LOBSTER.")
    write_incar.add_argument("--lcharg", action="store_true", help="Write LCHARG = .TRUE. instead of .FALSE..")
    write_incar.set_defaults(func=cmd_write_vasp_incar)

    read_results = subparsers.add_parser("read_results", help="Read one finished LOBSTER result directory.")
    read_results.add_argument("--calc_dir", required=True, help="Finished LOBSTER calculation directory.")
    read_results.set_defaults(func=cmd_read_results)

    collect = subparsers.add_parser("collect_results", help="Aggregate several finished LOBSTER directories.")
    collect.add_argument("--dirs", nargs="+", required=True, help="Finished LOBSTER calculation directories.")
    collect.set_defaults(func=cmd_collect_results)

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        result = args.func(args)
    except Exception as exc:
        result = {
            "status": "error",
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
