from pathlib import Path

import numpy as np
from ase import Atoms
from ase.build import bulk
from ase.data import atomic_numbers, reference_states
from ase.io import read

# ---------------------------------------------------------------------------
# Element and lattice helpers
# ---------------------------------------------------------------------------

METAL_DISTANCE_DATA = {
    ("Co", "hcp"): {"mp_id": "mp-1183710", "nn_distance": 2.4706, "radius": 1.2353},
    ("Co", "fcc"): {"mp_id": "mp-102", "nn_distance": 2.4843, "radius": 0.8783},
    ("Co", "bcc"): {"mp_id": "mp-2647057", "nn_distance": 2.4289, "radius": 1.0517},
    ("Zn", "hcp"): {"mp_id": "mp-79", "nn_distance": 2.6144, "radius": 1.3072},
    ("Zn", "fcc"): {"mp_id": "mp-2646972", "nn_distance": 2.7786, "radius": 0.9824},
    ("Zn", "bcc"): {"mp_id": "mp-2647117", "nn_distance": 2.7177, "radius": 1.1768},
    ("Ti", "hcp"): {"mp_id": "mp-46", "nn_distance": 2.9357, "radius": 1.4679},
    ("Ti", "fcc"): {"mp_id": "mp-6985", "nn_distance": 2.9056, "radius": 1.0273},
    ("Ti", "bcc"): {"mp_id": "mp-73", "nn_distance": 2.8160, "radius": 1.2194},
    ("Mg", "hcp"): {"mp_id": "mp-153", "nn_distance": 3.1720, "radius": 1.5860},
    ("Mg", "fcc"): {"mp_id": "mp-1056702", "nn_distance": 3.1739, "radius": 1.1221},
    ("Mg", "bcc"): {"mp_id": "mp-110", "nn_distance": 3.0705, "radius": 1.3296},
    ("Cd", "hcp"): {"mp_id": "mp-1183591", "nn_distance": 3.0931, "radius": 1.5465},
    ("Cd", "fcc"): {"mp_id": "mp-1096861", "nn_distance": 3.1369, "radius": 1.1091},
    ("Cd", "bcc"): {"mp_id": "mp-2647135", "nn_distance": 3.0905, "radius": 1.3382},
    ("Fe", "hcp"): {"mp_id": "mp-136", "nn_distance": 2.4342, "radius": 1.2171},
    ("Fe", "fcc"): {"mp_id": "mp-150", "nn_distance": 2.5849, "radius": 0.9139},
    ("Fe", "bcc"): {"mp_id": "mp-13", "nn_distance": 2.4778, "radius": 1.0729},
    ("Cr", "hcp"): {"mp_id": "mp-89", "nn_distance": 2.4436, "radius": 1.2218},
    ("Cr", "fcc"): {"mp_id": "mp-8633", "nn_distance": 2.5336, "radius": 0.8958},
    ("Cr", "bcc"): {"mp_id": "mp-90", "nn_distance": 2.9689, "radius": 1.2856},
    ("W", "hcp"): {"mp_id": "mp-2646990", "nn_distance": 2.7829, "radius": 1.3915},
    ("W", "fcc"): {"mp_id": "mp-8641", "nn_distance": 2.8228, "radius": 0.9980},
    ("W", "bcc"): {"mp_id": "mp-91", "nn_distance": 2.7456, "radius": 1.1889},
    ("Mo", "hcp"): {"mp_id": "mp-1066523", "nn_distance": 2.8176, "radius": 1.4088},
    ("Mo", "fcc"): {"mp_id": "mp-8637", "nn_distance": 2.8125, "radius": 0.9944},
    ("Mo", "bcc"): {"mp_id": "mp-129", "nn_distance": 2.7432, "radius": 1.1879},
    ("V", "hcp"): {"mp_id": "mp-2647074", "nn_distance": 2.6043, "radius": 1.3021},
    ("V", "fcc"): {"mp_id": "mp-8632", "nn_distance": 2.6819, "radius": 0.9482},
    ("V", "bcc"): {"mp_id": "mp-146", "nn_distance": 2.5828, "radius": 1.1184},
    ("Nb", "hcp"): {"mp_id": "mp-2647103", "nn_distance": 2.8813, "radius": 1.4406},
    ("Nb", "fcc"): {"mp_id": "mp-8636", "nn_distance": 2.9864, "radius": 1.0558},
    ("Nb", "bcc"): {"mp_id": "mp-75", "nn_distance": 2.8732, "radius": 1.2441},
    ("Cu", "hcp"): {"mp_id": "mp-989695", "nn_distance": 2.5308, "radius": 1.2654},
    ("Cu", "fcc"): {"mp_id": "mp-30", "nn_distance": 2.5296, "radius": 0.8944},
    ("Cu", "bcc"): {"mp_id": "mp-998890", "nn_distance": 2.4611, "radius": 1.0657},
    ("Ag", "hcp"): {"mp_id": "mp-10597", "nn_distance": 2.9223, "radius": 1.4611},
    ("Ag", "fcc"): {"mp_id": "mp-124", "nn_distance": 2.9022, "radius": 1.0261},
    ("Ag", "bcc"): {"mp_id": "mp-2646971", "nn_distance": 2.8677, "radius": 1.2417},
    ("Au", "hcp"): {"mp_id": "mp-1008634", "nn_distance": 2.8226, "radius": 1.4113},
    ("Au", "fcc"): {"mp_id": "mp-81", "nn_distance": 2.9495, "radius": 1.0428},
    ("Au", "bcc"): {"mp_id": "mp-2647062", "nn_distance": 2.8705, "radius": 1.2430},
    ("Ni", "hcp"): {"mp_id": "mp-10257", "nn_distance": 2.4480, "radius": 1.2240},
    ("Ni", "fcc"): {"mp_id": "mp-23", "nn_distance": 2.4573, "radius": 0.8688},
    ("Ni", "bcc"): {"mp_id": "mp-1008728", "nn_distance": 2.3967, "radius": 1.0378},
    ("Pd", "hcp"): {"mp_id": "mp-1186427", "nn_distance": 2.7626, "radius": 1.3813},
    ("Pd", "fcc"): {"mp_id": "mp-2", "nn_distance": 2.7700, "radius": 0.9793},
    ("Pd", "bcc"): {"mp_id": "mp-2646977", "nn_distance": 2.7233, "radius": 1.1792},
    ("Pt", "hcp"): {"mp_id": "mp-2647022", "nn_distance": 2.7607, "radius": 1.3803},
    ("Pt", "fcc"): {"mp_id": "mp-126", "nn_distance": 2.7882, "radius": 0.9858},
    ("Pt", "bcc"): {"mp_id": "mp-2646979", "nn_distance": 2.7439, "radius": 1.1882},
    ("Al", "hcp"): {"mp_id": "mp-1183144", "nn_distance": 2.8271, "radius": 1.4135},
    ("Al", "fcc"): {"mp_id": "mp-134", "nn_distance": 2.8560, "radius": 1.0097},
    ("Al", "bcc"): {"mp_id": "mp-998860", "nn_distance": 2.7561, "radius": 1.1934},
    ("Pb", "hcp"): {"mp_id": "mp-1186444", "nn_distance": 3.5244, "radius": 1.7622},
    ("Pb", "fcc"): {"mp_id": "mp-20483", "nn_distance": 3.5281, "radius": 1.2474},
    ("Pb", "bcc"): {"mp_id": "mp-22692", "nn_distance": 3.4289, "radius": 1.4847},
}

def infer_element_from_bulk_file(bulk_file: Path) -> str:
    atoms = read(bulk_file)
    symbols = sorted(set(atoms.get_chemical_symbols()))
    if len(symbols) != 1:
        raise ValueError(
            f"Bulk file {bulk_file} must contain exactly one element for metal cluster generation, got: {symbols}"
        )
    return symbols[0]


def resolve_cluster_element(cluster_element: str | None, bulk_file: Path | None) -> str:
    if cluster_element is not None:
        element = cluster_element.capitalize()
        if bulk_file is not None:
            file_element = infer_element_from_bulk_file(bulk_file)
            if file_element != element:
                raise ValueError(
                    f"--cluster_element ({element}) does not match the element in {bulk_file} ({file_element})."
                )
        return element

    if bulk_file is None:
        raise ValueError("Provide either --cluster_element or --cluster_bulk_file.")

    return infer_element_from_bulk_file(bulk_file)


def get_nearest_neighbor_distance(atoms: Atoms) -> float:
    probe = atoms.copy()
    if not all(probe.pbc):
        probe.pbc = (True, True, True)

    # A primitive bulk CIF may contain only one atom, so build a small supercell
    # before searching for the nearest neighbor.
    probe = probe.repeat((3, 3, 3))
    distances = probe.get_all_distances(mic=False)
    positive_distances = distances[distances > 1e-8]
    if positive_distances.size == 0:
        raise ValueError("Failed to determine nearest-neighbor distance from the bulk structure.")
    return float(np.min(positive_distances))


def get_bulk_hcp_c_over_a(bulk_file: Path | None) -> float | None:
    if bulk_file is None:
        return None

    atoms = read(bulk_file)
    cellpar = atoms.cell.cellpar()
    a = float(cellpar[0])
    b = float(cellpar[1])
    c = float(cellpar[2])
    gamma = float(cellpar[5])
    if abs(a - b) < 1e-3 and abs(gamma - 120.0) < 1e-1 and a > 1e-8:
        return c / a
    return None


def resolve_lattice_constants_from_bulk_file(
    bulk_file: Path,
    structure: str,
    a: float | None,
    c: float | None,
) -> tuple[float, float | None]:
    bulk_atoms = read(bulk_file)
    nn_distance = get_nearest_neighbor_distance(bulk_atoms)

    if a is None:
        if structure == "fcc":
            a = nn_distance * np.sqrt(2.0)
        elif structure == "bcc":
            a = 2.0 * nn_distance / np.sqrt(3.0)
        elif structure == "hcp":
            a = nn_distance
        else:
            raise ValueError(f"Unsupported structure: {structure}")

    if structure != "hcp":
        return float(a), None

    if c is None:
        c_over_a = get_bulk_hcp_c_over_a(bulk_file)
        if c_over_a is None:
            c_over_a = np.sqrt(8.0 / 3.0)
        c = float(a) * float(c_over_a)

    return float(a), float(c)


def resolve_lattice_constants_from_reference(
    element: str,
    structure: str,
    a: float | None,
    c: float | None,
) -> tuple[float, float | None]:
    if a is not None:
        if structure != "hcp":
            return float(a), None
        if c is not None:
            return float(a), float(c)

    ref = reference_states[atomic_numbers[element]]
    if ref is None:
        raise ValueError(f"No ASE reference state found for {element}. Please provide lattice constants explicitly.")

    ref_structure = ref.get("symmetry")
    if a is None:
        if ref_structure != structure or "a" not in ref:
            raise ValueError(
                f"ASE has no default lattice constant for {element}-{structure}. "
                "Please provide --cluster_a explicitly or pass --cluster_bulk_file."
            )
        a = float(ref["a"])

    if structure != "hcp":
        return float(a), None

    if c is None:
        if ref_structure == "hcp":
            if "c/a" in ref:
                c = float(a) * float(ref["c/a"])
            elif "c" in ref:
                c = float(ref["c"])

    if c is None:
        c = float(a) * np.sqrt(8.0 / 3.0)

    return float(a), float(c)


def resolve_lattice_constants_from_embedded_metal_data(
    element: str,
    structure: str,
    a: float | None,
    c: float | None,
) -> tuple[float, float | None] | None:
    if a is not None:
        return None

    data = METAL_DISTANCE_DATA.get((element, structure))
    if data is None:
        return None

    # The embedded value matches metal_parameter.txt "lattice_a_A" and is the lattice
    # constant for the corresponding crystal structure, not the NN distance.
    lattice_a = float(data["nn_distance"])
    if structure in {"fcc", "bcc"}:
        return lattice_a, None
    if structure == "hcp":
        if c is None:
            c = lattice_a * np.sqrt(8.0 / 3.0)
        return lattice_a, float(c)
    raise ValueError(f"Unsupported structure: {structure}")

def get_embedded_metal_radius(element: str, structure: str) -> float | None:
    data = METAL_DISTANCE_DATA.get((element, structure))
    if data is None:
        return None
    lattice_a = float(data["nn_distance"])
    if structure == "fcc":
        return np.sqrt(2.0) * lattice_a / 4.0
    if structure == "bcc":
        return np.sqrt(3.0) * lattice_a / 4.0
    if structure == "hcp":
        return lattice_a / 2.0
    raise ValueError(f"Unsupported structure: {structure}")


def get_embedded_nearest_neighbor_distance(element: str, structure: str) -> float | None:
    data = METAL_DISTANCE_DATA.get((element, structure))
    if data is None:
        return None
    lattice_a = float(data["nn_distance"])
    if structure == "fcc":
        return lattice_a / np.sqrt(2.0)
    if structure == "bcc":
        return np.sqrt(3.0) * lattice_a / 2.0
    if structure == "hcp":
        return lattice_a
    raise ValueError(f"Unsupported structure: {structure}")


def resolve_lattice_constants(
    element: str,
    structure: str,
    a: float | None,
    c: float | None,
    bulk_file: Path | None = None,
) -> tuple[float, float | None]:
    if bulk_file is not None:
        return resolve_lattice_constants_from_bulk_file(bulk_file, structure, a, c)
    embedded_constants = resolve_lattice_constants_from_embedded_metal_data(element, structure, a, c)
    if embedded_constants is not None:
        return embedded_constants
    return resolve_lattice_constants_from_reference(element, structure, a, c)


def nearest_neighbor_from_lattice(structure: str, lattice_a: float) -> float:
    if structure == "fcc":
        return lattice_a / np.sqrt(2.0)
    if structure == "bcc":
        return np.sqrt(3.0) * lattice_a / 2.0
    if structure == "hcp":
        return lattice_a
    raise ValueError(f"Unsupported structure: {structure}")


# ---------------------------------------------------------------------------
# Generic bulk/supercell construction helpers
# ---------------------------------------------------------------------------

def build_bulk_supercell(
    element: str,
    structure: str,
    a: float,
    c: float | None,
    min_repeat: int,
) -> Atoms:
    bulk_kwargs = {"crystalstructure": structure, "a": a, "cubic": False}
    if c is not None:
        bulk_kwargs["c"] = c
    bulk_atoms = bulk(element, **bulk_kwargs)
    repeats = [max(min_repeat, 3)] * 3
    return bulk_atoms.repeat(repeats)


def build_supercell_for_radius(
    element: str,
    structure: str,
    radius: float,
    a: float,
    c: float | None,
) -> Atoms:
    bulk_kwargs = {"crystalstructure": structure, "a": a, "cubic": False}
    if c is not None:
        bulk_kwargs["c"] = c
    bulk_atoms = bulk(element, **bulk_kwargs)
    cell_lengths = bulk_atoms.cell.lengths()
    repeats = [max(3, int(np.ceil(2.0 * radius / max(length, 1e-6))) + 2) for length in cell_lengths]
    return bulk_atoms.repeat(repeats)


def select_cluster_by_radius(supercell: Atoms, radius: float) -> Atoms:
    anchor_position = get_anchor_position(supercell)
    distances = np.linalg.norm(supercell.positions - anchor_position, axis=1)
    mask = distances <= radius
    cluster = supercell[mask]
    if len(cluster) == 0:
        raise ValueError("Generated empty cluster. Increase --cluster_radius.")
    cluster.pbc = False
    cluster.positions -= cluster.get_center_of_mass()
    return cluster


def select_cluster_by_atom_count(supercell: Atoms, target_atoms: int) -> Atoms:
    if target_atoms < 1:
        raise ValueError("--cluster_atoms must be >= 1.")
    if target_atoms > len(supercell):
        raise ValueError(
            f"Requested {target_atoms} atoms, but the generated supercell only contains {len(supercell)} atoms."
        )

    anchor_position = get_anchor_position(supercell)
    distances = np.linalg.norm(supercell.positions - anchor_position, axis=1)
    order = np.argsort(distances)
    selected_indices = order[:target_atoms]
    cluster = supercell[selected_indices]
    cluster.pbc = False
    cluster.positions -= cluster.get_center_of_mass()
    return cluster


def select_cluster_by_layers(supercell: Atoms, layers: int, tolerance: float = 1e-3) -> Atoms:
    if layers < 1:
        raise ValueError("--cluster_layers must be >= 1.")

    anchor_position = get_anchor_position(supercell)
    distances = np.linalg.norm(supercell.positions - anchor_position, axis=1)
    shell_distances = np.sort(distances)

    unique_shells = []
    for dist in shell_distances:
        if not unique_shells or abs(dist - unique_shells[-1]) > tolerance:
            unique_shells.append(float(dist))

    if layers > len(unique_shells):
        raise ValueError(
            f"Requested {layers} radial shells, but only found {len(unique_shells)} shells. Increase the supercell size."
        )

    cutoff = unique_shells[layers - 1] + tolerance
    mask = distances <= cutoff
    cluster = supercell[mask]
    if len(cluster) == 0:
        raise ValueError("Generated empty cluster from layers selection.")
    cluster.pbc = False
    cluster.positions -= cluster.get_center_of_mass()
    return cluster


def get_anchor_position(supercell: Atoms) -> np.ndarray:
    cell_center = 0.5 * np.sum(supercell.cell.array, axis=0)
    distances_to_center = np.linalg.norm(supercell.positions - cell_center, axis=1)
    anchor_index = int(np.argmin(distances_to_center))
    return supercell.positions[anchor_index].copy()


# ---------------------------------------------------------------------------
# Generic cluster builders
# ---------------------------------------------------------------------------

def build_spherical_nanocluster(
    element: str,
    structure: str,
    radius: float,
    a: float | None,
    c: float | None,
    bulk_file: Path | None = None,
) -> Atoms:
    lattice_a, lattice_c = resolve_lattice_constants(element, structure, a, c, bulk_file=bulk_file)
    supercell = build_supercell_for_radius(element, structure, radius, lattice_a, lattice_c)
    return select_cluster_by_radius(supercell, radius)


def build_nanocluster(
    element: str,
    structure: str,
    atom_count: int | None = None,
    radius: float | None = None,
    layers: int | None = None,
    a: float | None = None,
    c: float | None = None,
    bulk_file: Path | None = None,
) -> Atoms:
    selected_modes = [atom_count is not None, radius is not None, layers is not None]
    if sum(selected_modes) != 1:
        raise ValueError("Provide exactly one of atom_count, radius, or layers for cluster construction.")

    lattice_a, lattice_c = resolve_lattice_constants(element, structure, a, c, bulk_file=bulk_file)

    if atom_count is not None:
        nn_reference = nearest_neighbor_from_lattice(structure, lattice_a)
        approx_radius = max(nn_reference, nn_reference * (target_sphere_radius_scale(atom_count)))
        supercell = build_supercell_for_radius(element, structure, approx_radius, lattice_a, lattice_c)
        while len(supercell) < atom_count:
            approx_radius *= 1.3
            supercell = build_supercell_for_radius(element, structure, approx_radius, lattice_a, lattice_c)
        return select_cluster_by_atom_count(supercell, atom_count)

    if radius is not None:
        supercell = build_supercell_for_radius(element, structure, radius, lattice_a, lattice_c)
        return select_cluster_by_radius(supercell, radius)

    nn_reference = nearest_neighbor_from_lattice(structure, lattice_a)
    min_repeat = max(3, layers * 2 + 1)
    supercell = build_bulk_supercell(element, structure, lattice_a, lattice_c, min_repeat=min_repeat)
    cluster = select_cluster_by_layers(supercell, layers)

    # Guard against an unphysically tiny cluster when lattice inference is poor.
    if len(cluster) == 1 and layers > 1:
        fallback_radius = max(1.0, layers * nn_reference)
        supercell = build_supercell_for_radius(element, structure, fallback_radius, lattice_a, lattice_c)
        cluster = select_cluster_by_radius(supercell, fallback_radius)

    return cluster


def target_sphere_radius_scale(atom_count: int) -> float:
    return max(1.0, (3.0 * atom_count / (4.0 * np.pi)) ** (1.0 / 3.0))


# ---------------------------------------------------------------------------
# Standard compact local cluster builders
# ---------------------------------------------------------------------------

def shell_distances_from_anchor(supercell: Atoms, tolerance: float = 1e-3) -> tuple[np.ndarray, list[float]]:
    anchor_position = get_anchor_position(supercell)
    distances = np.linalg.norm(supercell.positions - anchor_position, axis=1)
    unique_shells = []
    for dist in np.sort(distances):
        if not unique_shells or abs(dist - unique_shells[-1]) > tolerance:
            unique_shells.append(float(dist))
    return distances, unique_shells


def build_neighbor_matrix(supercell: Atoms, shell_distances: list[float]) -> np.ndarray:
    if len(shell_distances) <= 1:
        cutoff = 1.5
    else:
        cutoff = float(shell_distances[1]) * 1.15
    pairwise = supercell.get_all_distances(mic=False)
    return pairwise <= cutoff


def greedy_select_compact_subset(
    supercell: Atoms,
    candidate_indices: list[int],
    selected_indices: list[int],
    target_total: int,
    neighbor_matrix: np.ndarray,
    anchor_distances: np.ndarray,
) -> list[int]:
    selected = list(selected_indices)
    remaining = [idx for idx in candidate_indices if idx not in selected]

    while len(selected) < target_total and remaining:
        current_positions = supercell.positions[selected]
        current_center = current_positions.mean(axis=0)
        best_idx = None
        best_score = None

        for idx in remaining:
            bonds = int(np.sum(neighbor_matrix[idx, selected])) if selected else 0
            dist_to_center = float(np.linalg.norm(supercell.positions[idx] - current_center))
            dist_to_anchor = float(anchor_distances[idx])
            score = (3.0 * bonds) - dist_to_center - 0.2 * dist_to_anchor
            if best_score is None or score > best_score:
                best_score = score
                best_idx = idx

        selected.append(best_idx)
        remaining.remove(best_idx)

    return selected


def build_standard_cluster(
    element: str,
    structure: str,
    atom_count: int,
    a: float | None = None,
    c: float | None = None,
    bulk_file: Path | None = None,
    tolerance: float = 1e-3,
) -> Atoms:
    if atom_count < 1:
        raise ValueError("--cluster_atoms must be >= 1.")

    lattice_a, lattice_c = resolve_lattice_constants(element, structure, a, c, bulk_file=bulk_file)
    approx_radius = max(lattice_a, lattice_a * (3.0 * atom_count / (4.0 * np.pi)) ** (1.0 / 3.0))
    supercell = build_supercell_for_radius(element, structure, approx_radius, lattice_a, lattice_c)
    while len(supercell) < atom_count * 3:
        approx_radius *= 1.25
        supercell = build_supercell_for_radius(element, structure, approx_radius, lattice_a, lattice_c)

    anchor_distances, shells = shell_distances_from_anchor(supercell, tolerance=tolerance)
    neighbor_matrix = build_neighbor_matrix(supercell, shells)

    selected_indices: list[int] = []
    for shell_distance in shells:
        shell_indices = [
            idx for idx, dist in enumerate(anchor_distances) if abs(float(dist) - float(shell_distance)) <= tolerance
        ]
        if len(selected_indices) + len(shell_indices) <= atom_count:
            selected_indices.extend(shell_indices)
            if len(selected_indices) == atom_count:
                break
            continue

        selected_indices = greedy_select_compact_subset(
            supercell=supercell,
            candidate_indices=shell_indices,
            selected_indices=selected_indices,
            target_total=atom_count,
            neighbor_matrix=neighbor_matrix,
            anchor_distances=anchor_distances,
        )
        break

    if len(selected_indices) < atom_count:
        raise ValueError(
            f"Failed to build a {structure} standard cluster with {atom_count} atoms. Try a larger bulk/supercell."
        )

    cluster = supercell[selected_indices]
    cluster.pbc = False
    cluster.positions -= cluster.get_center_of_mass()
    return cluster
