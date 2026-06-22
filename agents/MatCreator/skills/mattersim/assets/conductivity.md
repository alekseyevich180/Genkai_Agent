# Example python code to plot msd curve, compute diffusivity and conductivity 

Recommended workflow:
1. Read the MD trajectory file.
2. Select the target mobile ion species whose transport behavior should be analyzed, such as `Li`.
3. Discard an initial equilibration portion of the trajectory before analysis.
4. Convert the selected ASE frames to `pymatgen Structure` objects.
5. Use `pymatgen.analysis.diffusion.analyzer.DiffusionAnalyzer` to compute:
   - the MSD curve
   - the tracer diffusivity
   - the ionic conductivity

Example：

```python
import numpy as np
import matplotlib.pyplot as plt
from ase.io import read
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.analysis.diffusion.analyzer import DiffusionAnalyzer

trajectory_path = "300.0_nvt.traj"
frames = read(trajectory_path, index=":")

mobile_species = "Li"
temperature_K = 300.0
time_step_fs = 2.0
step_skip = 100
analysis_start_fraction = 0.40
analysis_end_fraction = 0.80

n_total = len(frames)
if n_total < 10:
    raise ValueError(f"Trajectory frames too few: {n_total}")

# Analyze only the production-like portion of the trajectory to reduce
# equilibration bias and noisy tail effects in the MSD/conductivity estimate.
start_index = int(n_total * analysis_start_fraction)
end_index = int(n_total * analysis_end_fraction)
selected_frames = frames[start_index:end_index]

symbols = selected_frames[0].get_chemical_symbols()
n_mobile = symbols.count(mobile_species)
if n_mobile == 0:
    raise ValueError(f"No {mobile_species!r} atoms found in structure.")

adaptor = AseAtomsAdaptor()
structures = [adaptor.get_structure(atoms) for atoms in selected_frames]

analyzer = DiffusionAnalyzer.from_structures(
    structures=structures,
    specie=mobile_species,
    temperature=temperature_K,
    time_step=time_step_fs,
    step_skip=step_skip,
    smoothed=False,
)

print(f"Diffusivity: {analyzer.diffusivity:.6e} cm^2/s")
print(f"Diffusivity std dev: {analyzer.diffusivity_std_dev:.6e} cm^2/s")
print(f"Conductivity: {analyzer.conductivity:.6e} mS/cm")
print(f"Conductivity std dev: {analyzer.conductivity_std_dev:.6e} mS/cm")

frame_interval_fs = time_step_fs * step_skip
dt_ps = frame_interval_fs / 1000.0
start_time_ps = start_index * dt_ps
relative_time_ps = np.arange(len(analyzer.msd)) * dt_ps
absolute_time_ps = start_time_ps + relative_time_ps

np.savetxt(
    "li_msd_selected_window.dat",
    np.column_stack([relative_time_ps, absolute_time_ps, analyzer.msd]),
    header="time_ps_relative time_ps_absolute msd_A2",
)

plt.figure(figsize=(6, 4))
plt.plot(relative_time_ps, analyzer.msd, linewidth=2)
plt.xlabel("Time / ps")
plt.ylabel(r"MSD / $\\AA^2$")
plt.title(
    f"{mobile_species} MSD from selected trajectory window\\n"
    f"Absolute window: {start_time_ps:.3f} to {absolute_time_ps[-1]:.3f} ps\\n"
    f"Diffusivity: {analyzer.diffusivity:.6e} cm^2/s\\n"
    f"Conductivity: {analyzer.conductivity:.6e} mS/cm"
)
plt.tight_layout()
plt.savefig("li_msd_selected_window.png", dpi=300)
```


Important analysis parameters
- `trajectory_path`: NVT trajectory path, for example `300.0_nvt.traj`
- `mobile_species`: mobile ion species such as `Li`
- `temperature_K`: simulation temperature in Kelvin; keep this consistent with the MD run
- `time_step_fs`: MD timestep in fs; for the current `mattersim_moldyn.py`, this comes from `--timestep`
- `step_skip`: frame stride in MD steps between saved trajectory frames; for the current script this is `dumpfreq = 100`
- `analysis_start_fraction` and `analysis_end_fraction`: frame selection window for the MSD analysis; the current example uses the 40% to 80% portion of the trajectory

- because `DiffusionAnalyzer` uses the first frame of the selected window as the displacement reference, the MSD plot should usually use a relative time axis starting from `0 ps`; if needed, also record the absolute start time of that selected window in the original trajectory


## Notes

- Use the same `mobile_species`, `temperature_K`, `time_step_fs`, and `step_skip` that correspond to the actual MD setup.
- Be explicit about which trajectory segment is analyzed; excluding early equilibration frames is usually important for stable results.
- The current example saves both relative and absolute time columns in the MSD data file. Use the relative time axis for the MSD curve itself, and the absolute time column to map the selected window back to the original trajectory.
- If the trajectory is too short or too noisy, report that the estimated conductivity has limited confidence.