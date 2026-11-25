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
_INT_INFO_KEYS = ("charge", "spin")


def sanitize_atoms_info(atoms: Atoms) -> Atoms:
    """Normalize calculator-sensitive integer metadata (``charge``, ``spin``) in ``atoms.info``.

    ASE's extxyz reader parses free-text XYZ comment lines as key=value pairs, so
    comments like ``charge=0;`` become the string ``"0;"`` and bare words like
    ``charge`` become ``True``. MLIP calculators such as FAIRChem UMA require
    integer values for ``charge`` and ``spin``.
    """
    for key in _INT_INFO_KEYS:
        if key not in atoms.info:
            continue
        value = atoms.info[key]
        if isinstance(value, bool):
            atoms.info.pop(key, None)
        elif isinstance(value, (int, np.integer)):
            atoms.info[key] = int(value)
        elif isinstance(value, str):
            cleaned = value.strip().rstrip(";,")
            try:
                atoms.info[key] = int(cleaned)
            except ValueError:
                atoms.info.pop(key, None)
        else:
            atoms.info.pop(key, None)
    return atoms


def read_structure(path: str | Path, format: str | None = None) -> tuple[Atoms, str]:
    """Read one structure and return it with the format actually used.

    ASE cannot guess the type of an extension-less POSCAR (e.g. a file named
    ``SnO2``); in that case the VASP reader is tried before giving up.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Structure file {source} does not exist.")
    if format is not None:
        return sanitize_atoms_info(read(source, format=format)), format
    try:
        return sanitize_atoms_info(read(source)), _detected_format(source)
    except UnknownFileTypeError:
        try:
            return sanitize_atoms_info(read(source, format="vasp")), "vasp (fallback: type not guessable)"
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


# ---------------------------------------------------------------------------
# Atom components: which modeling step put each atom there
# ---------------------------------------------------------------------------
#
# The per-atom string array ``component`` survives ASE copies, repeats, deletions
# and extxyz round trips. Builders label the atoms they add; atoms added without a
# label read as "" (unknown). A structure without the array (a plain CIF slab) is
# all substrate, so unlabeled inputs behave exactly as before.
#
# "Solid" components form the surface that later steps build on; the others are
# decorations that later steps must not build on top of or overlap.

COMPONENT_ARRAY = "component"
COMPONENTS = ("substrate", "overlayer", "cluster", "sam", "adsorbate")
SOLID_COMPONENTS = frozenset({"substrate", "overlayer"})


def has_components(atoms: Atoms) -> bool:
    return COMPONENT_ARRAY in atoms.arrays


def components(atoms: Atoms) -> np.ndarray:
    """Component label per atom ("" for atoms added without a label)."""
    if not has_components(atoms):
        return np.full(len(atoms), "substrate", dtype=object)
    return np.array([str(value) for value in atoms.arrays[COMPONENT_ARRAY]], dtype=object)


def label_components(atoms: Atoms, label: str, indices: Iterable[int] | None = None) -> Atoms:
    """Set the component of ``indices`` (default: every atom) in place; unlabeled atoms become substrate first."""
    if label not in COMPONENTS:
        raise ValueError(f"Unknown component {label!r}; choose from {', '.join(COMPONENTS)}.")
    values = components(atoms).astype("U16")
    selected = np.arange(len(atoms)) if indices is None else np.fromiter(indices, dtype=int)
    values[selected] = label
    atoms.set_array(COMPONENT_ARRAY, values)
    return atoms


def solid_mask(atoms: Atoms) -> np.ndarray:
    """Atoms of the solid surface (substrate and overlayer); unknown labels count as decorations."""
    return np.isin(components(atoms), list(SOLID_COMPONENTS))


def decoration_mask(atoms: Atoms) -> np.ndarray:
    return ~solid_mask(atoms)


def free_lateral_positions(
    atoms: Atoms,
    start: tuple[float, float],
    radius: float,
    *,
    grid: int = 12,
) -> list[tuple[float, float]]:
    """Fractional in-plane positions with no decoration atom within ``radius`` (in-plane minimum image).

    The requested ``start`` comes first when it is free, then grid points by in-plane
    distance from it. Without decorations only ``start`` is returned.
    """
    decorated = np.flatnonzero(decoration_mask(atoms))
    if not len(decorated):
        return [start]
    cell = atoms.cell.array
    a, b = cell[0, :2], cell[1, :2]
    origin = start[0] * a + start[1] * b
    candidates = [start] + [((i + 0.5) / grid, (j + 0.5) / grid) for i in range(grid) for j in range(grid)]
    free: list[tuple[float, float, float]] = []
    inv = np.linalg.inv(np.vstack([a, b]))
    for fx, fy in candidates:
        point = fx * a + fy * b
        delta = atoms.positions[decorated, :2] - point
        frac = delta @ inv
        frac -= np.round(frac)
        lateral = np.linalg.norm(frac @ np.vstack([a, b]), axis=1)
        if lateral.min() >= radius:
            shift = (point - origin) @ inv
            shift -= np.round(shift)
            free.append((float(np.linalg.norm(shift @ np.vstack([a, b]))), fx, fy))
    free.sort(key=lambda item: item[0])
    return [(fx, fy) for _, fx, fy in free]


def local_solid_top(atoms: Atoms, point_xy: np.ndarray, radius: float) -> float:
    """Highest solid atom within ``radius`` of an in-plane point (global solid top if none)."""
    solid = np.flatnonzero(solid_mask(atoms))
    if not len(solid):
        return float(atoms.positions[:, 2].max())
    cell = atoms.cell.array
    basis = np.vstack([cell[0, :2], cell[1, :2]])
    frac = (atoms.positions[solid, :2] - point_xy) @ np.linalg.inv(basis)
    frac -= np.round(frac)
    lateral = np.linalg.norm(frac @ basis, axis=1)
    near = solid[lateral < radius]
    return float(atoms.positions[near if len(near) else solid, 2].max())


# ---------------------------------------------------------------------------
# Output checks shared by scripts/run_modeling_smoke.py and the job runner
# ---------------------------------------------------------------------------

CLASH_RATIO = 0.6  # d / (r_i + r_j) below this means overlapping atoms (executor rule)
MIN_VACUUM_A = 5.0


def read_frames(path: str | Path) -> list[Atoms]:
    """Read every frame of an output file (extension-less files are tried as POSCAR)."""
    try:
        frames = read(path, index=":")
    except Exception:
        frames = read(path, index=":", format="vasp")
    frame_list = frames if isinstance(frames, list) else [frames]
    return [sanitize_atoms_info(frame) for frame in frame_list]


def frame_metrics(atoms: Atoms) -> dict[str, Any]:
    """Atom count, formula, smallest contact ratio, largest vacuum gap along c and fixed-atom count."""
    from ase.constraints import FixAtoms

    periodic = bool(atoms.pbc.any()) and atoms.cell.rank == 3
    metrics: dict[str, Any] = {"n_atoms": len(atoms), "formula": atoms.get_chemical_formula(mode="hill")}
    if len(atoms) > 1:
        distances = atoms.get_all_distances(mic=periodic)
        radii = covalent_radii[atoms.numbers]
        ratio = distances / (radii[:, None] + radii[None, :])
        np.fill_diagonal(ratio, np.inf)
        metrics["min_contact_ratio"] = round(float(ratio.min()), 4)
    if periodic:
        height = float(np.linalg.norm(atoms.cell.array[2]))
        z = np.sort(np.mod(atoms.get_scaled_positions(wrap=True)[:, 2], 1.0))
        gaps = np.diff(np.concatenate([z, [z[0] + 1.0]])) * height
        metrics["vacuum_gap_A"] = round(float(gaps.max()), 3)
    metrics["n_fixed"] = sum(len(c.get_indices()) for c in atoms.constraints if isinstance(c, FixAtoms))
    return metrics
