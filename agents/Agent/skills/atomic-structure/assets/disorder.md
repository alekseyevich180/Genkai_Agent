```python
import numpy as np
from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.io.ase import AseAtomsAdaptor
from ase.io import write


def list_wyckoff(input_file, symprec=1e-3):
    """Print Wyckoff groups in the ordered parent structure."""
    s = Structure.from_file(input_file)
    sga = SpacegroupAnalyzer(s, symprec=symprec)
    ss = sga.get_symmetrized_structure()

    print("Space group:", sga.get_space_group_symbol(), sga.get_space_group_number())
    print()

    for gid, (w, inds) in enumerate(zip(ss.wyckoff_symbols, ss.equivalent_indices)):
        elems = [s[i].specie.symbol for i in inds]
        coord = [round(x, 6) for x in s[inds[0]].frac_coords]
        print(f"group {gid:2d} | Wyckoff {w:>4s} | elements {sorted(set(elems))} | "
              f"indices {list(inds)} | first coord {coord}")


def find_wyckoff_indices(
    structure,
    element,
    wyckoff,
    symprec=1e-3,
    allow_multiple=False,
):
    """Find indices by element and Wyckoff symbol."""
    sga = SpacegroupAnalyzer(structure, symprec=symprec)
    ss = sga.get_symmetrized_structure()

    matches = []

    for w, inds in zip(ss.wyckoff_symbols, ss.equivalent_indices):
        elems = [structure[i].specie.symbol for i in inds]

        if w.lower() == wyckoff.lower() and set(elems) == {element}:
            matches.append(list(inds))

    if len(matches) == 0:
        raise ValueError(f"Cannot find {element} on Wyckoff {wyckoff}.")

    if len(matches) > 1 and not allow_multiple:
        raise ValueError(
            f"Multiple {element}-{wyckoff} groups found: {matches}. "
            "Check with list_wyckoff() or set allow_multiple=True."
        )

    return [i for group in matches for i in group]


def make_wyckoff_disorder(
    input_file,
    element_a,
    wyckoff_a,
    element_b,
    wyckoff_b,
    disorder_degree,
    supercell=(2, 2, 2),
    seed=42,
    symprec=1e-3,
    output_prefix="disordered",
):
    """
    Swap element_a on wyckoff_a with element_b on wyckoff_b.

    Example:
    Cl on 4a <-> S on 4c in Li6PS5Cl.
    """

    rng = np.random.default_rng(seed)

    s = Structure.from_file(input_file)

    # 1. Find Wyckoff sites in ordered parent cell
    idx_a = find_wyckoff_indices(s, element_a, wyckoff_a, symprec=symprec)
    idx_b = find_wyckoff_indices(s, element_b, wyckoff_b, symprec=symprec)

    print("A sites:", element_a, wyckoff_a, idx_a)
    print("B sites:", element_b, wyckoff_b, idx_b)

    if len(idx_a) != len(idx_b):
        raise ValueError(f"A/B site numbers differ: {len(idx_a)} vs {len(idx_b)}")

    # Preserve original species object, including oxidation state if present
    species_a = s[idx_a[0]].specie
    species_b = s[idx_b[0]].specie

    # 2. Label parent-cell sites before making supercell
    labels = ["other"] * len(s)

    for i in idx_a:
        labels[i] = "A"

    for i in idx_b:
        labels[i] = "B"

    s.add_site_property("sublattice", labels)

    # 3. Make supercell
    s.make_supercell(supercell)

    A = []
    B = []

    for i, site in enumerate(s):
        label = site.properties["sublattice"]
        elem = site.specie.symbol

        if label == "A" and elem == element_a:
            A.append(i)

        if label == "B" and elem == element_b:
            B.append(i)

    n_total = len(A)
    n_swap_float = disorder_degree * n_total
    n_swap = int(round(n_swap_float))

    if abs(n_swap - n_swap_float) > 1e-8:
        raise ValueError(
            f"disorder_degree × sites = {n_swap_float}, not integer. "
            "Use larger supercell or another degree."
        )

    print(f"Supercell A sites: {len(A)}")
    print(f"Supercell B sites: {len(B)}")
    print(f"Swap pairs: {n_swap}")

    chosen_A = rng.choice(A, n_swap, replace=False)
    chosen_B = rng.choice(B, n_swap, replace=False)

    # 4. Swap species
    for i in chosen_A:
        s.replace(i, species_b)

    for i in chosen_B:
        s.replace(i, species_a)

    tag = int(round(disorder_degree * 100))
    vasp_file = f"{output_prefix}_{tag}pct_seed{seed}.vasp"
    xyz_file = f"{output_prefix}_{tag}pct_seed{seed}.extxyz"

    s.to(fmt="poscar", filename=vasp_file)
    write(xyz_file, AseAtomsAdaptor.get_atoms(s))

    print("Written:", vasp_file)
    print("Written:", xyz_file)

    return s
```