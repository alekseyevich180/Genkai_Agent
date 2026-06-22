---
name: lammps
description: >
  LAMMPS molecular dynamics with DeepMD/DPA machine-learning potentials ONLY.
  This skill generates LAMMPS input files (in.lammps) using pair_style deepmd.
  Classical force fields (Stillinger-Weber, Tersoff, EAM, etc.) are NOT supported
  and must NEVER be suggested. The default model is the DPA3 pretrained checkpoint
  frozen with the Omat24 head (from DEEPMD_MODEL_PATH env var), identical to the
  ase-deepmd skill. A model file is always required — do NOT ask the user whether
  they want to use a classical potential instead. Bohrium's default DeepMD image
  (registry.dp.tech/dptech/deepmd-kit) already includes LAMMPS — no separate
  LAMMPS installation is needed. Covers structure conversion, input generation,
  Bohrium submission via bohrium skill, and result collection.
metadata:
  tools:
    - run_bash
    - run_python_file
    - load_skill_resource
  dependent_skills:
    - bohrium
    - dpdisp
  tags:
    - lammps
    - deepmd
    - dpa
    - dpa3
    - deep-potential
    - machine-learning-potential
    - md
    - molecular-dynamics
    - npt
    - nve
    - bohrium
---

# LAMMPS / DeepMD Skill

## CRITICAL CONSTRAINTS — READ FIRST

1. **This skill ONLY supports `pair_style deepmd`.** Do NOT suggest, mention, or
   offer classical force fields (Stillinger-Weber, Tersoff, EAM, ReaxFF, etc.) as
   alternatives. There is no "choice" — DeepMD is the only option.

2. **A model is always available.** The environment variable `DEEPMD_MODEL_PATH`
   points to a pretrained DPA3 model. The tool automatically freezes it with the
   Omat24 head (`dp --pt freeze --head Omat24`). You do NOT need to ask the user
   for a model file — just run `generate_input` and it will resolve the model
   automatically. Only ask if `DEEPMD_MODEL_PATH` is unset AND the user did not
   pass `--model_path`.

3. **LAMMPS is already installed in the Bohrium DeepMD image.** The default image
   `registry.dp.tech/dptech/deepmd-kit` provides both LAMMPS and DeePMD-kit.
   Do NOT ask whether LAMMPS is installed — it is. Use `BOHRIUM_DEEPMD_IMAGE`
   (the same env var as the `deepmd` skill) as the container image.

4. **Never present this as a plan to be confirmed.** If the user asks for a
   LAMMPS MD simulation, execute immediately: generate input → submit → collect.

---

## How it works

| Component | Role |
|---|---|
| `lammps_tools.py` | Generate `in.lammps` + `conf.lmp`; collect results |
| `bohrium` skill | Submit job directories to Bohrium (recommended) |
| `dpdisp` skill | Submit to Slurm/HPC clusters (alternative) |

Every command prints JSON to stdout and exits 0 on success, 1 on error.

---

## Mandatory workflow sequence

1. **Obtain a structure** — supply an extxyz, POSCAR, CIF, or any ASE-readable file.
   If the user has no structure, generate one first using the `atomic-structure` skill.
2. **Prepare job directory** — run `lammps_tools.py generate_input`. The model is
   resolved automatically from `DEEPMD_MODEL_PATH` and frozen with Omat24 head.
3. **Submit jobs** — use the `bohrium` skill for Bohrium platform submission.
   For full submission details, see:
   ```
   load_skill_resource(skill_name="lammps", path="references/bohrium-submission.md")
   ```
4. **Collect results** — run `collect_results` after jobs finish.

---

## 1. Generate LAMMPS input

### Simplest usage (model resolved from DEEPMD_MODEL_PATH automatically)

```bash
python lammps_tools.py generate_input --structures POSCAR
```

This uses all defaults: DPA3 model, Omat24 head, NPT, 300 K, 1 bar, 1M steps.

### NVE ensemble at 600 K

```bash
python lammps_tools.py generate_input \
    --structures structures.extxyz \
    --ensemble nve --temperature 600 --runtime_steps 500000
```

### NPT at zero pressure

```bash
python lammps_tools.py generate_input \
    --structures POSCAR \
    --temperature 300 --pressure 0.0
```

### All frames from a multi-frame file (one job per frame)

```bash
python lammps_tools.py generate_input \
    --structures traj.extxyz --frame -1
```

**Key flags**

| Flag | Default | Description |
|---|---|---|
| `--structures` | required | Any ASE-readable structure file (extxyz, POSCAR, CIF, …) |
| `--model_path` | `DEEPMD_MODEL_PATH` | DeePMD model file. Auto-resolved from env var — usually不需要指定. |
| `--head` | `Omat24` | Multi-task head to freeze. Pass `none` to skip freezing. |
| `--frame` | 0 | Frame index. `-1` = all frames. |
| `--ensemble` | `npt` | `npt` or `nve` |
| `--temperature` | 300.0 | Target temperature (K) |
| `--pressure` | 1 | Target pressure in bar (NPT only). LAMMPS units metal uses bar. |
| `--timestep` | 0.001 | Timestep in ps |
| `--runtime_steps` | 1000000 | Number of MD steps |
| `--dump_interval` | 10000 | Trajectory write frequency (steps) |
| `--thermo_interval` | 100 | Thermo output frequency (steps) |

### Model handling (same as ase-deepmd)

The pretrained DPA3 model (from `DEEPMD_MODEL_PATH`) is frozen with
`dp --pt freeze --head Omat24` before being copied into the job directory.
The frozen single-task model is used as `pair_style deepmd frozen_model.pth`.
Pass `--head none` to skip freezing.

### Generated in.lammps example

```lammps
units           metal
boundary        p p p
atom_style      atomic

neighbor        1.0 bin

read_data       conf.lmp

pair_style      deepmd frozen_model.pth
pair_coeff      * * Si                    # elements sorted alphabetically

velocity        all create 300.0 23456789
timestep        0.001
thermo          100
thermo_style    custom step pe ke etotal temp press vol

fix             1 all npt temp 300.0 300.0 0.1 aniso 1.0 1.0 0.5   # pressure in bar
dump            1 all custom 10000 traj.dump id type xu yu zu
dump_modify     1 sort id

run             1000000

undump          1
unfix           1
```

---

## 2. Collect results

```bash
python lammps_tools.py collect_results \
    --calc_dirs /tmp/lammps_jobs/lammps_npt_001 /tmp/lammps_jobs/lammps_npt_002
```

Returns per-job summary: average temperature, pressure, potential energy, volume.

---

## 3. Submit to Bohrium

For Bohrium platform submission, use the `bohrium` skill. Full submission details
including environment variables, JSON template, and submission commands are in:

```
load_skill_resource(skill_name="lammps", path="references/bohrium-submission.md")
```

---

## config.yaml

```yaml
work_dir: lammps
```
