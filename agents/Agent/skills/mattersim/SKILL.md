---
name: mattersim
description: Run MatterSim workflows for batch structure relaxation, molecular dynamics, model finetuning, and post-MD ionic conductivity analysis on crystal structure datasets..
tags: [MatterSim, relaxation, molecular dynamics, MSD, Mean Squared Displacement]
tools: [run_bash]
dependent_skills: []
---

| Script | Role |
|---|---|
| `mattersim_moldyn.py` | Supports a two-stage molecular dynamics workflow with an NPT stage followed by an NVT stage |

Script: `mattersim_moldyn.py` (in the skill's `scripts/` directory).

# MatterSim Skill

Default format
- Use `extxyz` as the default input and output format.
- For batch jobs, prefer a multi-frame `extxyz` file as input.


## Relaxation and Molecular Dynamics on local

Perform structure optimization and molecular dynamics simulations locally using MatterSim.

### Batch relaxation

Use the MatterSim CLI `relax` subcommand.

Example:

```bash
ts=$(date +"%Y%m%d%H%M%S")
workdir="matsim/${ts}.mattersim_relax"
mkdir -p "$workdir"
cd "$workdir"
source ${MATTERGEN_ENV}/bin/activate

python -m mattersim.cli.mattersim_app relax \
  --structure-file /abs/path/to/structures.extxyz \
  --device cuda \
  --work-dir results \
  --filter EXPCELLFILTER \
  --fmax 0.01 \
  --steps 1000
```

Important options
- `--structure-file`: one or more structure files; prefer one multi-frame `extxyz`
- `--mattersim-model`: optional:["mattersim-v1.0.0-1m", "mattersim-v1.0.0-5m"], default:"mattersim-v1.0.0-1m"
- `--device`: `cpu` or `cuda`
- `--work-dir`: working directory for relaxation outputs
- `--save-csv`: output table for relaxation results
- `--filter`: optional cell filter
- `--constrain-symmetry`: optional enable symmetry constraints when needed
- `--pressure-in-GPa`: optional target pressure
- `--fmax`: force convergence threshold
- `--steps`: maximum relaxation steps，default:1000

After relaxation, extract the structures from results.csv.gz and save them as an extxyz file.


### Batch molecular dynamics

Recommended workflow:

1. Create a timestamped `workdir`:

```bash
ts=$(date +"%Y%m%d%H%M%S")
workdir="matsim/${ts}.mattersim_batch_md"
mkdir -p "$workdir"
```

2. Prepare the input structures. If the input is a multi-frame `extxyz`, split it into single-frame structure files, create numerically indexed subdirectories under `workdir`, and place one `extxyz` file in each directory. Also determine the starting and ending indices, `num_start` and `num_end`.
3. Run `mattersim moldyn` once for each structure directory.


Example:

```bash
source "${MATTERGEN_ENV}/bin/activate"
for i in $(seq "$num_start" "$num_end"); do
  python mattersim_moldyn.py \
    --stru "$workdir/$i/structure.extxyz" \
    --model mattersim-v1.0.0-5M.pth \
    --temp 300 \
    --npt_steps 1000 \
    --nvt_steps 100000 \
    --timestep 2
done
```

Important options
- `--stru`: a single structure file for each MD run
- `--model`: a real model path
- `--temp`: simulation temperature in Kelvin
- `--npt_steps`: number of NPT steps
- `--nvt_steps`: number of NVT steps
- `--timestep`: MD timestep in fs, default `2`

Generated files
- `CONTCAR_min.vasp`: minimized structure in VASP format
- `log.npt`, `md_npt.xyz`: NPT log and trajectory frames
- `log.nvt`, `md_nvt.xyz`, `<temp>_nvt.traj`: NVT log and trajectory outputs

Notes
- Molecular dynamics should not be run on multiple structures in a single call.
- If the input is a multi-frame `extxyz`, split it into multiple single-structure `extxyz` files and run them one by one.
- Use separate output directories and trajectory files for different structures.





## Relaxation and Molecular Dynamics on Bohrium

Perform structure optimization and molecular dynamics simulations on Bohrium platform using MatterSim.

When submitting MatterGen jobs to Bohrium through `dpdisp`, the image and machine required by MatterSim are obtained from the environment variables `BOHRIUM_MAT_IMAGE` and `BOHRIUM_MAT_MACHINE`. For the `dpdisp` submission procedure, refer to the `dpdisp` skill documentation.

### Batch relaxation

```bash
ts=$(date +"%Y%m%d%H%M%S")
workdir="matsim/${ts}.mattersim_relax"
mkdir -p "$workdir"
cd "$workdir"
```

Then copy the structure to be relaxed into the `workdir`.

In `submission.json`:

- set `command` to a generation command such as:

```bash
/opt/mattergen/.venv/bin/python -m mattersim.cli.mattersim_app relax \
  --structure-file structures.extxyz \
  --device cuda \
  --work-dir results \
  --filter EXPCELLFILTER \
  --fmax 0.01 \
  --steps 2000
```

- `forward_files` should include the structures , such as `generated.extxyz`.
- `backward_files` can be `results`.

After relaxation, extract the structures from results.csv.gz and save them as an extxyz file.


### Batch molecular dynamics

1. Create a timestamped `workdir`:

```bash
ts=$(date +"%Y%m%d%H%M%S")
workdir="matsim/${ts}.mattersim_batch_md"
mkdir -p "$workdir"
cd "$workdir"
```

2. Prepare the input structures. If the input is a multi-frame `extxyz`, split it into single-frame structure files, create numerically indexed subdirectories under `workdir`, and place one `extxyz` file in each directory. Also determine the starting and ending indices, `num_start` and `num_end`.

3. Copy the model file into `workdir`. The model path can be obtained from the `mattersim_model` environment variable. Also copy the [mattersim_moldyn.py](scripts/mattersim_moldyn.py) into `workdir`.

4. Example of `submission.json`:

- Example of `submission.json` can refer to [bohrium-moldyn.md](aseets/bohrium-moldyn.md).



## Finetune MatterSim

Finetune the pre-trained MatterSim model on a custom dataset。

Recommended workflow:

1. Create a timestamped `workdir`:

```bash
ts=$(date +"%Y%m%d%H%M%S")
workdir="matsim/${ts}.mattersim_finetune"
mkdir -p "$workdir"
```
2. Prepare the training and validation datasets in `extxyz` format, and copy them into `workdir`.

Also copy the model file into `workdir`. The model path can be obtained from the `mattersim_model` environment variable.

3. Example of `submission.json`:

- Example of `submission.json` can refer to [finetune.md](aseets/finetune.md).




## Compute Ionic Conductivity

After molecular dynamics, estimate the ionic conductivity of the target mobile ion species such as `Li` or other ions from the MD trajectory.

- For detailed procedures and code examples for conductivity calculation, refer to [conductivity.md](assets/conductivity.md).



## What to report

Report at minimum:
- for batch relaxation: the number of input structures, `optimizer`, `filter`, `fmax`, `steps`, and the absolute path to the relaxation work directory and CSV results
- for batch MD: the number of input structures, whether the input was split before running, temperature, timestep, number of MD steps, ensemble, and the absolute path to each MD work directory, trajectory file
- for ionic conductivity analysis: the target ion species, temperature, the trajectory used, the selected trajectory frame window, `time_step_fs`, `step_skip`, the estimated diffusivity and conductivity with their standard deviations and units, and the absolute paths to the exported MSD data and plot files
