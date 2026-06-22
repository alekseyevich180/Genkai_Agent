# Relaxation Input Generation

Generate VASP geometry relaxation input files using `pymatgen` `MPRelaxSet`.

## Steps

**1. Create a job directory**
```bash
mkdir -p relax_job
```

**2. Load the structure and generate inputs**
```python
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.vasp.sets import MPRelaxSet
from ase.io import read as ase_read

# From any structure file (cif, extxyz, vasp, ...):
atoms = ase_read("structure.extxyz")
structure = AseAtomsAdaptor.get_structure(atoms)

user_incar = {
    "NCORE": 4,   # ≈ sqrt(number of cores)
    # "ENCUT": 600,
}

vis = MPRelaxSet(structure, user_incar_settings=user_incar)
vis.write_input("relax_job/")
```

This writes `INCAR`, `POSCAR`, `KPOINTS`, and `POTCAR` into the job directory.

## Key MPRelaxSet defaults

| Tag | Value | Notes |
|-----|-------|-------|
| IBRION | 2 | RMM-DIIS ionic relaxation |
| ISIF | 3 | Relax ions + cell shape + volume |
| NSW | 99 | Max ionic steps |
| ISMEAR | 0 | Gaussian smearing |
| SIGMA | 0.05 | Smearing width (eV) |
| LWAVE | False | Do not write WAVECAR |
| LCHARG | False | Do not write CHGCAR |
| k-points | `reciprocal_density=64` | Γ-centered MP mesh |

## Notes

- Include `CONTCAR` and `OUTCAR` in `backward_files` to retrieve the relaxed structure
- NCORE ≈ √(cores): 8 cores → 3, 16 cores → 4, 32 cores → 6
