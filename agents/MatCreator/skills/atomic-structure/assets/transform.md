```python
from ase.io import read, write
import numpy as np
import json

def transform_lattice(atoms, scale=None, strain=None, rotation=None, 
                      transform_matrix=None, scale_atoms=True):
    """Apply lattice transformations."""
    atoms_t = atoms.copy()
    operations = []
    
    # Scale
    if scale is not None:
        if isinstance(scale, (int, float)):
            scale = [scale, scale, scale]
        scale = np.array(scale)
        atoms_t.set_cell(atoms_t.cell * scale, scale_atoms=scale_atoms)
        operations.append(f"scale: {scale.tolist()}")
    
    # Strain (Voigt notation: [exx, eyy, ezz, eyz, exz, exy])
    if strain is not None:
        strain = np.array(strain)
        if len(strain) == 6:
            # Convert Voigt to tensor
            strain_tensor = np.array([
                [strain[0], strain[5], strain[4]],
                [strain[5], strain[1], strain[3]],
                [strain[4], strain[3], strain[2]]
            ])
        else:
            strain_tensor = np.array(strain).reshape(3, 3)
        
        deformation = np.eye(3) + strain_tensor
        atoms_t.set_cell(deformation @ atoms_t.cell, scale_atoms=scale_atoms)
        operations.append(f"strain: {strain.tolist()}")
    
    # Rotation (Euler angles ZYZ in degrees)
    if rotation is not None:
        rotation = np.array(rotation)
        if len(rotation) == 3:
            # ZYZ Euler angles
            alpha, beta, gamma = np.radians(rotation)
            Rz1 = np.array([[np.cos(alpha), -np.sin(alpha), 0],
                           [np.sin(alpha), np.cos(alpha), 0],
                           [0, 0, 1]])
            Ry = np.array([[np.cos(beta), 0, np.sin(beta)],
                          [0, 1, 0],
                          [-np.sin(beta), 0, np.cos(beta)]])
            Rz2 = np.array([[np.cos(gamma), -np.sin(gamma), 0],
                           [np.sin(gamma), np.cos(gamma), 0],
                           [0, 0, 1]])
            R = Rz1 @ Ry @ Rz2
        else:
            R = np.array(rotation).reshape(3, 3)
        
        atoms_t.set_cell(R @ atoms_t.cell, scale_atoms=scale_atoms)
        operations.append(f"rotation: {rotation.tolist()}")
    
    # Custom transform matrix
    if transform_matrix is not None:
        M = np.array(transform_matrix).reshape(3, 3)
        atoms_t.set_cell(M @ atoms_t.cell, scale_atoms=scale_atoms)
        operations.append(f"transform_matrix: applied")
    
    return atoms_t, operations

# Usage example
input_path = "structure.extxyz"
atoms = read(input_path)

# Apply transformations
atoms_transformed, ops = transform_lattice(
    atoms,
    scale=0.97,  # Uniform compression by 3%
    strain=None,
    rotation=None,
    scale_atoms=True
)

# Save
output_path = "structure_compressed.extxyz"
write(output_path, atoms_transformed, format='extxyz')

print(json.dumps({
    "status": "success",
    "structure_path": output_path,
    "original_cell": atoms.cell.array.tolist(),
    "transformed_cell": atoms_transformed.cell.array.tolist(),
    "operations_applied": ops
}))
```

**Uniaxial strain example:**
```python
from ase.io import read, write
import numpy as np

atoms = read("structure.extxyz")

# Apply 2% tensile strain along z
strain = [0.0, 0.0, 0.02, 0.0, 0.0, 0.0]  # Voigt notation
strain_tensor = np.array([
    [strain[0], strain[5], strain[4]],
    [strain[5], strain[1], strain[3]],
    [strain[4], strain[3], strain[2]]
])
deformation = np.eye(3) + strain_tensor

atoms.set_cell(deformation @ atoms.cell, scale_atoms=True)
write("structure_strained.extxyz", atoms, format='extxyz')
print("Applied 2% tensile strain along z")
```