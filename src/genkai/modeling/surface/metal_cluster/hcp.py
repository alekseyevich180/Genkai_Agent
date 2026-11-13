import argparse
from pathlib import Path

import numpy as np
from ase import Atoms

from .cluster_builder import resolve_cluster_element, resolve_lattice_constants


HCP_0001_COMPACT_SHAPES = [
    {"atoms": 1, "type": "hex", "row_sequence": [1]},
    {"atoms": 7, "type": "hex", "row_sequence": [3, 2, 3]},
    {"atoms": 19, "type": "hex", "row_sequence": [5, 4, 3, 4, 5]},
    {"atoms": 37, "type": "hex", "row_sequence": [7, 6, 5, 4, 5, 6, 7]},
    {"atoms": 61, "type": "hex", "row_sequence": [9, 8, 7, 6, 5, 6, 7, 8, 9]},
    {"atoms": 3, "type": "triangle", "row_sequence": [2, 1]},
    {"atoms": 6, "type": "triangle", "row_sequence": [3, 2, 1]},
    {"atoms": 10, "type": "triangle", "row_sequence": [4, 3, 2, 1]},
    {"atoms": 15, "type": "triangle", "row_sequence": [5, 4, 3, 2, 1]},
    {"atoms": 21, "type": "triangle", "row_sequence": [6, 5, 4, 3, 2, 1]},
    {"atoms": 28, "type": "triangle", "row_sequence": [7, 6, 5, 4, 3, 2, 1]},
    {"atoms": 5, "type": "trapezoid", "row_sequence": [3, 2]},
    {"atoms": 8, "type": "trapezoid", "row_sequence": [3, 2, 3]},
    {"atoms": 9, "type": "trapezoid", "row_sequence": [4, 3, 2]},
    {"atoms": 11, "type": "trapezoid", "row_sequence": [4, 3, 4]},
    {"atoms": 12, "type": "trapezoid", "row_sequence": [5, 4, 3]},
    {"atoms": 13, "type": "trapezoid", "row_sequence": [3, 2, 3, 2, 3]},
    {"atoms": 14, "type": "trapezoid", "row_sequence": [4, 3, 4, 3]},
    {"atoms": 16, "type": "trapezoid", "row_sequence": [5, 4, 5, 2]},
    {"atoms": 17, "type": "trapezoid", "row_sequence": [5, 4, 5, 3]},
    {"atoms": 18, "type": "trapezoid", "row_sequence": [4, 3, 4, 3, 4]},
    {"atoms": 20, "type": "trapezoid", "row_sequence": [5, 4, 3, 4, 4]},
    {"atoms": 23, "type": "trapezoid", "row_sequence": [5, 4, 5, 4, 5]},
    {"atoms": 2, "type": "row", "row_sequence": [2]},
    {"atoms": 4, "type": "row", "row_sequence": [2, 2]},
    {"atoms": 6, "type": "row", "row_sequence": [3, 3]},
    {"atoms": 8, "type": "row", "row_sequence": [4, 4]},
    {"atoms": 9, "type": "row", "row_sequence": [3, 3, 3]},
    {"atoms": 12, "type": "row", "row_sequence": [4, 4, 4]},
    {"atoms": 16, "type": "row", "row_sequence": [4, 4, 4, 4]},
]


def format_row_sequence(rows):
    return "+".join(str(value) for value in rows)


def row_profile_name(rows):
    if not rows:
        return "empty"

    if len(rows) == 1:
        return "row" if rows[0] > 1 else "hex"

    if all(value == rows[0] for value in rows):
        return "row"

    diffs = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
    if all(diff == -1 for diff in diffs) and rows[-1] == 1:
        return "triangle"

    if len(rows) % 2 == 1 and rows == rows[::-1]:
        unique_rows = sorted(set(rows))
        if len(unique_rows) == 2 and unique_rows[1] - unique_rows[0] == 1:
            if rows[0] == unique_rows[0] and rows[len(rows) // 2] == unique_rows[1]:
                return "hex"
            if rows[0] == unique_rows[1] and all(
                rows[i] == (unique_rows[1] if i % 2 == 0 else unique_rows[0])
                for i in range(len(rows))
            ):
                return "trapezoid"

    if all(abs(diff) <= 1 for diff in diffs):
        return "trapezoid"

    return "custom"


def parse_row_sequence(text):
    cleaned = text.strip().replace("+", ",")
    return [int(value) for value in cleaned.split(",") if value.strip()]


def lookup_compact_shape(atom_count, shape_type=None):
    for entry in HCP_0001_COMPACT_SHAPES:
        if entry["atoms"] != atom_count:
            continue
        if shape_type is None or entry["type"] == shape_type:
            return dict(entry)
    raise ValueError(f"No hcp(0001) compact shape for atoms={atom_count}, type={shape_type}.")


def validate_hcp0001_rows(row_sequence):
    if not row_sequence:
        raise ValueError("row_sequence cannot be empty.")
    if any(row_len < 1 for row_len in row_sequence):
        raise ValueError("Each row must contain at least one atom.")
    if any(abs(row_sequence[i + 1] - row_sequence[i]) > 1 for i in range(len(row_sequence) - 1)):
        raise ValueError(
            "hcp(0001) compact monolayer requires adjacent rows to differ by at most 1 atom: "
            f"{format_row_sequence(row_sequence)}"
        )


def validate_hcp0001_spacing(positions, lattice_a, label):
    min_distance = lattice_a
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            distance = float(np.linalg.norm(positions[i] - positions[j]))
            if distance < min_distance - 1e-8:
                raise ValueError(
                    f"{label} violates hcp(0001) close-packed spacing: "
                    f"minimum in-plane distance is {distance:.6f} Angstrom, expected >= a = {lattice_a:.6f} Angstrom."
                )


def layer_positions_from_rows(rows, dx=1.0):
    dy = np.sqrt(3.0) * dx / 2.0
    y_center = (len(rows) - 1) / 2.0
    positions = []
    for row_idx, row_len in enumerate(rows):
        x_center = (row_len - 1) / 2.0
        y = (row_idx - y_center) * dy
        positions.extend([(col - x_center) * dx, y] for col in range(row_len))
    return np.array(positions, dtype=float)


def hollow_orientation_for_rows(rows):
    diffs = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
    first_nonzero = next((diff for diff in diffs if diff != 0), 0)
    return 0 if first_nonzero > 0 else 1


def hollow_count(left, right, orientation):
    if abs(left - right) > 1:
        raise ValueError("Adjacent hcp rows must differ by at most 1 atom for compact AB stacking.")

    if left == right:
        return left - 1

    if orientation == 0:
        return left if right == left + 1 else right - 1

    return left - 1 if right == left + 1 else right


def hcp_upper_rows(rows, orientation):
    upper = []
    for i in range(len(rows) - 1):
        next_len = hollow_count(rows[i], rows[i + 1], orientation)
        if next_len > 0:
            upper.append(next_len)
    return upper


def hcp_transition_orientation(base_orientation, transition_idx):
    return base_orientation if transition_idx % 2 == 0 else 1 - base_orientation


def build_hcp_stack(bottom_rows, layers):
    if layers < 1:
        raise ValueError("hcp layers must be >= 1.")
    validate_hcp0001_rows(bottom_rows)
    stack = [bottom_rows]
    current = bottom_rows
    base_orientation = hollow_orientation_for_rows(bottom_rows)
    for transition_idx in range(layers - 1):
        orientation = hcp_transition_orientation(base_orientation, transition_idx)
        current = hcp_upper_rows(current, orientation)
        if len(current) == 0:
            break
        validate_hcp0001_rows(current)
        stack.append(current)
    return stack


def hcp0001_monolayer_positions(row_sequence, lattice_a):
    # A3/hcp reference:
    # dense plane {0001}, dense direction <11-20>, in-plane minimum unit length a.
    xy_positions = layer_positions_from_rows(row_sequence, dx=lattice_a)
    return np.column_stack([xy_positions, np.zeros(len(xy_positions), dtype=float)])


def hcp0001_positions(stack, lattice_a, lattice_c):
    dx = lattice_a
    dz = lattice_c / 2.0

    positions = []
    bottom_rows = stack[0]
    base_orientation = hollow_orientation_for_rows(bottom_rows)
    current_layer_rows = []
    bottom_xy = layer_positions_from_rows(bottom_rows, dx=dx)
    cursor = 0
    for row_len in bottom_rows:
        row_atoms = []
        for _ in range(row_len):
            x, y = bottom_xy[cursor]
            row_atoms.append(np.array([x, y, 0.0], dtype=float))
            cursor += 1
        current_layer_rows.append(row_atoms)

    for layer_idx in range(len(stack)):
        for row_atoms in current_layer_rows:
            positions.extend(row_atoms)

        if layer_idx == len(stack) - 1:
            break

        next_layer_rows = []
        orientation = hcp_transition_orientation(base_orientation, layer_idx)
        for row_idx in range(len(current_layer_rows) - 1):
            row_a = current_layer_rows[row_idx]
            row_b = current_layer_rows[row_idx + 1]
            row_atoms = []

            len_a = len(row_a)
            len_b = len(row_b)

            if abs(len_a - len_b) > 1:
                raise ValueError("Adjacent hcp rows must differ by at most 1 atom for compact AB stacking.")

            if len_a == len_b:
                for col in range(len_a - 1):
                    if orientation == 0:
                        hollow = (row_a[col] + row_a[col + 1] + row_b[col]) / 3.0
                    else:
                        hollow = (row_a[col] + row_b[col] + row_b[col + 1]) / 3.0
                    row_atoms.append(np.array([hollow[0], hollow[1], (layer_idx + 1) * dz], dtype=float))
            elif len_b == len_a + 1:
                if orientation == 0:
                    for col in range(len_a):
                        hollow = (row_a[col] + row_b[col] + row_b[col + 1]) / 3.0
                        row_atoms.append(np.array([hollow[0], hollow[1], (layer_idx + 1) * dz], dtype=float))
                else:
                    for col in range(len_a - 1):
                        hollow = (row_a[col] + row_a[col + 1] + row_b[col + 1]) / 3.0
                        row_atoms.append(np.array([hollow[0], hollow[1], (layer_idx + 1) * dz], dtype=float))
            else:
                if orientation == 0:
                    for col in range(len_b - 1):
                        hollow = (row_a[col + 1] + row_b[col] + row_b[col + 1]) / 3.0
                        row_atoms.append(np.array([hollow[0], hollow[1], (layer_idx + 1) * dz], dtype=float))
                else:
                    for col in range(len_b):
                        hollow = (row_a[col] + row_a[col + 1] + row_b[col]) / 3.0
                        row_atoms.append(np.array([hollow[0], hollow[1], (layer_idx + 1) * dz], dtype=float))

            if row_atoms:
                next_layer_rows.append(row_atoms)

        current_layer_rows = next_layer_rows

    return np.array(positions, dtype=float)


def build_hcp0001_monolayer_cluster(element, row_sequence, lattice_a):
    validate_hcp0001_rows(row_sequence)
    positions = hcp0001_monolayer_positions(row_sequence, lattice_a)
    validate_hcp0001_spacing(positions, lattice_a, "hcp(0001) monolayer")
    atoms = Atoms(symbols=[element] * len(positions), positions=positions)
    atoms.pbc = False
    atoms.center()
    return atoms


def build_hcp0001_cluster(element, row_sequence, layers, lattice_a, lattice_c):
    stack = build_hcp_stack(row_sequence, layers)
    positions = hcp0001_positions(stack, lattice_a, lattice_c)
    for layer_idx, layer_rows in enumerate(stack, start=1):
        validate_hcp0001_spacing(
            hcp0001_monolayer_positions(layer_rows, lattice_a),
            lattice_a,
            f"hcp(0001) layer {layer_idx}",
        )
    atoms = Atoms(symbols=[element] * len(positions), positions=positions)
    atoms.pbc = False
    atoms.center()
    return atoms, stack


def print_catalog():
    print("atoms  type       row_sequence")
    print("-----  ---------  ---------------------")
    for entry in HCP_0001_COMPACT_SHAPES:
        print(f"{entry['atoms']:<5}  {entry['type']:<9}  {format_row_sequence(entry['row_sequence'])}")


def main():
    parser = argparse.ArgumentParser(
        description="Build an hcp(0001) compact ABAB-stacked cluster from a row sequence or a catalog entry."
    )
    parser.add_argument("--rows", type=str, default=None, help="Row sequence, e.g. 3,2,3.")
    parser.add_argument("--atoms", type=int, default=None, help="Catalog atom count.")
    parser.add_argument(
        "--shape_type",
        type=str,
        default=None,
        choices=["hex", "triangle", "trapezoid", "row"],
        help="Catalog shape type.",
    )
    parser.add_argument("--element", type=str, default=None, help="Element symbol.")
    parser.add_argument(
        "--cluster_bulk_file",
        type=Path,
        default=None,
        help="Optional elemental bulk CIF/structure file used to infer the element and lattice constants.",
    )
    parser.add_argument("--cluster_a", type=float, default=None, help="Manual hcp lattice constant a.")
    parser.add_argument("--cluster_c", type=float, default=None, help="Manual hcp lattice constant c.")
    parser.add_argument("--layers", type=int, default=1, help="Number of hcp(0001) stacking layers, ABAB.")
    parser.add_argument("--output", type=str, default=None, help="Output CIF path.")
    parser.add_argument("--list_catalog", action="store_true", help="Print the built-in compact-shape catalog and exit.")
    args = parser.parse_args()

    if args.list_catalog:
        print_catalog()
        return

    if args.rows is not None:
        row_sequence = parse_row_sequence(args.rows)
        shape_type = row_profile_name(row_sequence)
    elif args.atoms is not None:
        entry = lookup_compact_shape(args.atoms, args.shape_type)
        row_sequence = entry["row_sequence"]
        shape_type = entry["type"]
    else:
        raise ValueError("Provide either --rows or --atoms (optionally with --shape_type).")

    element = resolve_cluster_element(args.element, args.cluster_bulk_file)
    lattice_a, lattice_c = resolve_lattice_constants(
        element=element,
        structure="hcp",
        a=args.cluster_a,
        c=args.cluster_c,
        bulk_file=args.cluster_bulk_file,
    )

    atoms, stack = build_hcp0001_cluster(element, row_sequence, args.layers, lattice_a, lattice_c)
    output = args.output or (
        f"hcp0001_{element}_{shape_type}_{len(atoms)}atoms_L{len(stack)}_{format_row_sequence(row_sequence).replace('+', '_')}.cif"
    )

    print(f"hcp(0001) cluster: {shape_type}")
    print(f"bottom rows: {format_row_sequence(row_sequence)}")
    print("stacking: ABAB")
    print(f"layers: {len(stack)}")
    print("row sequences per layer:", " / ".join(format_row_sequence(layer_rows) for layer_rows in stack))
    print(f"atoms: {len(atoms)}")
    print(f"element: {element}")
    print(f"lattice constants: a = {lattice_a:.6f} Angstrom, c = {lattice_c:.6f} Angstrom")
    print(f"in-plane nearest-neighbor distance: a = {lattice_a:.6f} Angstrom")
    print(f"inter-plane spacing: c/2 = {0.5 * lattice_c:.6f} Angstrom")
    print("close-packed plane: {0001}")
    print("close-packed direction: <11-20>")

    from ase.io import write

    write(output, atoms)
    print(f"Written: {output}")


if __name__ == "__main__":
    main()
