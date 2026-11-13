import argparse

import numpy as np
from ase import Atoms


def format_row_sequence(row_sequence: list[int] | tuple[int, ...]) -> str:
    return "+".join(str(value) for value in row_sequence)


def staggered_row_sequence(max_row_atoms: int, row_count: int) -> list[int]:
    if max_row_atoms < 1:
        raise ValueError("max_row_atoms must be >= 1.")
    if row_count < 1:
        raise ValueError("row_count must be >= 1.")
    if max_row_atoms == 1 and row_count > 1:
        raise ValueError("max_row_atoms=1 only supports one row.")

    rows = []
    for row_idx in range(row_count):
        row_atoms = max_row_atoms if row_idx % 2 == 0 else max_row_atoms - 1
        if row_atoms < 1:
            raise ValueError("Staggered rows cannot contain fewer than one atom.")
        rows.append(row_atoms)
    return rows


def bridge_upper_row_sequence(row_sequence: list[int] | tuple[int, ...]) -> list[int]:
    return [row_count - 1 for row_count in row_sequence if row_count > 1]


def bridge_upper_atom_count(row_sequence: list[int] | tuple[int, ...]) -> int:
    return sum(bridge_upper_row_sequence(row_sequence))


def bridge_stack_from_row_sequence(row_sequence: list[int] | tuple[int, ...], layers: int) -> list[list[int]]:
    if layers < 1:
        raise ValueError("layers must be >= 1.")

    stack = [list(row_sequence)]
    current_rows = list(row_sequence)
    for _ in range(1, layers):
        current_rows = bridge_upper_row_sequence(current_rows)
        if not current_rows:
            raise ValueError(
                f"Cannot build {layers} layers from bottom row sequence {format_row_sequence(row_sequence)}."
            )
        stack.append(current_rows)
    return stack


def bridge_stack_from_shape(max_row_atoms: int, row_count: int, layers: int) -> list[list[int]]:
    return bridge_stack_from_row_sequence(staggered_row_sequence(max_row_atoms, row_count), layers)


def summarize_stack(stack: list[list[int]]) -> dict[str, object]:
    return {
        "layer_plan": [sum(rows) for rows in stack],
        "row_sequences": stack,
        "row_sequence_text": [format_row_sequence(rows) for rows in stack],
    }


def bcc110_bridge_positions(stack: list[list[int]], lattice_a: float) -> np.ndarray:
    # A2/bcc compact stacking from the reference table:
    # dense plane {110}, dense direction <111>, in-row spacing sqrt(3)/2*a,
    # inter-plane spacing sqrt(2)/2*a, ABAB stacking along <110>.
    dense_spacing = np.sqrt(3.0) * lattice_a / 2.0
    row_spacing = lattice_a / np.sqrt(2.0)
    z_spacing = lattice_a / np.sqrt(2.0)

    bottom_rows = stack[0]
    row_center = (len(bottom_rows) - 1) / 2.0
    current_layer_rows = []
    for row_idx, row_length in enumerate(bottom_rows):
        x_center = (row_length - 1) / 2.0
        y = (row_idx - row_center) * row_spacing
        current_layer_rows.append(
            [
                np.array([(col - x_center) * dense_spacing, y, 0.0], dtype=float)
                for col in range(row_length)
            ]
        )

    positions = []
    for layer_idx in range(len(stack)):
        for row_atoms in current_layer_rows:
            positions.extend(row_atoms)

        if layer_idx == len(stack) - 1:
            break

        next_layer_rows = []
        for row_atoms in current_layer_rows:
            if len(row_atoms) < 2:
                continue
            sorted_row = sorted(row_atoms, key=lambda point: float(point[0]))
            next_layer_rows.append(
                [
                    np.array(
                        [
                            0.5 * (sorted_row[idx][0] + sorted_row[idx + 1][0]),
                            sorted_row[idx][1],
                            (layer_idx + 1) * z_spacing,
                        ],
                        dtype=float,
                    )
                    for idx in range(len(sorted_row) - 1)
                ]
            )
        current_layer_rows = next_layer_rows

    return np.array(positions, dtype=float)


def build_bcc110_bridge_cluster(
    element: str,
    max_row_atoms: int,
    row_count: int,
    layers: int,
    lattice_a: float,
) -> tuple[Atoms, list[int], list[str]]:
    stack = bridge_stack_from_shape(max_row_atoms, row_count, layers)
    positions = bcc110_bridge_positions(stack, lattice_a)
    atoms = Atoms(symbols=[element] * len(positions), positions=positions)
    atoms.pbc = False
    atoms.positions -= atoms.get_center_of_mass()
    summary = summarize_stack(stack)
    return atoms, list(summary["layer_plan"]), list(summary["row_sequence_text"])


def print_stack(max_row_atoms: int, row_count: int, layers: int) -> None:
    stack = bridge_stack_from_shape(max_row_atoms, row_count, layers)
    summary = summarize_stack(stack)

    print("bcc {110}, dense direction <111>, paired bridge stacking")
    print(f"input: max_row_atoms={max_row_atoms}, rows={row_count}, layers={layers}")
    print("")
    print("  layer  atoms  rows")
    print("  -----  -----  -----------------")
    for idx, rows in enumerate(stack, start=1):
        print(f"  L{idx:<4}  {sum(rows):<5}  {format_row_sequence(rows)}")
    print("")
    print("layer_plan: " + "+".join(str(value) for value in summary["layer_plan"]))
    print("top_layer: " + summary["row_sequence_text"][-1])


# Compatibility helpers for existing package imports.
bcc110_bridge_upper_row_sequence = bridge_upper_row_sequence
bcc110_supported_upper_capacity = bridge_upper_atom_count


def bcc110_single_layer_shape_candidates(atom_count: int) -> list[dict[str, object]]:
    candidates = []
    for max_row_atoms in range(1, atom_count + 1):
        for row_count in range(1, atom_count + 1):
            try:
                rows = staggered_row_sequence(max_row_atoms, row_count)
            except ValueError:
                continue
            if sum(rows) == atom_count:
                candidates.append(
                    {
                        "atom_count": atom_count,
                        "row_sequence": rows,
                        "row_sequence_text": format_row_sequence(rows),
                        "upper_atom_count": bridge_upper_atom_count(rows),
                        "upper_row_sequence": bridge_upper_row_sequence(rows),
                        "upper_row_sequence_text": format_row_sequence(bridge_upper_row_sequence(rows)),
                    }
                )
    return candidates


def bcc110_layer_stack_candidates(bottom_atom_count: int, layers: int) -> list[dict[str, object]]:
    stacks = []
    for candidate in bcc110_single_layer_shape_candidates(bottom_atom_count):
        try:
            stack = bridge_stack_from_row_sequence(candidate["row_sequence"], layers)
        except ValueError:
            continue
        stacks.append(summarize_stack(stack))
    return stacks


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build bcc {110} paired bridge-stacking layer plans from max-row size, row count, and layer count."
    )
    parser.add_argument("max_row_atoms", type=int, help="Atom count in each long row of the bottom layer.")
    parser.add_argument("row_count", type=int, help="Number of staggered rows in the bottom layer.")
    parser.add_argument("layers", type=int, help="Number of stacked layers to generate.")
    args = parser.parse_args()

    print_stack(args.max_row_atoms, args.row_count, args.layers)


if __name__ == "__main__":
    main()
