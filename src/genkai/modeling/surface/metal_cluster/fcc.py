import argparse

import numpy as np
from ase import Atoms


# =========================
# Basic utilities
# =========================
def format_row_sequence(rows):
    return "+".join(map(str, rows))


def row_profile_name(rows):
    if not rows:
        return "empty"

    if len(rows) == 1:
        return "single_row"

    diffs = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
    if all(diff == -1 for diff in diffs) and rows[-1] == 1:
        return "triangle"

    if all(diff == -1 for diff in diffs) or all(diff == 1 for diff in diffs):
        return "trapezoid"

    if len(rows) % 2 == 1 and rows == rows[::-1]:
        unique_rows = sorted(set(rows))
        if len(unique_rows) == 2 and unique_rows[1] - unique_rows[0] == 1:
            if rows[0] == unique_rows[1] and all(
                rows[i] == (unique_rows[1] if i % 2 == 0 else unique_rows[0])
                for i in range(len(rows))
            ):
                return "rectangle"
            if rows[0] == unique_rows[0] and rows[len(rows) // 2] == unique_rows[1]:
                return "hexagon"

    if rows == rows[::-1]:
        return "symmetric"

    return "custom"


# =========================
# FCC(111) row-sequence generation
# =========================
def triangle_rows(n):
    if n < 1:
        raise ValueError("Triangle edge length must be >= 1.")
    return list(range(n, 0, -1))


def hex_rows(n):
    if n < 1:
        raise ValueError("Hexagon side length must be >= 1.")
    return list(range(n, 2 * n)) + list(range(2 * n - 2, n - 1, -1))


def trapezoid_rows(max_row_atoms, row_count):
    if max_row_atoms < 1 or row_count < 1:
        raise ValueError("max_row_atoms and row_count must be >= 1.")
    rows = [max_row_atoms - i for i in range(row_count)]
    if rows[-1] < 1:
        raise ValueError("trapezoid rows would fall below 1 atom; reduce row_count or increase max_row_atoms.")
    return rows


def rectangle_rows(max_row_atoms, row_count):
    if max_row_atoms < 1 or row_count < 1:
        raise ValueError("max_row_atoms and row_count must be >= 1.")
    short_row_atoms = max(1, max_row_atoms - 1)
    return [max_row_atoms if i % 2 == 0 else short_row_atoms for i in range(row_count)]


def resolve_fcc_rows(
    rows_text=None,
    row_profile="custom",
    max_row_atoms=None,
    row_count=None,
    size=None,
):
    profile = row_profile.lower()

    if profile in {"auto", "custom"} and rows_text:
        return parse_rows(rows_text)

    if profile == "triangle":
        edge = size if size is not None else max_row_atoms
        if edge is None:
            raise ValueError("--fcc_max_row_atoms is required when --fcc_row_profile triangle is used.")
        return triangle_rows(edge)

    if profile == "hexagon":
        side = size if size is not None else max_row_atoms
        if side is None:
            raise ValueError("--fcc_max_row_atoms is required when --fcc_row_profile hexagon is used.")
        return hex_rows(side)

    if profile == "trapezoid":
        if max_row_atoms is None or row_count is None:
            raise ValueError("--fcc_max_row_atoms and --fcc_row_count are required for trapezoid.")
        return trapezoid_rows(max_row_atoms, row_count)

    if profile == "rectangle":
        if max_row_atoms is None or row_count is None:
            raise ValueError("--fcc_max_row_atoms and --fcc_row_count are required for rectangle.")
        return rectangle_rows(max_row_atoms, row_count)

    raise ValueError("--fcc_rows is required when --fcc_row_profile auto/custom is used.")


# =========================
# FCC upper-layer rules
# =========================
def hollow_orientation_for_rows(rows):
    diffs = [rows[i + 1] - rows[i] for i in range(len(rows) - 1)]
    first_nonzero = next((diff for diff in diffs if diff != 0), 0)
    return 0 if first_nonzero > 0 else 1


def hollow_count(left, right, orientation):
    if abs(left - right) > 1:
        raise ValueError("Adjacent fcc rows must differ by at most 1 atom for compact hollow stacking.")

    if left == right:
        return left - 1

    if orientation == 0:
        return left if right == left + 1 else right - 1

    return left - 1 if right == left + 1 else right


def layer_positions_from_rows(rows, dx=1.0):
    dy = np.sqrt(3.0) * dx / 2.0
    y_center = (len(rows) - 1) / 2.0
    positions = []
    for row_idx, row_len in enumerate(rows):
        x_center = (row_len - 1) / 2.0
        y = (row_idx - y_center) * dy
        positions.extend([(col - x_center) * dx, y] for col in range(row_len))
    return np.array(positions, dtype=float)


def validate_compact_layer_rows(rows, label):
    if any(row_len < 1 for row_len in rows):
        raise ValueError(f"{label} contains an empty row: {format_row_sequence(rows)}")

    if any(abs(rows[i + 1] - rows[i]) > 1 for i in range(len(rows) - 1)):
        raise ValueError(
            f"{label} is not compact for fcc(111): adjacent rows differ by more than 1 atom "
            f"({format_row_sequence(rows)})."
        )

    positions = layer_positions_from_rows(rows)
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            distance = float(np.linalg.norm(positions[i] - positions[j]))
            if distance < 1.0 - 1e-8:
                raise ValueError(
                    f"{label} violates fcc(111) close-packed spacing: "
                    f"minimum in-plane distance is {distance:.6f} times sqrt(2)/2*a "
                    f"for rows {format_row_sequence(rows)}."
                )


def fcc_upper_rows(rows, orientation):
    upper = []
    for i in range(len(rows) - 1):
        next_len = hollow_count(rows[i], rows[i + 1], orientation)
        if next_len > 0:
            upper.append(next_len)
    return upper


def transition_orientation(base_orientation, stacking_mode, transition_idx):
    if stacking_mode == "AB" and transition_idx % 2 == 1:
        return 1 - base_orientation
    return base_orientation


def build_fcc_stack(bottom_rows, layers, stacking_mode="ABC"):
    stacking_mode = validate_stacking_mode(stacking_mode)
    validate_compact_layer_rows(bottom_rows, "bottom layer")
    stack = [bottom_rows]
    current = bottom_rows
    base_orientation = hollow_orientation_for_rows(bottom_rows)
    for transition_idx in range(layers - 1):
        orientation = transition_orientation(base_orientation, stacking_mode, transition_idx)
        current = fcc_upper_rows(current, orientation)
        if len(current) == 0:
            break
        validate_compact_layer_rows(current, f"layer {transition_idx + 2}")
        stack.append(current)
    return stack


# =========================
# Coordinate generation for FCC(111)
# =========================
def fcc111_positions(stack, lattice_a, stacking_mode="ABC"):
    stacking_mode = validate_stacking_mode(stacking_mode)

    # Geometric parameters
    a = lattice_a
    dx = a / np.sqrt(2)               # {111} in-plane dense direction <110>: sqrt(2)/2*a
    dy = np.sqrt(3) / 2 * dx          # triangular-lattice row spacing within {111}
    dz = np.sqrt(3) / 3 * a           # {111} inter-plane spacing: sqrt(3)/3*a

    positions = []
    bottom_rows = stack[0]
    base_orientation = hollow_orientation_for_rows(bottom_rows)
    y_center = (len(bottom_rows) - 1) / 2
    current_layer_rows = []

    for i, row_len in enumerate(bottom_rows):
        x_center = (row_len - 1) / 2
        y = (i - y_center) * dy
        current_layer_rows.append(
            [
                np.array([(j - x_center) * dx, y, 0.0], dtype=float)
                for j in range(row_len)
            ]
        )

    for layer_idx in range(len(stack)):
        for row_atoms in current_layer_rows:
            positions.extend(row_atoms)

        if layer_idx == len(stack) - 1:
            break

        next_layer_rows = []
        orientation = transition_orientation(base_orientation, stacking_mode, layer_idx)
        for row_idx in range(len(current_layer_rows) - 1):
            row_a = current_layer_rows[row_idx]
            row_b = current_layer_rows[row_idx + 1]
            row_atoms = []

            len_a = len(row_a)
            len_b = len(row_b)

            if abs(len_a - len_b) > 1:
                raise ValueError("Adjacent fcc rows must differ by at most 1 atom for compact hollow stacking.")

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

    return np.array(positions)


def validate_stacking_mode(stacking_mode):
    mode = stacking_mode.upper()
    if mode not in {"ABC", "AB"}:
        raise ValueError("stacking_mode must be ABC or AB.")
    return mode


# =========================
# Main builder
# =========================
def build_fcc111_cluster(element, row_sequence, layers, lattice_a, stacking_mode="ABC"):
    stacking_mode = validate_stacking_mode(stacking_mode)
    stack = build_fcc_stack(row_sequence, layers, stacking_mode=stacking_mode)
    positions = fcc111_positions(stack, lattice_a, stacking_mode=stacking_mode)

    atoms = Atoms(symbols=[element] * len(positions), positions=positions)
    atoms.pbc = False
    atoms.center()

    return atoms, stack


def parse_rows(text):
    cleaned = text.strip()
    if "," not in cleaned:
        raise ValueError("fcc rows must be comma-separated, e.g. 4,3,2,1.")
    return [int(value) for value in cleaned.split(",") if value.strip()]


# =========================
# Example CLI
# =========================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an fcc {111} compact cluster from a bottom row sequence.")
    parser.add_argument("--rows", type=str, default="4,3,2,1", help="Bottom row sequence, e.g. 4,3,2,1.")
    parser.add_argument(
        "--row_profile",
        type=str,
        default="auto",
        choices=["auto", "custom", "triangle", "hexagon", "trapezoid", "rectangle"],
        help="Bottom-layer row profile.",
    )
    parser.add_argument("--max_row_atoms", type=int, default=None, help="Maximum row length or shape size.")
    parser.add_argument("--row_count", type=int, default=None, help="Number of rows for trapezoid/rectangle profiles.")
    parser.add_argument("--size", type=int, default=None, help="Backward-compatible triangle edge or hexagon side length.")
    parser.add_argument("--stacking_mode", type=str, default="ABC", choices=["ABC", "AB"], help="Compact stacking mode.")
    parser.add_argument("--layers", type=int, default=4, help="Number of stacking layers.")
    parser.add_argument("--element", type=str, default="Pt", help="Element symbol.")
    parser.add_argument("--lattice_a", type=float, default=3.92, help="FCC lattice constant a.")
    parser.add_argument("--output", type=str, default=None, help="Output CIF path.")
    args = parser.parse_args()

    rows = resolve_fcc_rows(
        rows_text=args.rows,
        row_profile=args.row_profile,
        max_row_atoms=args.max_row_atoms,
        row_count=args.row_count,
        size=args.size,
    )

    atoms, stack = build_fcc111_cluster(
        element=args.element,
        row_sequence=rows,
        layers=args.layers,
        lattice_a=args.lattice_a,
        stacking_mode=args.stacking_mode,
    )

    print("Row sequences per layer:")
    for i, r in enumerate(stack):
        print(f"L{i+1}: {format_row_sequence(r)} (atoms={sum(r)})")

    print("Bottom row profile:", row_profile_name(rows))
    print("\nTotal atoms:", len(atoms))

    from ase.io import write

    output = args.output or f"fcc111_atoms{len(atoms)}_L{len(stack)}_{'_'.join(map(str, rows))}.cif"
    write(output, atoms)
    print("Written:", output)
