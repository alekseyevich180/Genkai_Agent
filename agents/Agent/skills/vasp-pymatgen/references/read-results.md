# Reading VASP Results

Load `vasprun.xml` with `pymatgen` `Vasprun` and access results as attributes.

## Load

```python
from pymatgen.io.vasp.outputs import Vasprun

vr = Vasprun("calc_dir/vasprun.xml")
```

For band structure jobs, enable eigenvalue parsing:
```python
vr = Vasprun("nscf_job/vasprun.xml", parse_eigen=True)
```

## Key attributes by calculation type

**Relaxation**
```python
vr.final_structure          # relaxed pymatgen Structure
vr.final_energy             # total energy (eV)
vr.ionic_steps[-1]["forces"]   # forces on last step (eV/Å)
vr.ionic_steps[-1]["stress"]   # stress tensor (kBar)
len(vr.ionic_steps)         # number of ionic steps taken
```

**SCF**
```python
vr.final_energy             # total energy (eV)
vr.efermi                   # Fermi energy (eV)
gap, cbm, vbm, is_metal = vr.eigenvalue_band_properties
```

**NSCF (band structure)**
```python
vr.efermi
gap, cbm, vbm, is_metal = vr.eigenvalue_band_properties
bs = vr.get_band_structure(line_mode=True)
bs.kpoints                  # list of k-points
bs.nb_bands                 # number of bands
bs.labels_dict              # high-symmetry point labels
```
