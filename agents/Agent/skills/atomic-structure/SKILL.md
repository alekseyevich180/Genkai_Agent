---
name: atomic-structure
description: Build, inspect, modify, and curate atomic structures using inline Python code with ASE (no external scripts required).
metadata:
  tools: []
  dependent_skills: []
---
## Overview

This skill provides **inline Python code examples** using ASE (Atomic Simulation Environment) to build, inspect, transform, and curate atomic structures. Unlike the `crystal_structure` skill, all operations are performed by writing and executing Python code directly via `run_python` — no external CLI scripts are needed.

**Key workflow:**
1. Write Python code using ASE and other available packages
2. Execute via `run_python` tool
3. Parse output (JSON or file paths) to retrieve results
4. Save structures to workspace for downstream use

**Common output formats:** `extxyz` (recommended), `xyz`, `cif`, `vasp` (POSCAR)

---

## 1. Build Bulk Crystal

Create a bulk crystal from a chemical formula and structure prototype.

```python
from ase.build import bulk
from ase.io import write
import json

# Parameters
formula = "Al"
crystal_structure = "fcc"
a = 4.05  # lattice constant in Å
size = [2, 2, 2]  # supercell size
vacuum = 0.0  # Å, set >0 for surfaces

# Build structure
atoms = bulk(formula, crystal_structure, a=a)
atoms = atoms * size  # create supercell

if vacuum > 0:
    atoms.center(vacuum=vacuum, axis=2)

# Save to file
output_path = f"{formula}_{crystal_structure}.extxyz"
write(output_path, atoms, format='extxyz')

# Output metadata as JSON
result = {
    "status": "success",
    "structure_path": output_path,
    "chemical_formula": formula,
    "num_atoms": len(atoms),
    "cell": atoms.cell.array.tolist(),
    "pbc": list(atoms.pbc)
}
print(json.dumps(result))
```

**Example: BCC iron with 3×3×3 supercell**
```python
from ase.build import bulk
from ase.io import write
import json

atoms = bulk("Fe", "bcc", a=2.87)
atoms = atoms * [3, 3, 3]
write("Fe_bcc_3x3x3.extxyz", atoms, format='extxyz')

print(json.dumps({"status": "success", "structure_path": "Fe_bcc_3x3x3.extxyz", "num_atoms": len(atoms)}))
```

**Example: HCP titanium with c/a ratio**
```python
from ase.build import bulk
from ase.io import write

atoms = bulk("Ti", "hcp", a=2.95, c=4.68)  # c/a ≈ 1.586
write("Ti_hcp.cif", atoms, format='cif')
print("Structure saved to Ti_hcp.cif")
```

---

## 2. Build Supercells and Doped Structures

Expand an existing structure file into a supercell.

```python
from ase.io import read, write
import json

# Read input structure
input_path = "GaN.extxyz"
atoms = read(input_path)

# Create supercell
size = [2, 2, 2]  # [nx, ny, nz]
atoms_super = atoms * size

# Substitute one Ga atom with Al to create an Al-doped GaN structure
symbols = atoms_super.get_chemical_symbols()
ga_indices = [i for i, s in enumerate(symbols) if s == "Ga"]
if not ga_indices:
    raise ValueError("No Ga atoms found for Al substitution.")
atoms_super[ga_indices[0]].symbol = "Al"

# Save
output_path = "GaN_Al_doped_2x2x2.extxyz"
write(output_path, atoms_super, format='extxyz')

print(json.dumps({
    "status": "success",
    "structure_path": output_path,
    "original_num_atoms": len(atoms),
    "supercell_num_atoms": len(atoms_super),
    "size": size,
    "dopant": "Al",
    "substituted_site": ga_indices[0]
}))
```

**Anisotropic supercell example:**
```python
from ase.io import read, write

atoms = read("structure.cif")
atoms = atoms * [3, 3, 1]  # 3×3×1 supercell
write("POSCAR", atoms, format='vasp')
print("POSCAR created with 3x3x1 supercell")
```

---

## 3. Perturb Atoms

Generate multiple perturbed replicas by randomly distorting the cell and displacing atoms.

```python
from ase.io import read, write
from ase.build import make_supercell
import numpy as np
import json

def perturb_structure(atoms, cell_pert_fraction=0.03, atom_pert_distance=0.1, 
                      atom_pert_style='normal', seed=None):
    """Generate a single perturbed structure."""
    if seed is not None:
        np.random.seed(seed)
    
    atoms_pert = atoms.copy()
    
    # Cell perturbation
    if cell_pert_fraction > 0:
        cell = atoms_pert.cell.array
        perturbation = np.eye(3) + np.random.uniform(-cell_pert_fraction, cell_pert_fraction, (3, 3))
        atoms_pert.set_cell(cell @ perturbation, scale_atoms=True)
    
    # Atom perturbation
    if atom_pert_distance > 0:
        positions = atoms_pert.positions
        if atom_pert_style == 'normal':
            displacement = np.random.normal(0, atom_pert_distance/3, positions.shape)
        elif atom_pert_style == 'uniform':
            # Uniform within sphere
            r = atom_pert_distance * np.random.uniform(0, 1, len(positions))**(1/3)
            theta = np.random.uniform(0, 2*np.pi, len(positions))
            phi = np.random.uniform(0, np.pi, len(positions))
            displacement = np.column_stack([
                r * np.sin(phi) * np.cos(theta),
                r * np.sin(phi) * np.sin(theta),
                r * np.cos(phi)
            ])
        elif atom_pert_style == 'const':
            # Fixed magnitude, random direction
            direction = np.random.normal(0, 1, positions.shape)
            direction /= np.linalg.norm(direction, axis=1, keepdims=True)
            displacement = direction * atom_pert_distance
        else:
            displacement = np.random.normal(0, atom_pert_distance/3, positions.shape)
        
        atoms_pert.positions = positions + displacement
    
    return atoms_pert

# Main execution
input_path = "Al_fcc.extxyz"
atoms = read(input_path)

pert_num = 50
cell_pert_fraction = 0.03
atom_pert_distance = 0.1
atom_pert_style = 'normal'

# Generate perturbed structures
perturbed_structures = []
for i in range(pert_num):
    pert = perturb_structure(atoms, cell_pert_fraction, atom_pert_distance, 
                            atom_pert_style, seed=i)
    perturbed_structures.append(pert)

# Write multi-frame file
output_path = "Al_fcc_perturbed.extxyz"
write(output_path, perturbed_structures, format='extxyz')

print(json.dumps({
    "status": "success",
    "structure_path": output_path,
    "num_structures": len(perturbed_structures),
    "num_atoms_per_structure": len(atoms)
}))
```

---

## 4. Inspect Structure

Read structure file(s) and report metadata. Optionally export properties.

```python
from ase.io import read
import json
import numpy as np

def inspect_structure(filepath):
    """Inspect a structure file and return metadata."""
    structures = read(filepath, index=':')  # Read all frames
    
    if not isinstance(structures, list):
        structures = [structures]
    
    results = {
        "status": "success",
        "structure_path": filepath,
        "num_frames": len(structures),
        "chemical_formulas": [],
        "num_atoms": len(structures[0]) if structures else 0,
        "info_keys": list(structures[0].info.keys()) if structures else [],
        "array_keys": list(structures[0].arrays.keys()) if structures else [],
        "volumes": [],
        "energies": []
    }
    
    for i, atoms in enumerate(structures):
        # Chemical formula
        symbols = atoms.get_chemical_symbols()
        from collections import Counter
        formula_dict = Counter(symbols)
        formula = "".join(f"{el}{cnt}" if cnt > 1 else el 
                         for el, cnt in sorted(formula_dict.items()))
        results["chemical_formulas"].append(formula)
        
        # Volume
        results["volumes"].append(float(atoms.get_volume()))
        
        # Energy (if available)
        if 'energy' in atoms.info:
            results["energies"].append(float(atoms.info['energy']))
        elif 'energy' in atoms.arrays:
            results["energies"].append(float(atoms.arrays['energy']))
    
    # Summary statistics
    if results["volumes"]:
        results["volume_summary"] = {
            "mean": float(np.mean(results["volumes"])),
            "std": float(np.std(results["volumes"])),
            "min": float(np.min(results["volumes"])),
            "max": float(np.max(results["volumes"]))
        }
    
    if results["energies"]:
        results["energy_summary"] = {
            "mean": float(np.mean(results["energies"])),
            "std": float(np.std(results["energies"])),
            "min": float(np.min(results["energies"])),
            "max": float(np.max(results["energies"]))
        }
    
    return results

# Usage
filepath = "structures.extxyz"
metadata = inspect_structure(filepath)
print(json.dumps(metadata, indent=2))
```

**Export properties to files:**
```python
from ase.io import read
import numpy as np

structures = read("dataset.extxyz", index=':')
if not isinstance(structures, list):
    structures = [structures]

# Export volumes
with open("volumes.txt", "w") as f:
    for i, atoms in enumerate(structures):
        f.write(f"{i} {atoms.get_volume():.6f}\n")

# Export energies (if available)
energies = []
for atoms in structures:
    if 'energy' in atoms.info:
        energies.append(atoms.info['energy'])
    elif 'energy' in atoms.arrays:
        energies.append(atoms.arrays['energy'])

if energies:
    with open("energies.txt", "w") as f:
        for i, e in enumerate(energies):
            f.write(f"{i} {e:.6f}\n")

print("Exported volumes.txt and energies.txt")
```

---

## 5. Transform Lattice

Apply scale, strain, rotation, or custom matrix transformations.

For implementation details and example code, refer to [transform.md](assets/transform.md).

---

## 6. Filter by Diversity (Entropy-based)

Select a maximally diverse subset of candidate structures using descriptor-based filtering, so that the retained set spans the broadest possible range of local environments and structural motifs while reducing near-duplicate configurations.

For implementation details and example code, refer to [diversity.md](assets/diversity.md).

---

## 7. Modify Disorder

Modify the degree of disorder in the structure by swapping atomic positions.

1. Use SpacegroupAnalyzer to identify the Wyckoff sites of the ordered parent phase.
2. Locate the primitive-cell sites corresponding to the specified element + Wyckoff label.
3. Assign labels, build a supercell, and perform random pairwise swaps.

For implementation details and example code, refer to [disorder.md](assets/disorder.md).

---

## Best Practices

1. **Always save structures to workspace** — Use absolute or workspace-relative paths
2. **Use extxyz format** — Preserves all metadata (energy, forces, stress)
3. **Validate after operations** — Check `len(atoms)` and cell parameters
4. **Set random seeds** — For reproducible perturbations
5. **Handle multi-frame files** — Use `index=':'` when reading
6. **Export metadata as JSON** — Easy to parse in subsequent steps

---

## Error Handling

Wrap code in try-except blocks and return structured error messages:

```python
import json

try:
    from ase.io import read, write
    atoms = read("input.extxyz")
    # ... operations ...
    write("output.extxyz", atoms)
    print(json.dumps({"status": "success", "structure_path": "output.extxyz"}))
except Exception as e:
    print(json.dumps({"status": "error", "message": str(e)}))
```

---

## Quick Reference

| Task | Key ASE Functions |
|------|------------------|
| Build bulk | `ase.build.bulk()` |
| Supercell | `atoms * [nx, ny, nz]` |
| Read/write | `ase.io.read()`, `ase.io.write()` |
| Cell manipulation | `atoms.set_cell()`, `atoms.cell` |
| Positions | `atoms.positions`, `atoms.get_positions()` |
| Neighbors | `ase.neighborlist.neighbor_list()` |
| Visualization | `ase.visualize.view()` (local only) |
