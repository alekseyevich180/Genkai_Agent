from __future__ import annotations

import argparse
import io
import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.data import covalent_radii
from ase.filters import ExpCellFilter, StrainFilter
from ase.io import read, write
from ase.optimize import LBFGS

from ..mlip.calculators import molecule_in_box
from ..mlip.search_sampler import add_sampler_argument, make_sampler
from ..structure_io import label_components, sanitize_atoms_info, write_frames


CALCULATOR = None


def normalize_symbols(symbols: list[str] | None) -> list[str]:
    if not symbols:
        return []

    normalized = []
    for symbol in symbols:
        cleaned = symbol.strip().strip(",")
        if not cleaned:
            continue
        normalized.append(cleaned[0].upper() + cleaned[1:].lower())
    return normalized


def format_symbol_counts(atoms: Atoms) -> str:
    counts = Counter(atoms.get_chemical_symbols())
    return ", ".join(f"{symbol}:{counts[symbol]}" for symbol in sorted(counts))


def write_run_config(output_dir: Path, args: argparse.Namespace) -> Path:
    """Record the calculator settings (model, UMA task head, device) used for this run."""
    config = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    path = output_dir / "run_config.json"
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def build_calculator(
    uma_model: str,
    device: str,
    include_d3: bool,
    checkpoint: Path | None = None,
    task_name: str = "omat",
    *, calculator_name: str = "uma", mace_model: str | None = None, mace_dtype: str = "float32",
):
    from ..mlip.calculators import build_calculator as build_energy_model

    return build_energy_model(
        calculator_name, uma_model=uma_model, device=device, task_name=task_name,
        include_d3=include_d3, checkpoint=str(checkpoint) if checkpoint is not None else None,
        mace_model=mace_model, mace_dtype=mace_dtype,
    )


def get_opt_energy(
    atoms: Atoms,
    calculator,
    fmax: float = 1e-3,
    opt_mode: str = "normal",
    max_steps: int | None = None,
) -> float:
    sanitize_atoms_info(atoms)
    atoms.calc = calculator
    if opt_mode == "scale":
        optimizer = LBFGS(StrainFilter(atoms, mask=[1, 1, 1, 0, 0, 0]), logfile=None)
    elif opt_mode == "all":
        optimizer = LBFGS(ExpCellFilter(atoms), logfile=None)
    else:
        optimizer = LBFGS(atoms, logfile=None)
    optimizer.run(fmax=fmax, steps=max_steps)
    return atoms.get_total_energy()


def atoms_to_json(atoms: Atoms) -> str:
    """Serialize for Optuna user attributes; extxyz keeps FixAtoms, tags and component labels."""
    clean = atoms.copy()
    clean.calc = None
    buffer = io.StringIO()
    write(buffer, clean, format="extxyz")
    return buffer.getvalue()


def json_to_atoms(atoms_str: str) -> Atoms:
    fmt = "json" if atoms_str.lstrip().startswith("{") else "extxyz"
    return read(io.StringIO(atoms_str), format=fmt)


def get_geometric_center(atoms: Atoms) -> np.ndarray:
    return np.mean(atoms.positions, axis=0)


def ensure_headroom(slab: Atoms, needed_height: float) -> tuple[Atoms, bool]:
    """Lengthen c (keeping its direction) so the cell is at least ``needed_height`` tall along z."""
    cell = slab.cell.array.copy()
    height = float(cell[2, 2])
    if height >= needed_height:
        return slab, False
    cell[2] = cell[2] * (needed_height / height)
    slab.set_cell(cell, scale_atoms=False)
    return slab, True


def load_slab(
    surface_path: Path,
    calculator,
    fmax: float,
    max_steps: int | None,
    fixed_fraction: float = 0.5,
    headroom: float = 0.0,
) -> tuple[Atoms, float]:
    """Read, fix the bottom if needed, make room above the slab, then relax (all before any trial).

    ``headroom`` is the space needed above the slab top (largest gap + cluster
    diameter + vacuum); without it a large cluster can approach the periodic
    image of the slab bottom.
    """
    from ..builders.substrate import ensure_fixed_bottom

    slab, source = ensure_fixed_bottom(read(surface_path), fixed_fraction)
    print(f"Slab constraints: {source}")
    if headroom > 0:
        slab, extended = ensure_headroom(slab, float(slab.positions[:, 2].max()) + headroom)
        if extended:
            print(f"Cell lengthened along c to {slab.cell.array[2, 2]:.2f} A (z) for the cluster and vacuum.")
    energy = get_opt_energy(slab, calculator, fmax=fmax, opt_mode="normal", max_steps=max_steps)
    return slab, energy


def get_active_indices(
    atoms: Atoms, active_symbols: list[str], structure_path: Path | None = None
) -> list[int]:
    active_symbol_set = set(normalize_symbols(active_symbols))
    indices = [idx for idx, atom in enumerate(atoms) if atom.symbol in active_symbol_set]
    if not indices:
        available_symbols = sorted(set(atoms.get_chemical_symbols()))
        hint = ""
        if structure_path is not None and structure_path.suffix.lower() in {".vasp", ".poscar", ".contcar"}:
            hint = (
                " Hint: VASP/POSCAR files do not store element labels per atom. "
                "If you replaced atoms in the slab, you must also update the species/count header "
                "and regroup atoms by element so ASE reads the modified species correctly."
            )
        raise ValueError(
            "No active-site atoms found for symbols: "
            f"{', '.join(active_symbol_set)}. "
            f"Available symbols in slab: {', '.join(available_symbols)}. "
            f"Symbol counts: {format_symbol_counts(atoms)}."
            f"{hint}"
        )
    return indices


def _parse_frac_range(text: str | None, name: str) -> tuple[float, float]:
    """Parse ``lo,hi`` fractional bounds with ``0 <= lo < hi <= 1``."""
    if text is None:
        return (0.0, 1.0)
    parts = [item.strip() for item in str(text).split(",") if item.strip()]
    if len(parts) != 2:
        raise ValueError(f"--{name} requires two comma-separated floats 'lo,hi' in [0, 1], got {text!r}.")
    lo, hi = float(parts[0]), float(parts[1])
    if not (0.0 <= lo < hi <= 1.0):
        raise ValueError(f"--{name} must satisfy 0 <= lo < hi <= 1, got ({lo}, {hi}).")
    return (lo, hi)


def load_clusters(
    cluster_path: Path,
    calculator,
    fmax: float,
    max_steps: int | None,
    placement_shape: str = "relaxed",
) -> tuple[list[Atoms], list[str], float]:
    """Load one or more cluster isomers (same composition), returning ``(shapes, seed_names, E_cluster_ref)``.

    When ``cluster_path`` holds multiple frames (e.g. a multi-isomer ``.extxyz``
    seed pool), every isomer is relaxed isolated in vacuum to determine the
    lowest isolated reference energy ``E_cluster_ref``, while the placed shape
    follows ``placement_shape`` (``"input"`` preserves 2D/bilayer/3D seeds).
    """
    frames = read(cluster_path, index=":")
    if isinstance(frames, Atoms):
        frames = [frames]
    if not frames:
        raise ValueError(f"Cluster file {cluster_path} contains no structures.")

    ref_comp = Counter(frames[0].get_chemical_symbols())
    for idx, frame in enumerate(frames[1:], start=1):
        if Counter(frame.get_chemical_symbols()) != ref_comp:
            raise ValueError(
                f"All frames in multi-isomer --cluster file must have the same composition "
                f"(frame 0 has {dict(ref_comp)}, frame {idx} has {dict(Counter(frame.get_chemical_symbols()))})."
            )

    placed_list: list[Atoms] = []
    seed_names: list[str] = []
    energies: list[float] = []
    for idx, raw in enumerate(frames):
        supplied = raw.copy()
        supplied.set_constraint()
        seed_name = str(raw.info.get("seed_name") or f"seed_{idx}")
        relaxed = supplied.copy()
        was_nonperiodic = (not all(relaxed.pbc)) or (relaxed.cell.rank < 3) or (relaxed.cell.volume < 1e-6)
        relaxed_eval = molecule_in_box(relaxed) if was_nonperiodic else relaxed
        energy = get_opt_energy(relaxed_eval, calculator, fmax=fmax, max_steps=max_steps)
        if placement_shape == "relaxed":
            chosen = Atoms(
                symbols=relaxed_eval.get_chemical_symbols(),
                positions=relaxed_eval.positions.copy(),
                pbc=False,
            )
            if "seed_name" in supplied.info:
                chosen.info["seed_name"] = supplied.info["seed_name"]
        else:
            chosen = supplied
        chosen.calc = None
        chosen.positions -= get_geometric_center(chosen)
        placed_list.append(chosen)
        seed_names.append(seed_name)
        energies.append(float(energy))
    return placed_list, seed_names, min(energies)


def load_cluster(
    cluster_path: Path,
    calculator,
    fmax: float,
    max_steps: int | None,
    placement_shape: str = "relaxed",
) -> tuple[Atoms, float]:
    """Reference energy of the fully relaxed isolated cluster, and the shape to place.

    ``placement_shape="input"`` places the cluster as supplied (e.g. an amorphous
    island cut from a bulk, which can deform strongly when relaxed alone in
    vacuum); the reference energy is still that of the relaxed isolated cluster.
    """
    clusters, _, energy = load_clusters(
        cluster_path, calculator, fmax=fmax, max_steps=max_steps, placement_shape=placement_shape
    )
    return clusters[0], energy


def estimate_bottom_plane_normal(cluster: Atoms, z_tolerance: float = 0.35) -> np.ndarray:
    positions = np.asarray(cluster.positions, dtype=float)
    if len(positions) < 3:
        return np.array([0.0, 0.0, 1.0])

    min_z = float(np.min(positions[:, 2]))
    bottom_mask = positions[:, 2] <= (min_z + z_tolerance)
    bottom_positions = positions[bottom_mask]
    if len(bottom_positions) < 3:
        sorted_indices = np.argsort(positions[:, 2])[: min(3, len(positions))]
        bottom_positions = positions[sorted_indices]
    if len(bottom_positions) < 3:
        return np.array([0.0, 0.0, 1.0])

    centered = bottom_positions - np.mean(bottom_positions, axis=0)
    _, _, vh = np.linalg.svd(centered, full_matrices=False)
    normal = vh[-1]
    norm = np.linalg.norm(normal)
    if norm < 1e-8:
        return np.array([0.0, 0.0, 1.0])
    normal = normal / norm
    if normal[2] < 0.0:
        normal = -normal
    return normal


def get_min_slab_cluster_distance(combined: Atoms, n_slab_atoms: int) -> float:
    if n_slab_atoms <= 0 or n_slab_atoms >= len(combined):
        return float("inf")
    if bool(np.any(combined.pbc)) and combined.cell.rank == 3:
        distances = combined.get_all_distances(mic=True)[:n_slab_atoms, n_slab_atoms:]
        return float(distances.min())
    slab_positions = combined.positions[:n_slab_atoms]
    cluster_positions = combined.positions[n_slab_atoms:]
    deltas = slab_positions[:, None, :] - cluster_positions[None, :, :]
    return float(np.linalg.norm(deltas, axis=2).min())


def evaluate_cluster_morphology(
    combined: Atoms,
    n_slab_atoms: int,
    *,
    detach_cutoff: float,
    bond_scale: float = 1.30,
) -> dict[str, float | int]:
    """Compute periodic-aware anchoring, cohesion, and patch-geometry metrics for the supported cluster."""
    n_total = len(combined)
    n_cluster = n_total - n_slab_atoms
    if n_slab_atoms <= 0 or n_cluster <= 0:
        return {
            "min_slab_cluster_distance": float("inf"),
            "n_anchor_atoms": 0,
            "n_components": 0,
            "avg_cluster_cn": 0.0,
            "cluster_z_span": 0.0,
            "cluster_xy_span": 0.0,
        }

    use_mic = bool(np.any(combined.pbc)) and combined.cell.rank == 3
    all_dist = combined.get_all_distances(mic=use_mic)
    slab_cluster = all_dist[:n_slab_atoms, n_slab_atoms:]
    per_atom_slab_dist = slab_cluster.min(axis=0)
    min_distance = float(per_atom_slab_dist.min())
    n_anchor_atoms = int(np.sum(per_atom_slab_dist <= detach_cutoff))

    cluster_dist = all_dist[n_slab_atoms:, n_slab_atoms:]
    cluster_numbers = combined.numbers[n_slab_atoms:]
    radii = covalent_radii[cluster_numbers]
    bond_cutoffs = bond_scale * (radii[:, None] + radii[None, :])
    adj = (cluster_dist <= bond_cutoffs) & (~np.eye(n_cluster, dtype=bool))
    avg_cn = float(adj.sum(axis=1).mean()) if n_cluster > 1 else 0.0

    visited = [False] * n_cluster
    n_components = 0
    for start in range(n_cluster):
        if visited[start]:
            continue
        n_components += 1
        stack = [start]
        visited[start] = True
        while stack:
            node = stack.pop()
            for nbr in np.flatnonzero(adj[node]):
                idx = int(nbr)
                if not visited[idx]:
                    visited[idx] = True
                    stack.append(idx)

    cluster_pos = combined.positions[n_slab_atoms:]
    z_span = float(np.ptp(cluster_pos[:, 2])) if n_cluster > 1 else 0.0
    if n_cluster > 1:
        if use_mic:
            vecs = combined.get_distances(n_slab_atoms, range(n_slab_atoms, n_total), mic=True, vector=True)
            xy = vecs[:, :2]
        else:
            xy = cluster_pos[:, :2]
        xy_span = float(np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2).max())
    else:
        xy_span = 0.0

    return {
        "min_slab_cluster_distance": min_distance,
        "n_anchor_atoms": n_anchor_atoms,
        "n_components": n_components,
        "avg_cluster_cn": avg_cn,
        "cluster_z_span": z_span,
        "cluster_xy_span": xy_span,
    }


def check_cluster_morphology(
    metrics: dict[str, float | int],
    *,
    detach_cutoff: float,
    min_anchor_atoms: int = 1,
    require_connected: bool = False,
    max_cluster_height: float | None = None,
) -> tuple[bool, float]:
    """Check whether a supported cluster satisfies adhesion, cohesion, and height constraints."""
    min_dist = float(metrics["min_slab_cluster_distance"])
    n_anchor = int(metrics["n_anchor_atoms"])
    n_comp = int(metrics["n_components"])
    z_span = float(metrics["cluster_z_span"])

    violation = 0.0
    detached = min_dist > detach_cutoff
    if detached:
        violation += (min_dist - detach_cutoff) + 10.0
    if n_anchor < min_anchor_atoms:
        violation += 5.0 * float(min_anchor_atoms - n_anchor)
    if require_connected and n_comp > 1:
        violation += 20.0 * float(n_comp - 1)
    if max_cluster_height is not None and z_span > max_cluster_height:
        violation += 2.0 * (z_span - max_cluster_height)

    ok = (
        (not detached)
        and (n_anchor >= min_anchor_atoms)
        and ((not require_connected) or (n_comp <= 1))
        and (max_cluster_height is None or z_span <= max_cluster_height)
    )
    return ok, violation


def place_cluster_on_slab(
    cluster: Atoms,
    slab: Atoms,
    trial: optuna.Trial,
    placement_mode: str,
    active_indices: list[int],
    site_radius: float,
    z_min: float,
    z_max: float,
    max_tilt: float = 0.0,
    x_range: tuple[float, float] = (0.0, 1.0),
    y_range: tuple[float, float] = (0.0, 1.0),
) -> Atoms:
    placed = cluster.copy()
    geometric_center = get_geometric_center(placed)
    bottom_normal = estimate_bottom_plane_normal(placed)
    spin_angle = trial.suggest_float("spin_angle", -180.0, 180.0)
    placed.rotate(spin_angle, v=bottom_normal, center=geometric_center)
    if max_tilt > 0.0:
        # Which face points down matters for irregular (e.g. amorphous) clusters:
        # tilt by up to max_tilt degrees about an in-plane axis of random direction.
        tilt = trial.suggest_float("tilt", 0.0, max_tilt)
        tilt_azimuth = np.radians(trial.suggest_float("tilt_azimuth", 0.0, 360.0))
        axis = [float(np.cos(tilt_azimuth)), float(np.sin(tilt_azimuth)), 0.0]
        placed.rotate(tilt, v=axis, center=geometric_center)

    slab_top_z = float(np.max(slab.positions[:, 2]))
    if placement_mode == "active":
        site_choice = trial.suggest_int("site_index", 0, len(active_indices) - 1)
        dx = trial.suggest_float("dx", -site_radius, site_radius)
        dy = trial.suggest_float("dy", -site_radius, site_radius)
        anchor_position = slab.positions[active_indices[site_choice]]
        x_pos = float(anchor_position[0] + dx)
        y_pos = float(anchor_position[1] + dy)
        reference_z = max(slab_top_z, float(anchor_position[2]))
    else:
        x_frac = trial.suggest_float("x_frac", x_range[0], x_range[1])
        y_frac = trial.suggest_float("y_frac", y_range[0], y_range[1])
        xy_position = np.matmul([x_frac, y_frac, 0.0], slab.cell.array)[:2]
        x_pos = float(xy_position[0])
        y_pos = float(xy_position[1])
        reference_z = slab_top_z

    z_gap = trial.suggest_float("z_gap", z_min, z_max)
    geometric_center = get_geometric_center(placed)
    min_cluster_z = float(np.min(placed.positions[:, 2]))
    placed.translate(
        [
            x_pos - float(geometric_center[0]),
            y_pos - float(geometric_center[1]),
            reference_z + z_gap - min_cluster_z,
        ]
    )
    return placed


def objective(trial: optuna.Trial) -> float:
    slab = json_to_atoms(trial.study.user_attrs["slab"])
    e_slab = float(trial.study.user_attrs["E_slab"])
    clusters_attr = trial.study.user_attrs.get("clusters")
    seed_names = list(trial.study.user_attrs.get("cluster_seed_names", ["seed_0"]))
    if clusters_attr and len(clusters_attr) > 1:
        cluster_index = trial.suggest_int("cluster_index", 0, len(clusters_attr) - 1)
        cluster = json_to_atoms(clusters_attr[cluster_index])
    else:
        cluster_index = 0
        cluster = json_to_atoms(trial.study.user_attrs["cluster"])
    seed_name = seed_names[cluster_index] if cluster_index < len(seed_names) else f"seed_{cluster_index}"

    e_cluster = float(trial.study.user_attrs["E_cluster"])
    placement_mode = str(trial.study.user_attrs["placement_mode"])
    active_indices = list(trial.study.user_attrs["active_indices"])
    site_radius = float(trial.study.user_attrs["site_radius"])
    z_min = float(trial.study.user_attrs["z_min"])
    z_max = float(trial.study.user_attrs["z_max"])
    detach_cutoff = float(trial.study.user_attrs["detach_cutoff"])
    min_anchor_atoms = int(trial.study.user_attrs.get("min_anchor_atoms", 1))
    require_connected = bool(trial.study.user_attrs.get("require_connected", False))
    cluster_bond_scale = float(trial.study.user_attrs.get("cluster_bond_scale", 1.30))
    max_cluster_height = trial.study.user_attrs.get("max_cluster_height", None)
    if max_cluster_height is not None:
        max_cluster_height = float(max_cluster_height)
    penalty_energy = float(trial.study.user_attrs["penalty_energy"])
    max_steps = int(trial.study.user_attrs.get("stage1_steps", trial.study.user_attrs["max_steps"]))
    fmax = float(trial.study.user_attrs.get("stage1_fmax", trial.study.user_attrs["fmax"]))
    max_tilt = float(trial.study.user_attrs.get("max_tilt", 0.0))
    x_range = tuple(float(v) for v in trial.study.user_attrs.get("x_range", (0.0, 1.0)))
    y_range = tuple(float(v) for v in trial.study.user_attrs.get("y_range", (0.0, 1.0)))

    placed_cluster = place_cluster_on_slab(
        cluster=cluster,
        slab=slab,
        trial=trial,
        placement_mode=placement_mode,
        active_indices=active_indices,
        site_radius=site_radius,
        z_min=z_min,
        z_max=z_max,
        max_tilt=max_tilt,
        x_range=x_range,
        y_range=y_range,
    )

    combined = slab + placed_cluster
    label_components(combined, "cluster", range(len(slab), len(combined)))
    e_total = get_opt_energy(combined, CALCULATOR, fmax=fmax, max_steps=max_steps)
    adsorption_energy = e_total - e_slab - e_cluster
    structure_json = atoms_to_json(combined)
    trial.set_user_attr("structure", structure_json)
    trial.set_user_attr("cluster_index", cluster_index)
    trial.set_user_attr("seed_name", seed_name)

    morph = evaluate_cluster_morphology(
        combined, len(slab), detach_cutoff=detach_cutoff, bond_scale=cluster_bond_scale
    )
    min_distance = float(morph["min_slab_cluster_distance"])
    detached = min_distance > detach_cutoff
    morph_ok, violation = check_cluster_morphology(
        morph,
        detach_cutoff=detach_cutoff,
        min_anchor_atoms=min_anchor_atoms,
        require_connected=require_connected,
        max_cluster_height=max_cluster_height,
    )
    trial.set_user_attr("min_slab_cluster_distance", min_distance)
    trial.set_user_attr("n_anchor_atoms", int(morph["n_anchor_atoms"]))
    trial.set_user_attr("n_components", int(morph["n_components"]))
    trial.set_user_attr("avg_cluster_cn", float(morph["avg_cluster_cn"]))
    trial.set_user_attr("cluster_z_span", float(morph["cluster_z_span"]))
    trial.set_user_attr("cluster_xy_span", float(morph["cluster_xy_span"]))
    trial.set_user_attr("detached", bool(detached))
    trial.set_user_attr("morphology_ok", bool(morph_ok))
    if not morph_ok:
        return penalty_energy + violation

    return adsorption_energy


def get_ranked_valid_trials(study: optuna.Study) -> list[optuna.trial.FrozenTrial]:
    morph_valid = []
    attached_only = []
    for trial in study.trials:
        if trial.value is None:
            continue
        if trial.user_attrs.get("detached", False):
            continue
        if "structure" not in trial.user_attrs:
            continue
        if trial.user_attrs.get("morphology_ok", True):
            morph_valid.append(trial)
        else:
            attached_only.append(trial)
    valid_trials = morph_valid if morph_valid else attached_only
    valid_trials.sort(key=lambda trial: float(trial.value))
    return valid_trials


def select_best_trial(study: optuna.Study) -> tuple[optuna.trial.FrozenTrial, bool]:
    """Return ``(best_trial, all_detached)``, preferring attached (non-detached) trials."""
    valid_trials = get_ranked_valid_trials(study)
    if valid_trials:
        return valid_trials[0], False
    return study.best_trial, True


def _cluster_fingerprint(atoms: Atoms, n_slab: int) -> np.ndarray:
    """Rotation/translation/permutation-invariant distance spectrum of the supported cluster."""
    all_dist = atoms.get_all_distances(mic=True)
    cluster_dist = all_dist[n_slab:, n_slab:]
    tri = cluster_dist[np.triu_indices(len(atoms) - n_slab, k=1)]
    slab_gap = all_dist[n_slab:, :n_slab].min(axis=1) if n_slab else np.array([], dtype=float)
    return np.concatenate([np.sort(tri), np.sort(slab_gap)])


def select_distinct_top_trials(
    ranked_trials: list[optuna.trial.FrozenTrial],
    n_slab: int,
    top_k: int,
    *,
    tol: float = 0.15,
) -> list[optuna.trial.FrozenTrial]:
    """Pick up to ``top_k`` lowest-energy distinct Stage-1 trials (backfilling if fewer distinct exist)."""
    if top_k < 1 or not ranked_trials:
        return []
    chosen: list[optuna.trial.FrozenTrial] = []
    seen_fps: list[np.ndarray] = []
    skipped: list[optuna.trial.FrozenTrial] = []
    for trial in ranked_trials:
        atoms = json_to_atoms(trial.user_attrs["structure"])
        fp = _cluster_fingerprint(atoms, n_slab)
        if all(len(fp) != len(ref) or float(np.max(np.abs(fp - ref))) > tol for ref in seen_fps):
            chosen.append(trial)
            seen_fps.append(fp)
            if len(chosen) >= top_k:
                return chosen
        else:
            skipped.append(trial)
    for trial in skipped:
        chosen.append(trial)
        if len(chosen) >= top_k:
            break
    return chosen


def refine_and_anneal_candidates(
    top_trials: list[optuna.trial.FrozenTrial],
    n_slab: int,
    e_slab: float,
    e_cluster: float,
    calculator,
    *,
    fmax: float,
    max_steps: int,
    detach_cutoff: float,
    min_anchor_atoms: int = 1,
    require_connected: bool = False,
    cluster_bond_scale: float = 1.30,
    max_cluster_height: float | None = None,
    anneal_steps: int = 0,
    anneal_temperature: float = 600.0,
    anneal_snapshots: int = 1,
    seed: int = 42,
    calculator_name: str = "uma",
) -> list[dict]:
    """Stage 2/3 refinement: full relaxation plus optional surface MD anneal-and-quench."""
    from ..mlip.calculators import anneal, is_mock

    results: list[dict] = []

    def _record_relaxed(atoms: Atoms, trial: optuna.trial.FrozenTrial, stage: str) -> dict:
        work = atoms.copy()
        work.set_momenta(np.zeros((len(work), 3)))
        e_total = get_opt_energy(work, calculator, fmax=fmax, max_steps=max_steps)
        forces = np.asarray(work.get_forces(), dtype=float)
        max_force = float(np.linalg.norm(forces, axis=1).max()) if len(forces) else 0.0
        morph = evaluate_cluster_morphology(
            work, n_slab, detach_cutoff=detach_cutoff, bond_scale=cluster_bond_scale
        )
        min_distance = float(morph["min_slab_cluster_distance"])
        detached = min_distance > detach_cutoff
        morph_ok, _ = check_cluster_morphology(
            morph,
            detach_cutoff=detach_cutoff,
            min_anchor_atoms=min_anchor_atoms,
            require_connected=require_connected,
            max_cluster_height=max_cluster_height,
        )
        e_ads = float(e_total - e_slab - e_cluster)
        clean = work.copy()
        clean.calc = None
        clean.set_momenta(np.zeros((len(clean), 3)))
        return {
            "source_trial": int(trial.number),
            "cluster_index": int(trial.user_attrs.get("cluster_index", 0)),
            "seed_name": str(trial.user_attrs.get("seed_name", "seed_0")),
            "stage": stage,
            "energy": e_ads,
            "E_total_eV": float(e_total),
            "min_slab_cluster_distance": float(min_distance),
            "detached": bool(detached),
            "morphology_ok": bool(morph_ok),
            "n_anchor_atoms": int(morph["n_anchor_atoms"]),
            "n_components": int(morph["n_components"]),
            "cluster_z_span_A": round(float(morph["cluster_z_span"]), 4),
            "cluster_xy_span_A": round(float(morph["cluster_xy_span"]), 4),
            "avg_cluster_cn": round(float(morph["avg_cluster_cn"]), 3),
            "max_force_eV_A": round(max_force, 6),
            "atoms": clean,
        }

    for idx, trial in enumerate(top_trials):
        base_atoms = json_to_atoms(trial.user_attrs["structure"])
        results.append(_record_relaxed(base_atoms, trial, "direct"))

        if anneal_steps > 0 and not is_mock(calculator_name):
            n_snaps = max(1, int(anneal_snapshots))
            seg_steps = max(1, int(round(anneal_steps / n_snaps)))
            end_temp = min(float(anneal_temperature), 300.0)
            temps = (
                [float(anneal_temperature)]
                if n_snaps == 1
                else [float(t) for t in np.linspace(float(anneal_temperature), end_temp, n_snaps)]
            )
            md_atoms = base_atoms.copy()
            for snap_idx, temp in enumerate(temps, start=1):
                anneal(
                    md_atoms,
                    calculator,
                    temperature=temp,
                    steps=seg_steps,
                    seed=int(seed) + 1000 * idx + 10 * snap_idx,
                )
                results.append(_record_relaxed(md_atoms, trial, f"anneal_snap_{snap_idx}"))

    results.sort(key=lambda item: (not item["morphology_ok"], item["detached"], item["energy"]))
    return results


def select_trials_for_dft(
    ranked_trials: list[optuna.trial.FrozenTrial],
    top_pool_size: int,
    top_pick_count: int,
    tail_bin_size: int,
    tail_pick_per_bin: int,
    final_selection_count: int,
    seed: int,
) -> list[dict]:
    if final_selection_count < 1:
        raise ValueError("--selection_count must be >= 1.")
    if top_pool_size < 0:
        raise ValueError("--top_pool_size must be >= 0.")
    if top_pick_count < 0:
        raise ValueError("--top_pick_count must be >= 0.")
    if tail_bin_size < 1:
        raise ValueError("--tail_bin_size must be >= 1.")
    if tail_pick_per_bin < 0:
        raise ValueError("--tail_pick_per_bin must be >= 0.")

    rng = random.Random(seed)
    top_pool = ranked_trials[:top_pool_size]
    if top_pick_count > len(top_pool):
        raise ValueError(
            f"Requested {top_pick_count} top-pool picks, but only {len(top_pool)} valid trials are available."
        )
    if final_selection_count < top_pick_count:
        raise ValueError(
            "--selection_count must be >= --top_pick_count so the top-pool picks can always be retained."
        )

    top_selected = rng.sample(top_pool, top_pick_count) if top_pick_count else []
    top_selected_by_number = {trial.number: trial for trial in top_selected}

    tail_trials = ranked_trials[top_pool_size:]
    tail_selected: list[tuple[optuna.trial.FrozenTrial, int, int]] = []
    if tail_pick_per_bin:
        for bin_start in range(0, len(tail_trials), tail_bin_size):
            bin_end = min(bin_start + tail_bin_size, len(tail_trials))
            tail_bin = tail_trials[bin_start:bin_end]
            if not tail_bin:
                continue
            picks = min(tail_pick_per_bin, len(tail_bin))
            for trial in rng.sample(tail_bin, picks):
                tail_selected.append((trial, top_pool_size + bin_start + 1, top_pool_size + bin_end))

    selected_tail_count = max(0, final_selection_count - len(top_selected))
    if selected_tail_count > len(tail_selected):
        raise ValueError(
            "Not enough tail candidates to satisfy the requested selection count. "
            "Adjust the selection parameters or increase --n_trials."
        )

    chosen_tail = rng.sample(tail_selected, selected_tail_count) if selected_tail_count else []

    selected_rows = []
    for trial in sorted(top_selected, key=lambda item: float(item.value)):
        selected_rows.append(
            {
                "trial": trial,
                "selection_group": "top_pool",
                "rank_range": f"1-{top_pool_size}",
            }
        )
    for trial, rank_start, rank_end in sorted(chosen_tail, key=lambda item: float(item[0].value)):
        if trial.number in top_selected_by_number:
            continue
        selected_rows.append(
            {
                "trial": trial,
                "selection_group": "tail_bin",
                "rank_range": f"{rank_start}-{rank_end}",
            }
        )

    selected_rows.sort(key=lambda item: float(item["trial"].value))
    return selected_rows


def export_selected_candidates(
    selected_trials: list[dict],
    mlip_output_dir: Path,
    vasp_dir: Path,
) -> None:
    for index, item in enumerate(selected_trials, start=1):
        trial = item["trial"]
        structure = json_to_atoms(trial.user_attrs["structure"])
        cif_path = mlip_output_dir / f"{index:02d}_trial_{trial.number:03d}.cif"
        write(cif_path, structure)

        write(vasp_dir / f"{index}.vasp", structure, format="vasp", direct=True, sort=True, vasp5=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search stable adsorption structures for a prebuilt cluster on a surface using Optuna."
    )
    parser.add_argument("--surface", type=Path, required=True, help="Surface structure file readable by ASE.")
    parser.add_argument("--cluster", type=Path, required=True, help="Prebuilt cluster structure readable by ASE.")
    parser.add_argument("--output_dir", type=Path, default=Path("output_nanocluster"))
    parser.add_argument("--n_trials", type=int, default=100)
    parser.add_argument("--fmax", type=float, default=1e-4)
    from ..mlip.calculators import CALCULATORS, add_mace_arguments

    parser.add_argument(
        "--calculator",
        choices=CALCULATORS,
        default="uma",
        help="uma/mace: real MLIP search; emt: empirical metal test potential; none: mock contact score for workflow tests only.",
    )
    parser.add_argument("--uma_model", type=str, default="uma-s-1p2")

    add_mace_arguments(parser)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument(
        "--task_name",
        type=str,
        default="omat",
        help="UMA task head passed to FAIRChemCalculator; checked against the installed fairchem before loading "
        "(fairchem 2.7.1 has omol, omat, odac, oc20, oc25, omc - no oc22).",
    )
    parser.add_argument(
        "--fixed_fraction",
        type=float,
        default=0.5,
        help="Fix slab atoms below this fraction of the thickness when the file has no FixAtoms (CIF); 0 disables.",
    )
    parser.add_argument(
        "--max_tilt",
        type=float,
        default=0.0,
        help="Also search a tilt of the cluster up to this angle (deg) about a random in-plane axis; 0 = spin only.",
    )
    parser.add_argument(
        "--placement_shape",
        choices=["relaxed", "input"],
        default="relaxed",
        help="Shape placed on the slab: the relaxed isolated cluster, or the input as supplied (amorphous islands). "
        "The reference energy always comes from the relaxed isolated cluster.",
    )
    parser.add_argument("--device", type=str, default="cuda", choices=["cuda", "cpu"])
    parser.add_argument(
        "--placement_mode",
        type=str,
        default="cell",
        choices=["cell", "active"],
        help="cell: scan the full surface cell; active: scan near selected surface atoms.",
    )
    parser.add_argument("--active_symbols", nargs="+", default=None)
    parser.add_argument("--site_radius", type=float, default=2.5)
    parser.add_argument("--z_min", type=float, default=1.5, help="Minimum initial cluster-surface gap in Angstrom.")
    parser.add_argument("--z_max", type=float, default=4.5, help="Maximum initial cluster-surface gap in Angstrom.")
    parser.add_argument(
        "--min_vacuum",
        type=float,
        default=10.0,
        help="Vacuum kept above the highest possible cluster position; c is lengthened before the slab relaxation.",
    )
    parser.add_argument("--detach_cutoff", type=float, default=6.0)
    parser.add_argument(
        "--min_anchor_atoms",
        type=int,
        default=1,
        help="Minimum number of cluster atoms within --detach_cutoff of the slab (default: 1).",
    )
    parser.add_argument(
        "--require_connected",
        action="store_true",
        help="Reject fragmented/dispersing clusters that break into >1 connected metal component.",
    )
    parser.add_argument(
        "--cluster_bond_scale",
        type=float,
        default=1.30,
        help="Covalent-radius multiplier defining M-M connectivity for morphology checks (default: 1.30).",
    )
    parser.add_argument(
        "--max_cluster_height",
        type=float,
        default=None,
        help="Optional maximum allowed cluster vertical z-span in Angstrom (rejects tall upright needles).",
    )
    parser.add_argument("--penalty_energy", type=float, default=1e6)
    parser.add_argument("--max_steps", type=int, default=200)
    parser.add_argument(
        "--screen_steps",
        type=int,
        default=None,
        help="Optional Stage-1 fast screening LBFGS steps per trial; top candidates are refined with --max_steps.",
    )
    parser.add_argument(
        "--screen_fmax",
        type=float,
        default=None,
        help="Force threshold (eV/A) during Stage-1 screening (default: max(fmax, 0.10) when --screen_steps is set).",
    )
    parser.add_argument(
        "--refine_top_k",
        type=int,
        default=0,
        help="Number of distinct Stage-1 candidates refined in Stage 2/3 (0 = auto when funnel/anneal is enabled).",
    )
    parser.add_argument(
        "--anneal_steps",
        type=int,
        default=0,
        help="Surface Langevin MD annealing steps per top candidate before final relaxation (0 disables).",
    )
    parser.add_argument(
        "--anneal_temperature",
        type=float,
        default=600.0,
        help="Starting temperature (K) for surface MD annealing (ramps down toward 300 K across snapshots).",
    )
    parser.add_argument(
        "--anneal_snapshots",
        type=int,
        default=1,
        help="Number of quench-relaxed snapshots taken along each annealing trajectory.",
    )
    parser.add_argument(
        "--x_range",
        type=str,
        default=None,
        help="Fractional x_frac bounds 'lo,hi' in [0,1] (e.g. '0,0.5' for a 2x supercell irreducible unit cell).",
    )
    parser.add_argument(
        "--y_range",
        type=str,
        default=None,
        help="Fractional y_frac bounds 'lo,hi' in [0,1] (e.g. '0,0.3333' for a 3x supercell irreducible unit cell).",
    )
    parser.add_argument("--include_d3", action="store_true")
    parser.add_argument("--candidate_pool_size", type=int, default=100)
    parser.add_argument("--selection_count", type=int, default=10)
    parser.add_argument("--top_pool_size", type=int, default=10)
    parser.add_argument("--top_pick_count", type=int, default=6)
    parser.add_argument("--tail_bin_size", type=int, default=10)
    parser.add_argument("--tail_pick_per_bin", type=int, default=1)
    parser.add_argument("--selection_random_seed", type=int, default=42)
    parser.add_argument("--seed", type=int, default=None, help="Optuna sampler seed (default: random).")
    add_sampler_argument(parser)
    return parser


def main(argv: list[str] | None = None):
    global CALCULATOR

    import optuna
    import pandas as pd

    args = _build_parser().parse_args(argv)

    if args.calculator == "mace":
        from ..mlip.calculators import resolve_mace_model

        args.mace_model = resolve_mace_model(args.mace_model)
    args.active_symbols = normalize_symbols(args.active_symbols)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.placement_mode == "active" and not args.active_symbols:
        raise ValueError("--placement_mode active requires --active_symbols.")

    write_run_config(args.output_dir, args)
    if args.calculator == "none":
        from ..mlip.calculators import MOCK_NOTE, ContactMockCalculator

        print(f"WARNING {MOCK_NOTE}")
        CALCULATOR = ContactMockCalculator()
    else:
        if args.calculator == "mace":
            print(f"MACE model: {args.mace_model}, dtype: {args.mace_dtype}, device: {args.device}")
        elif args.calculator == "emt":
            print("EMT empirical potential (test only)")
        else:
            print(f"UMA model: {args.checkpoint or args.uma_model}, task: {args.task_name}, device: {args.device}")
        CALCULATOR = build_calculator(
            args.uma_model,
            args.device,
            args.include_d3,
            args.checkpoint,
            task_name=args.task_name,
            calculator_name=args.calculator,
            mace_model=args.mace_model,
            mace_dtype=args.mace_dtype,
        )
    x_range = _parse_frac_range(args.x_range, "x_range")
    y_range = _parse_frac_range(args.y_range, "y_range")
    if args.anneal_steps < 0:
        raise ValueError("--anneal_steps must be >= 0.")
    if args.anneal_snapshots < 1:
        raise ValueError("--anneal_snapshots must be >= 1.")
    if args.screen_steps is not None and args.screen_steps < 0:
        raise ValueError("--screen_steps must be >= 0.")
    if args.min_anchor_atoms < 1:
        raise ValueError("--min_anchor_atoms must be >= 1.")
    if args.cluster_bond_scale <= 0.0:
        raise ValueError("--cluster_bond_scale must be > 0.")
    if args.max_cluster_height is not None and args.max_cluster_height <= 0.0:
        raise ValueError("--max_cluster_height must be > 0.")

    input_surface = read(args.surface)
    input_clusters_raw = read(args.cluster, index=":")
    if isinstance(input_clusters_raw, Atoms):
        input_clusters_raw = [input_clusters_raw]
    input_cluster = input_clusters_raw[0]

    diameter = 0.0
    for raw_c in input_clusters_raw:
        centred = raw_c.positions - raw_c.positions.mean(axis=0)
        if len(raw_c) > 1:
            diameter = max(diameter, 2.0 * float(np.linalg.norm(centred, axis=1).max()))
    print(f"Loading and relaxing surface: {args.surface}")
    slab, e_slab = load_slab(
        args.surface,
        CALCULATOR,
        args.fmax,
        args.max_steps,
        args.fixed_fraction,
        headroom=args.z_max + diameter + args.min_vacuum,
    )
    print(f"Surface symbols: {format_symbol_counts(slab)}")
    print(f"Relaxed slab energy: {e_slab:.6f} eV")

    active_indices: list[int] = []
    if args.placement_mode == "active":
        active_indices = get_active_indices(slab, args.active_symbols, args.surface)
        print(f"Active symbols: {', '.join(args.active_symbols)}")
        print(f"Number of active atoms: {len(active_indices)}")
    else:
        print(f"Placement mode: cell scan x={x_range}, y={y_range}")

    print(f"\nLoading cluster(s): {args.cluster}\n")
    clusters, seed_names, e_cluster = load_clusters(
        cluster_path=args.cluster,
        calculator=CALCULATOR,
        fmax=args.fmax,
        max_steps=args.max_steps,
        placement_shape=args.placement_shape,
    )
    cluster = clusters[0]
    print(
        f"Cluster seeds: {len(clusters)} ({', '.join(seed_names)}), "
        f"atoms: {len(cluster)} (placed shape: {args.placement_shape})"
    )
    print(f"Cluster symbols: {format_symbol_counts(cluster)}")
    print(f"Relaxed cluster reference energy: {e_cluster:.6f} eV")

    structure_output_dir = args.output_dir / "mlip_output"
    structure_output_dir.mkdir(parents=True, exist_ok=True)
    vasp_dir = args.output_dir / "vasp"
    vasp_dir.mkdir(parents=True, exist_ok=True)
    write(structure_output_dir / "initial_surface.cif", input_surface)
    write(structure_output_dir / "initial_cluster.cif", input_cluster)

    stage1_steps = args.screen_steps if args.screen_steps is not None else args.max_steps
    stage1_fmax = (
        args.screen_fmax
        if args.screen_fmax is not None
        else (max(args.fmax, 0.10) if args.screen_steps is not None else args.fmax)
    )
    use_refinement = (args.screen_steps is not None) or (args.anneal_steps > 0) or (args.refine_top_k > 0)

    sampler = make_sampler(
        args.sampler, seed=args.seed, periodic=("spin_angle", "tilt_azimuth", "x_frac", "y_frac"),
        categorical=("site_index", "cluster_index"),
    )
    study = optuna.create_study(direction="minimize", sampler=sampler)
    study.set_user_attr("max_tilt", args.max_tilt)
    study.set_user_attr("slab", atoms_to_json(slab))
    study.set_user_attr("E_slab", e_slab)
    study.set_user_attr("cluster", atoms_to_json(cluster))
    study.set_user_attr("clusters", [atoms_to_json(c) for c in clusters])
    study.set_user_attr("cluster_seed_names", seed_names)
    study.set_user_attr("E_cluster", e_cluster)
    study.set_user_attr("placement_mode", args.placement_mode)
    study.set_user_attr("active_indices", active_indices)
    study.set_user_attr("site_radius", args.site_radius)
    study.set_user_attr("z_min", args.z_min)
    study.set_user_attr("z_max", args.z_max)
    study.set_user_attr("x_range", list(x_range))
    study.set_user_attr("y_range", list(y_range))
    study.set_user_attr("detach_cutoff", args.detach_cutoff)
    study.set_user_attr("min_anchor_atoms", args.min_anchor_atoms)
    study.set_user_attr("require_connected", args.require_connected)
    study.set_user_attr("cluster_bond_scale", args.cluster_bond_scale)
    study.set_user_attr("max_cluster_height", args.max_cluster_height)
    study.set_user_attr("penalty_energy", args.penalty_energy)
    study.set_user_attr("max_steps", args.max_steps)
    study.set_user_attr("fmax", args.fmax)
    study.set_user_attr("stage1_steps", stage1_steps)
    study.set_user_attr("stage1_fmax", stage1_fmax)
    study.optimize(objective, n_trials=args.n_trials)

    energy_rows = []
    for trial in study.trials:
        energy_rows.append(
            {
                "trial": trial.number,
                "energy": trial.value,
                "detached": trial.user_attrs.get("detached", False),
                "morphology_ok": trial.user_attrs.get("morphology_ok", True),
                "min_slab_cluster_distance": trial.user_attrs.get("min_slab_cluster_distance"),
                "n_anchor_atoms": trial.user_attrs.get("n_anchor_atoms"),
                "n_components": trial.user_attrs.get("n_components"),
                "cluster_z_span_A": trial.user_attrs.get("cluster_z_span"),
                "cluster_xy_span_A": trial.user_attrs.get("cluster_xy_span"),
                "avg_cluster_cn": trial.user_attrs.get("avg_cluster_cn"),
                "cluster_index": trial.user_attrs.get("cluster_index", 0),
                "seed_name": trial.user_attrs.get("seed_name", seed_names[0]),
                "x_frac": trial.params.get("x_frac"),
                "y_frac": trial.params.get("y_frac"),
            }
        )
    pd.DataFrame(energy_rows).to_csv(structure_output_dir / "mlip_energy_table.csv", index=False)

    ranked_trials = get_ranked_valid_trials(study)[: args.candidate_pool_size]

    if use_refinement and ranked_trials:
        refine_k = args.refine_top_k if args.refine_top_k > 0 else max(args.selection_count, args.top_pick_count, 1)
        distinct_top = select_distinct_top_trials(ranked_trials, len(slab), refine_k)
        print(
            f"\nStage 2/3 refinement on {len(distinct_top)} distinct Stage-1 candidates "
            f"(max_steps={args.max_steps}, fmax={args.fmax}, anneal_steps={args.anneal_steps}, "
            f"T={args.anneal_temperature} K, snapshots={args.anneal_snapshots})..."
        )
        refined = refine_and_anneal_candidates(
            distinct_top,
            len(slab),
            e_slab,
            e_cluster,
            CALCULATOR,
            fmax=args.fmax,
            max_steps=args.max_steps,
            detach_cutoff=args.detach_cutoff,
            min_anchor_atoms=args.min_anchor_atoms,
            require_connected=args.require_connected,
            cluster_bond_scale=args.cluster_bond_scale,
            max_cluster_height=args.max_cluster_height,
            anneal_steps=args.anneal_steps,
            anneal_temperature=args.anneal_temperature,
            anneal_snapshots=args.anneal_snapshots,
            seed=args.seed if args.seed is not None else args.selection_random_seed,
            calculator_name=args.calculator,
        )
        refined_rows = [
            {
                "rank": rank,
                "source_trial": item["source_trial"],
                "cluster_index": item["cluster_index"],
                "seed_name": item["seed_name"],
                "stage": item["stage"],
                "energy": item["energy"],
                "E_total_eV": item["E_total_eV"],
                "detached": item["detached"],
                "morphology_ok": item["morphology_ok"],
                "min_slab_cluster_distance": item["min_slab_cluster_distance"],
                "n_anchor_atoms": item["n_anchor_atoms"],
                "n_components": item["n_components"],
                "cluster_z_span_A": item["cluster_z_span_A"],
                "cluster_xy_span_A": item["cluster_xy_span_A"],
                "avg_cluster_cn": item["avg_cluster_cn"],
                "max_force_eV_A": item["max_force_eV_A"],
            }
            for rank, item in enumerate(refined, start=1)
        ]
        pd.DataFrame(refined_rows).to_csv(structure_output_dir / "mlip_refined_table.csv", index=False)

        morph_refined = [item for item in refined if item["morphology_ok"]]
        attached_refined = [item for item in refined if not item["detached"]]
        if morph_refined:
            best_item = morph_refined[0]
            export_pool = morph_refined
            all_detached = False
        elif attached_refined:
            best_item = attached_refined[0]
            export_pool = attached_refined
            all_detached = False
            print(
                "WARNING: No refined cluster_search structure satisfied all morphology filters; "
                "falling back to lowest-energy attached candidate."
            )
        else:
            best_item = refined[0]
            export_pool = refined
            all_detached = True
            print(
                "WARNING: Every refined cluster_search structure detached (> detach_cutoff); "
                "falling back to lowest-energy refined candidate for mlip_best_structure."
            )

        best_structure = best_item["atoms"]
        write(structure_output_dir / "mlip_best_structure.cif", best_structure)
        best_frame = best_structure.copy()
        best_frame.calc = None
        best_frame.info = {
            "task": "cluster_search",
            "role": "best_cluster_on_slab",
            "trial": int(best_item["source_trial"]),
            "stage": str(best_item["stage"]),
            "seed_name": str(best_item["seed_name"]),
            "energy_eV": float(best_item["energy"]),
            "detached": bool(best_item["detached"]),
            "morphology_ok": bool(best_item["morphology_ok"]),
            "n_anchor_atoms": int(best_item["n_anchor_atoms"]),
            "n_components": int(best_item["n_components"]),
        }
        write_frames(structure_output_dir / "mlip_best_structure.extxyz", [best_frame])

        ranked_frames: list[Atoms] = []
        for rank, item in enumerate(export_pool[: args.candidate_pool_size], start=1):
            frame = item["atoms"].copy()
            frame.calc = None
            frame.info = {
                "task": "cluster_search",
                "role": "cluster_on_slab_ranked",
                "rank": rank,
                "trial": int(item["source_trial"]),
                "stage": str(item["stage"]),
                "seed_name": str(item["seed_name"]),
                "energy_eV": float(item["energy"]),
                "morphology_ok": bool(item["morphology_ok"]),
            }
            ranked_frames.append(frame)
        if ranked_frames:
            write_frames(structure_output_dir / "cluster_search_structures.extxyz", ranked_frames)

        for index, item in enumerate(export_pool[: args.selection_count], start=1):
            struct = item["atoms"]
            cif_path = structure_output_dir / f"{index:02d}_trial_{item['source_trial']:03d}.cif"
            write(cif_path, struct)
            write(vasp_dir / f"{index}.vasp", struct, format="vasp", direct=True, sort=True, vasp5=True)
    else:
        best_trial, all_detached = select_best_trial(study)
        if all_detached:
            print(
                "WARNING: Every cluster_search trial detached (> detach_cutoff); "
                "falling back to the global best trial for mlip_best_structure."
            )
        best_structure = json_to_atoms(best_trial.user_attrs["structure"])
        write(structure_output_dir / "mlip_best_structure.cif", best_structure)
        best_frame = best_structure.copy()
        best_frame.calc = None
        best_frame.info = {
            "task": "cluster_search",
            "role": "best_cluster_on_slab",
            "trial": int(best_trial.number),
            "energy_eV": float(best_trial.value),
            "detached": bool(best_trial.user_attrs.get("detached", False)),
        }
        write_frames(structure_output_dir / "mlip_best_structure.extxyz", [best_frame])

        ranked_frames = []
        for rank, trial in enumerate(ranked_trials, start=1):
            frame = json_to_atoms(trial.user_attrs["structure"])
            frame.calc = None
            frame.info = {
                "task": "cluster_search",
                "role": "cluster_on_slab_ranked",
                "rank": rank,
                "trial": int(trial.number),
                "energy_eV": float(trial.value),
            }
            ranked_frames.append(frame)
        if ranked_frames:
            write_frames(structure_output_dir / "cluster_search_structures.extxyz", ranked_frames)

        selected_trials = select_trials_for_dft(
            ranked_trials=ranked_trials,
            top_pool_size=args.top_pool_size,
            top_pick_count=args.top_pick_count,
            tail_bin_size=args.tail_bin_size,
            tail_pick_per_bin=args.tail_pick_per_bin,
            final_selection_count=args.selection_count,
            seed=args.selection_random_seed,
        )
        export_selected_candidates(selected_trials, structure_output_dir, vasp_dir)

    print(f"Selected MLIP structures written to {structure_output_dir}")
    print(f"VASP inputs written to {vasp_dir}")
    return 0


if __name__ == "__main__":
    main()
