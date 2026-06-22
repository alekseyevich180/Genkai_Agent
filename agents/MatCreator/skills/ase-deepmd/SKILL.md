---
name: ase-deepmd
description: Skills for running ASE molecular dynamics (MD) and structure optimisation using a DeePMD interatomic potential — input preparation, remote batch submission to Bohrium, and result collection.
metadata:
  tools:
    - run_bash
    - run_python_file
  dependent_skills:
    - dpdisp
  tags:
    - ase
    - deepmd
    - md
    - molecular-dynamics
    - structure-optimisation
    - bohrium
---

# ASE / DeePMD Skill

Two scripts handle ASE/DeePMD-specific work; submission is delegated to the `dpdisp` skill:

| Script | Role |
|---|---|
| `ase_deepmd_tools.py` | Prepare job directories; collect results; inspect config |
| `run_ase_job.py` | Self-contained job runner shipped to the compute node |
| `skills/dpdisp/` | Submit prepared directories via DPDispatcher (see `dpdisp-submit` skill) |

`ase_deepmd_tools.py` and `run_ase_job.py` live alongside `config.yaml` and `.env`.
Every command prints JSON to stdout and exits 0 on success, 1 on error.

> **Note:** `bohrium_submit.py` (both the local copy and `skills/bohr/`) is deprecated.
> Always use the `dpdisp-submit` skill with `submission.template.json` for new workflows.

---

## Mandatory workflow sequence

1. **Obtain structures** — supply a multi-frame extxyz (or any ASE-readable file).
2. **Prepare job directories** — run `ase_deepmd_tools.py prepare_md` or `prepare_relax`.  By default the pretrained model is frozen with `dp --pt freeze --head Omat24` before being copied into each job directory, so the runtime `DP` calculator loads a single-task model (no `--head` needed).  Pass `--head none` to skip freezing.
3. **Submit jobs** — generate a `submission.template.json` from the returned `calc_dir_list` and submit via the `dpdisp-submit` skill (see [Submission section](#submission-dpdisp-skill) below).
4. **Collect results** — after jobs finish, run `collect_md` or `collect_relax`.

---

## 1. Prepare MD jobs

```bash
python ase_deepmd_tools.py prepare_md \
    --structures structures.extxyz \
    --model_path /path/to/model.pt \
    --stages '[{"mode":"NVT","temperature_K":300,"runtime_ps":10,"timestep_ps":0.001}]'
```

Multi-stage (heat-up → production):

```bash
python ase_deepmd_tools.py prepare_md \
    --structures structures.extxyz \
    --model_path model.pt \
    --stages '[
        {"mode":"NVT-Langevin","temperature_K":100,"runtime_ps":2},
        {"mode":"NVT",         "temperature_K":300,"runtime_ps":10},
        {"mode":"NPT-aniso",   "temperature_K":300,"pressure":0.0,"runtime_ps":20}
    ]' \
    --save_interval_steps 50 \
    --seed 2024
```

Model on the remote node (no local transfer):

```bash
python ase_deepmd_tools.py prepare_md \
    --structures structures.extxyz \
    --remote_model_path /data/models/dpa2.pt \
    --stages '[{"mode":"NVT","temperature_K":300,"runtime_ps":5}]'
```

**Key flags**

| Flag | Default | Description |
|---|---|---|
| `--structures` | required | Any ASE-readable structure file |
| `--model_path` | env var | Local `.pt` model; copied into every job dir.  Falls back to `DEEPMD_MODEL_PATH`. |
| `--remote_model_path` | — | Remote model path; mutually exclusive with `--model_path` |
| `--stages` | required | JSON list of stage dicts (see schema below) |
| `--frames` | all | Specific frame indices to process |
| `--head` | Omat24 | Multi-task head to freeze (`dp --pt freeze`). Pass `none` to skip freezing and use the model as-is. |
| `--save_interval_steps` | 100 | Trajectory write frequency |
| `--traj_prefix` | traj | Trajectory filename prefix |
| `--seed` | 42 | Velocity initialisation seed |

**Stage dict schema**

```json
{
  "mode":          "NVT",    // NVT|NVT-NH|NVT-Langevin|NVT-Berendsen|NVT-Andersen|NPT-aniso|NPT-tri|NVE
  "temperature_K": 300,
  "pressure":      null,     // GPa — required for NPT modes
  "runtime_ps":    1.0,
  "timestep_ps":   0.0005,   // default 0.5 fs
  "tau_t_ps":      0.01,     // thermostat relaxation time (default 10 fs)
  "tau_p_ps":      0.1       // barostat relaxation time  (default 100 fs)
}
```

---

## 2. Prepare relax jobs

```bash
python ase_deepmd_tools.py prepare_relax \
    --structures structures.extxyz \
    --model_path model.pt \
    --force_tolerance 0.01 \
    --relax_cell
```

| Flag | Default | Description |
|---|---|---|
| `--head` | Omat24 | Multi-task head to freeze (`dp --pt freeze`). Pass `none` to skip freezing and use the model as-is. |
| `--force_tolerance` | 0.01 | Convergence threshold in eV/Å |
| `--max_iterations` | 200 | Maximum BFGS steps |
| `--relax_cell` | false | Also relax lattice parameters (ExpCellFilter) |

---

## 3. Submit via the dpdisp skill {#submission-dpdisp-skill}

Submission uses the `dpdisp` skill (DPDispatcher) with `BohriumContext`.
`bohrium_submit.py` is deprecated — do not use it for new workflows.

### Required environment variables

| Variable | Description |
|---|---|
| `BOHRIUM_EMAIL` | Bohrium account e-mail |
| `BOHRIUM_PASSWORD` | Bohrium account password |
| `BOHRIUM_PROJECT_ID` | Bohrium project ID (integer) |
| `BOHRIUM_DEEPMD_ASE_MACHINE` | Machine/scass type, e.g. `c32_m128_cpu` |
| `BOHRIUM_DEEPMD_ASE_IMAGE` | Container image URI providing ASE + DeePMD |
| `DEEPMD_MODEL_PATH` | Default local model path (used when `--model_path` is omitted) |

### MD jobs

The `prepare_md` command returns a `batch_dir` (the common parent of all job dirs) and
a `calc_dir_list` of individual job directories.  `model.pt` is placed at the **`batch_dir`
level**, shared by all jobs.  Set `work_base` to this `batch_dir` path and upload the model
once via `forward_common_files`.

`submission.template.json`:

```json
{
  "work_base": "<batch_dir>",
  "machine": {
    "batch_type": "Bohrium",
    "context_type": "BohriumContext",
    "local_root": ".",
    "remote_profile": {
      "email": "${BOHRIUM_EMAIL}",
      "password": "${BOHRIUM_PASSWORD}",
      "program_id": ${BOHRIUM_PROJECT_ID},
      "input_data": {
        "job_type": "container",
        "log_file": "log",
        "scass_type": "${BOHRIUM_DEEPMD_ASE_MACHINE}",
        "platform": "ali",
        "image_name": "${BOHRIUM_DEEPMD_ASE_IMAGE}"
      }
    }
  },
  "resources": { "group_size": 1 },
  "forward_common_files": ["model.pt", "run_ase_job.py"],
  "task_list": [
    {
      "command": "python ../run_ase_job.py",
      "task_work_path": "<md_job_dir_name>",
      "forward_files": ["structure.extxyz", "ase_input.json"],
      "backward_files": ["trajectories", "md_simulation.log", "status.json", "log", "err"]
    }
  ]
}
```

- `work_base` must be the `batch_dir` path returned by `prepare_md` (the directory that
  contains `model.pt`, `run_ase_job.py`, and all per-job subdirectories).
- `task_work_path` is the **basename** of each job directory (relative to `batch_dir`),
  e.g. `md_20240324120000_abc12345`.  Add one entry per dir in `calc_dir_list`.
- `forward_common_files` uploads `model.pt` and `run_ase_job.py` once from `batch_dir`
  to the remote working directory (one level above each task dir).  `ase_input.json`
  already references the model as `"../model.pt"`; `run_ase_job.py` is invoked as
  `python ../run_ase_job.py` for the same reason.
- Omit `model.pt` from `forward_common_files` when `--remote_model_path` was used during
  preparation (the model already lives on the remote node).

> **Before submitting:** verify that all `forward_common_files` are present in `batch_dir`:
> ```bash
> ls "<batch_dir>/model.pt" "<batch_dir>/run_ase_job.py"
> ```
> Both files must exist.  `prepare_md` / `prepare_relax` copies them automatically;
> if either is missing, re-run the prepare step before proceeding with submission.

### Relax jobs

Same structure as MD jobs.  Use the `batch_dir` returned by `prepare_relax` as `work_base`
and add the task-level fields for each job in `calc_dir_list`:

```json
{
  "command": "python ../run_ase_job.py",
  "task_work_path": "<relax_job_dir_name>",
  "forward_files": ["structure.extxyz", "ase_input.json"],
  "backward_files": [
    "structure_optimized.cif",
    "structure_optimization_traj.extxyz",
    "optimization.log",
    "status.json",
    "log",
    "err"
  ]
}
```

File manifests summary:

| Level | Files |
|---|---|
| **`forward_common_files`** (at `work_base` / `batch_dir`) | `model.pt`* `run_ase_job.py` |
| **`forward_files`** per MD task | `structure.extxyz` `ase_input.json` |
| **`forward_files`** per Relax task | `structure.extxyz` `ase_input.json` |
| **`backward_files`** MD | `trajectories` `md_simulation.log` `status.json` `log` `err` |
| **`backward_files`** Relax | `structure_optimized.cif` `structure_optimization_traj.extxyz` `optimization.log` `status.json` `log` `err` |

(*) omit from `forward_common_files` when `--remote_model_path` was used during preparation.

### Substitute, validate, and submit

```bash
envsubst '${BOHRIUM_EMAIL} ${BOHRIUM_PASSWORD} ${BOHRIUM_PROJECT_ID} ${BOHRIUM_DEEPMD_ASE_MACHINE} ${BOHRIUM_DEEPMD_ASE_IMAGE}' \
    < submission.template.json > submission.json

uv run -m json.tool submission.json >/dev/null
uvx --with dpdispatcher dargs check -f dpdispatcher.entrypoints.submit.submission_args submission.json

# Always use --with oss2 for Bohrium jobs
uvx --from dpdispatcher --with oss2 dpdisp submit submission.json
```

For long-running MD jobs, wrap in `tmux`:

```bash
tmux new-session -d -s ase_md \
    "uvx --from dpdispatcher --with oss2 dpdisp submit submission.json"
tmux ls
```

---

## 4. Collect results

**MD** — merge all trajectory frames into one extxyz:

```bash
python ase_deepmd_tools.py collect_md \
    --calc_dirs /tmp/ase_deepmd_jobs/md_*
```

**Relax** — merge all optimised structures into one extxyz:

```bash
python ase_deepmd_tools.py collect_relax \
    --calc_dirs /tmp/ase_deepmd_jobs/relax_*
```

Both commands accept `--output_dir` to control where the merged file is written.

---

## 5. Inspect the default model path

Query which model file will be used when `--model_path` / `--remote_model_path` are omitted:

```bash
python ase_deepmd_tools.py show_model_path
```

Example output (path is set and the file exists):

```json
{
  "status": "ok",
  "model_path": "/data/models/dpa2.pt",
  "exists": true
}
```

Example output (variable not configured):

```json
{
  "status": "not_set",
  "model_path": null,
  "message": "DEEPMD_MODEL_PATH is not set in the environment or .env file."
}
```

Use this command to verify that `DEEPMD_MODEL_PATH` is correctly configured before running a large batch of jobs.

---

## Running locally (no remote submission)

Each prepared job directory is fully self-contained.  Run it directly:

```bash
cd /tmp/ase_deepmd_jobs/md_20240324120000_abc12345
python /path/to/skills/ase_deepmd/run_ase_job.py
```

Or copy `run_ase_job.py` into the job dir first:

```bash
cp /path/to/skills/ase_deepmd/run_ase_job.py .
python run_ase_job.py
```

---

## config.yaml

```yaml
work_dir: /tmp/ase_deepmd_jobs   # base directory for all prepared job dirs
```
