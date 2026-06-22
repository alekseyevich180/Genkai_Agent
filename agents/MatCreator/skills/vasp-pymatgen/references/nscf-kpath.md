# NSCF Band Structure Input Generation

Generate VASP non-self-consistent (band structure) input files using `MPNonSCFSet`.
Requires a completed SCF calculation with `CHGCAR`.

## Steps

**1. Create a job directory**
```bash
mkdir -p nscf_job
```

**2. Generate inputs from previous SCF**
```python
from pymatgen.io.vasp.sets import MPNonSCFSet

user_incar = {
    "NCORE": 4,   # ≈ sqrt(number of cores)
    # "NBANDS": 64,
}

vis = MPNonSCFSet.from_prev_calc("scf_job/", mode="line", user_incar_settings=user_incar)
vis.write_input("nscf_job/")   # copies CHGCAR automatically
```

For SOC calculations, also copy `WAVECAR` manually:
```python
import shutil
shutil.copy2("scf_job/WAVECAR", "nscf_job/WAVECAR")
```

## Key MPNonSCFSet defaults

| Tag | Value | Notes |
|-----|-------|-------|
| ICHARG | 11 | Read charge density from CHGCAR |
| LCHARG | False | Do not write new CHGCAR |
| LWAVE | False | Do not write WAVECAR |
| LORBIT | 11 | DOS with orbital projections |
| k-path | `HighSymmKpath` | 64 points per segment |

## Notes

- `CHGCAR` must be in `forward_files` when submitting the NSCF job to Bohrium
- For SOC, also include `WAVECAR` in `forward_files`
- Include `vasprun.xml` in `backward_files` for band structure post-processing
