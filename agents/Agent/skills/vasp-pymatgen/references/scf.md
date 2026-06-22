# SCF Input Generation

Generate VASP static calculation input files using `pymatgen` `MPStaticSet`.

## Steps

**1. Create a job directory**
```bash
mkdir -p scf_job
```

**2. Load the structure and generate inputs**
```python
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.vasp.sets import MPStaticSet
from ase.io import read as ase_read

# Or from any structure file (cif, extxyz, vasp, ...):
atoms = ase_read("structure.extxyz")
structure = AseAtomsAdaptor.get_structure(atoms)

# Custom 
user_incar = {
    "NCORE": 4,   # ≈ sqrt(number of cores) for optimal performance
}
vis = MPStaticSet(structure, user_incar_settings=user_incar)
vis.write_input("scf_job/")
```
If read from a previous relaxation, simply:

```python
vis = MPStaticSet.from_prev_calc("relax_job/", user_incar_settings=user_incar)
vis.write_input("scf_job/")
```

This writes `INCAR`, `POSCAR`, `KPOINTS`, and `POTCAR` into the job directory.

## Key MPStaticSet defaults

| Tag | Value | Notes |
|-----|-------|-------|
| NSW | 0 | No ionic relaxation |
| IBRION | -1 | No ion movement |
| LCHARG | True | Write CHGCAR |
| LORBIT | 11 | DOS with orbital projections |
| LASPH | True | Non-spherical PAW corrections |
| k-points | `reciprocal_density=100` | Γ-centered MP mesh |

## Notes

- Include `CHGCAR` in `backward_files` to retrieve it after the job
- For SOC calculations, also include `WAVECAR` in both `forward_files` and `backward_files`
- NCORE ≈ √(cores): 8 cores → 4, 16 cores → 4, 32 cores → 6
