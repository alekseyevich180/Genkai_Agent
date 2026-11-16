"""Structure file conventions for surface modeling.

See ``AGENTS.md`` ("结构文件约定"):

* user inputs default to CIF, but any ASE-readable format is accepted and is
  read once at the entry point;
* stages exchange extxyz files, which keep ``FixAtoms`` (``move_mask``), tags,
  per-atom arrays and multiple frames;
* metadata goes to JSON manifests, not extxyz ``info`` (``"110"`` would be read
  back as an integer);
* CIF and POSCAR are export formats only; POSCAR is written unsorted so atom
  indices stay identical to the extxyz frames.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
from ase import Atoms
from ase.data import covalent_radii
from ase.io import read, write
from ase.io.formats import UnknownFileTypeError

EXPORT_FORMATS = ("cif", "vasp")


def read_structure(path: str | Path, format: str | None = None) -> tuple[Atoms, str]:
    """Read one structure and return it with the format actually used.

    ASE cannot guess the type of an extension-less POSCAR (e.g. a file named
    ``SnO2``); in that case the VASP reader is tried before giving up.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Structure file {source} does not exist.")
    if format is not None:
        return read(source, format=format), format
    try:
        return read(source), _detected_format(source)
    except UnknownFileTypeError:
        try:
            return read(source, format="vasp"), "vasp (fallback: type not guessable)"
        except Exception as exc:  # pragma: no cover - error path depends on file content
            raise ValueError(
                f"Cannot determine the format of {source.name}; pass an explicit format (e.g. cif, vasp, extxyz)."
            ) from exc


def _detected_format(path: Path) -> str:
    try:
        from ase.io.formats import filetype

        return str(filetype(str(path), guess=True))
    except Exception:  # pragma: no cover - reporting only
        return "ase-auto"


def make_molecule_whole(atoms: Atoms, scale: float = 1.2) -> Atoms:
    """Return a non-periodic copy with bonded atoms unwrapped across cell boundaries.

    Molecules stored in CIF files are folded into the unit cell, which splits a
    molecule that crosses a cell face. Bonds are found with the minimum-image
    convention and the fragments are reassembled by a breadth-first walk.
    """
    molecule = atoms.copy()
    molecule.set_constraint()
    if not any(molecule.pbc) or molecule.cell.rank < 3:
        molecule.pbc = False
        return molecule
    positions = molecule.get_positions()
    radii = covalent_radii[molecule.numbers]
    deltas = molecule.get_all_distances(mic=True, vector=True)
    distances = np.linalg.norm(deltas, axis=2)
    bonded = distances <= scale * (radii[:, None] + radii[None, :])
    np.fill_diagonal(bonded, False)
    placed = np.zeros(len(molecule), dtype=bool)
    unwrapped = positions.copy()
    for start in range(len(molecule)):
        if placed[start]:
            continue
        placed[start] = True
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in np.flatnonzero(bonded[current]):
                if not placed[neighbor]:
                    unwrapped[neighbor] = unwrapped[current] + deltas[current, neighbor]
                    placed[neighbor] = True
                    queue.append(int(neighbor))
    molecule.set_positions(unwrapped)
    molecule.pbc = False
    molecule.cell = None
    return molecule


def read_molecule(path: str | Path, format: str | None = None) -> tuple[Atoms, str]:
    """Read a molecule from any supported file, made whole and non-periodic."""
    atoms, used = read_structure(path, format)
    return make_molecule_whole(atoms), used


def write_frames(path: str | Path, frames: Sequence[Atoms]) -> Path:
    """Write frames as extxyz (the stage-to-stage format)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    write(target, list(frames), format="extxyz")
    return target


def export_frames(
    frames: Sequence[Atoms],
    output_dir: str | Path,
    stem: str,
    formats: Iterable[str] = EXPORT_FORMATS,
) -> list[Path]:
    """Export each frame as CIF and/or unsorted POSCAR for viewing or DFT input."""
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"Unsupported export format {fmt!r}; choose from {', '.join(EXPORT_FORMATS)}.")
        for index, frame in enumerate(frames):
            path = outdir / f"{stem}_{index:03d}.{fmt}"
            if fmt == "vasp":
                write(path, frame, format="vasp", direct=True, sort=False)
            else:
                write(path, frame, format=fmt)
            written.append(path)
    return written


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_ready(value: Any) -> Any:
    """Convert numpy scalars/arrays and paths so ``json.dumps`` accepts them."""
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, np.ndarray):
        return json_ready(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return value.as_posix()
    return value


def write_manifest(path: str | Path, data: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(json_ready(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
