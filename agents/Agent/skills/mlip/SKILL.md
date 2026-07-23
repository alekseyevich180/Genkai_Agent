---
name: mlip
description: Prepare, validate, and submit MACE, DeePMD-kit/DeepMD/DeepModel, or UMA/fairchem machine-learning interatomic potential calculations on Genkai with established PJM launchers and project-local virtual environments. Use for MLIP training, fine-tuning, freezing, compression, testing, structure relaxation, molecular dynamics, energy/force inference, CPU or GPU calculations, PJM submission, restart preparation, or locating and reporting calculation outputs.
---

# MLIP calculations with MACE, DeepMD, or UMA

Use `scripts/submit_mace_calculation.sh` for MACE, `scripts/submit_deepmd_calculation.sh` for DeePMD-kit, and `scripts/submit_uma_calculation.sh` for UMA. Keep each calculation self-contained in one run directory so inputs, models, generated structures, trajectories, logs, and scheduler output remain together.

## MACE calculations

Use `/home/pj24001724/ku40000345/wu/MACE` as the default MACE runtime. Its bundled generic entrypoint supports MACE-MP single-point energy/force evaluation and atomic/cell relaxation for any ASE-readable structure. It writes every result into `MACE_WORK_DIR`.

Create a self-contained task directory and copy every input into it:

```bash
ts=$(date +%Y%m%d%H%M%S)
run_dir="${MATCLAW_SESSION_DIR:-$PWD}/mlip/${ts}.mace_<task>"
mkdir -p "$run_dir"
cp POSCAR "$run_dir/"
```

Validate the calculation without running it:

```bash
MACE_DRY_RUN=1 \
MACE_WORK_DIR="$run_dir" \
MACE_DEVICE=cpu \
MACE_MODEL=small \
MACE_PYTHON_ARGS="--input POSCAR --task single-point" \
bash agents/Agent/skills/mlip/scripts/submit_mace_calculation.sh
```

For agent tool execution, use `run_skill_script` only for this non-computing dry run:

```text
run_skill_script(
  skill_name="mlip",
  script_name="submit_mace_calculation.sh",
  args=""
)
```

Set `MACE_DRY_RUN=1`, `MACE_WORK_DIR`, and `MACE_PYTHON_ARGS` in the execution environment before calling it. Do not use `run_skill_script` to start a long CPU or GPU calculation.

Submit a GPU task from inside the run directory after the user approves the exact model, task, resources, and command:

```bash
cd "$run_dir"
pjsub -o "$run_dir/mace_calc.out" \
  -x "MACE_WORK_DIR=$run_dir,MACE_DEVICE=cuda,MACE_MODEL=small,MACE_THREADS=40,MACE_PYTHON_ARGS=--input POSCAR --task relax --fmax 0.05 --steps 500" \
  /absolute/path/to/agents/Agent/skills/mlip/scripts/submit_mace_calculation.sh
```

Genkai `pjsub -x` variables must be comma-separated. Use `MACE_PYTHON_SCRIPT` to replace the bundled generic entrypoint with a task-specific Python program. Keep simple space-separated arguments in `MACE_PYTHON_ARGS`; use a copied task configuration for complex values.

| Variable | Default | Purpose |
|---|---|---|
| `MACE_RUNTIME_DIR` | `/home/pj24001724/ku40000345/wu/MACE` | Shared MACE runtime and caches |
| `MACE_VENV_DIR` | `$MACE_RUNTIME_DIR/.venv` | Virtual environment to activate |
| `MACE_PYTHON_BIN` | `$MACE_VENV_DIR/bin/python` | Explicit Python override |
| `MACE_WORK_DIR` | submission/session directory | Calculation input and output directory |
| `MACE_PYTHON_SCRIPT` | bundled generic MACE entrypoint | Task-specific Python override |
| `MACE_PYTHON_ARGS` | empty | Simple space-separated entrypoint arguments |
| `MACE_MODEL` | `small` | MACE-MP shortcut or checkpoint path |
| `MACE_DEVICE` | `cuda` | `cpu` or `cuda` |
| `MACE_THREADS` | `40` | Host-side OpenMP/BLAS thread count |
| `MACE_DRY_RUN` | `0` | Validate and print without computing when `1` |

Expected single-point outputs are `results.json` and `evaluated.extxyz`. Relaxation additionally writes `relaxed.extxyz`, `optimization.traj`, and `optimization.log`. Report the model, task, device, job ID or local status, absolute run directory, primary outputs, and `mace_calc.out` when submitted through PJM.

## DeepMD calculations

Use `/home/pj24001724/ku40000345/wu/deepmd_kit` as the runtime source and `/home/pj24001724/ku40000345/wu/deepmd_train` as the established training/workflow source:

- `deepmd_kit/dp_venv` contains the Python 3.12 DeePMD environment and `dp` CLI.
- `deepmd_kit/deepmd_root/bin/lmp` is the DeepMD-enabled LAMMPS executable.
- `deepmd_train` contains task inputs, training data, checkpoints, frozen/compressed models, and previously executed PJM workflows.

Do not run `dp_venv/bin/dp` without loading `python/3.12.11`; the venv Python depends on that module's shared libraries. The bundled launcher reproduces `deepmd_kit/use.sh` with an absolute venv path so it does not depend on the caller's `HOME`.

### Prepare and validate a generic DeepMD task

Create a self-contained task directory. Copy the input JSON and any task-specific inputs into it. Inspect every `training_data.systems` and `validation_data.systems` path in the JSON before submission; either stage the referenced data with the task or retain only verified immutable absolute paths.

```bash
ts=$(date +%Y%m%d%H%M%S)
run_dir="${MATCLAW_SESSION_DIR:-$PWD}/mlip/${ts}.deepmd_<task>"
mkdir -p "$run_dir"
cp input.json "$run_dir/"
```

Validate the runtime paths and exact command without loading modules or starting a calculation:

```bash
DEEPMD_DRY_RUN=1 \
DEEPMD_WORK_DIR="$run_dir" \
DEEPMD_MODE=dp \
DEEPMD_BACKEND=tensorflow \
DEEPMD_COMMAND=train \
DEEPMD_ARGS="input.json" \
DEEPMD_REQUIRED_PATHS="input.json" \
bash agents/Agent/skills/mlip/scripts/submit_deepmd_calculation.sh
```

For agent tool execution, use `run_skill_script` only for this non-computing dry run:

```text
run_skill_script(
  skill_name="mlip",
  script_name="submit_deepmd_calculation.sh",
  args=""
)
```

Set `DEEPMD_DRY_RUN=1`, `DEEPMD_WORK_DIR`, `DEEPMD_MODE`, `DEEPMD_COMMAND`, `DEEPMD_ARGS`, and `DEEPMD_REQUIRED_PATHS` in the execution environment first. Do not use `run_skill_script` to start training or molecular dynamics. A dry run validates paths and command construction but intentionally does not load the Python module or import TensorFlow.

### Submit a generic DeepMD task

Submit only after the user approves the input, backend, resources, restart/init behavior, and exact command:

```bash
cd "$run_dir"
pjsub -o "$run_dir/deepmd_calc.out" \
  -x "DEEPMD_WORK_DIR=$run_dir,DEEPMD_MODE=dp,DEEPMD_BACKEND=tensorflow,DEEPMD_COMMAND=train,DEEPMD_ARGS=input.json,DEEPMD_REQUIRED_PATHS=input.json,DEEPMD_THREADS=15" \
  /absolute/path/to/agents/Agent/skills/mlip/scripts/submit_deepmd_calculation.sh
```

The launcher defaults to TensorFlow on CPU, matching the executed workflows under `deepmd_train`; its PJM header does not request a GPU. Set `DEEPMD_BACKEND=pytorch`, `jax`, or `paddle`, or add GPU resources, only after validating that backend/device combination in `dp_venv`. After runtime changes, separately run the launcher's non-computing `dp --version` and LAMMPS `-help` checks before submitting a scientific task.

Preview post-training operations as explicit dry-run tasks in the same directory. Submit the approved commands through PJM to execute them:

```bash
cd "$run_dir"

# Freeze the current checkpoint.
DEEPMD_DRY_RUN=1 DEEPMD_COMMAND=freeze \
DEEPMD_ARGS="-o graph.pb" DEEPMD_REQUIRED_PATHS="checkpoint" \
bash agents/Agent/skills/mlip/scripts/submit_deepmd_calculation.sh

# Compress the frozen model.
DEEPMD_DRY_RUN=1 DEEPMD_COMMAND=compress \
DEEPMD_ARGS="-i graph.pb -o compress.pb" DEEPMD_REQUIRED_PATHS="graph.pb" \
bash agents/Agent/skills/mlip/scripts/submit_deepmd_calculation.sh

# Test a frozen model against one DeepMD dataset.
DEEPMD_DRY_RUN=1 DEEPMD_COMMAND=test \
DEEPMD_ARGS="-m graph.pb -s validation_data -n 40" \
DEEPMD_REQUIRED_PATHS="graph.pb validation_data" \
bash agents/Agent/skills/mlip/scripts/submit_deepmd_calculation.sh

# Run DeepMD-enabled LAMMPS.
DEEPMD_DRY_RUN=1 DEEPMD_MODE=lammps \
DEEPMD_ARGS="-in in.lammps" DEEPMD_REQUIRED_PATHS="in.lammps" \
bash agents/Agent/skills/mlip/scripts/submit_deepmd_calculation.sh
```

Use `pjsub` rather than direct login-node execution for long training, testing, or MD jobs.

### Continue the established nnp_train workflow

When the request explicitly targets `/home/pj24001724/ku40000345/wu/deepmd_train/nnp_train`, inspect and use its task-specific `wu_deep.sh` rather than reconstructing its multi-stage logic. It handles training or checkpoint continuation, freeze, compression, per-system testing, optional LAMMPS, and timeout-based resubmission.

Before submitting it, confirm `TRAIN_ID`, `INPUT_NAME`, `BASE_CKPT`, `TRAIN_MODE`, and `DP_TEST_N`. Use `TRAIN_MODE=init` to initialize weights while resetting the step and learning-rate schedule for fine-tuning; use `restart` only to continue the original checkpoint schedule. Its automatic resubmission has previously encountered scheduler-wrapper failures, so inspect the end of the current output before relying on it.

### DeepMD overrides and outputs

| Variable | Default | Purpose |
|---|---|---|
| `DEEPMD_RUNTIME_DIR` | `/home/pj24001724/ku40000345/wu/deepmd_kit` | DeepMD runtime, venv, and LAMMPS installation |
| `DEEPMD_TRAINING_ROOT` | `/home/pj24001724/ku40000345/wu/deepmd_train` | Established training/workflow source |
| `DEEPMD_VENV_DIR` | `$DEEPMD_RUNTIME_DIR/dp_venv` | DeepMD virtual environment |
| `DEEPMD_BIN` | `$DEEPMD_VENV_DIR/bin/dp` | DeePMD CLI override |
| `DEEPMD_LMP_BIN` | `$DEEPMD_RUNTIME_DIR/deepmd_root/bin/lmp` | DeepMD-enabled LAMMPS |
| `DEEPMD_PYTHON_MODULE` | `python/3.12.11` | Required Genkai Python module |
| `DEEPMD_WORK_DIR` | submission/session directory | Input and output directory |
| `DEEPMD_MODE` | `dp` | Run `dp` or `lammps` |
| `DEEPMD_BACKEND` | `tensorflow` | TensorFlow, PyTorch, JAX, or Paddle backend |
| `DEEPMD_COMMAND` | `train` | `dp` subcommand |
| `DEEPMD_ARGS` | empty | Simple whitespace-separated command arguments |
| `DEEPMD_REQUIRED_PATHS` | empty | Required input files/directories checked before execution |
| `DEEPMD_THREADS` | `15` | Host thread and TensorFlow pool limit |
| `DEEPMD_DRY_RUN` | `0` | Validate and print without loading modules or computing |

Depending on `input.json`, expected training outputs include `model.ckpt*`, `checkpoint`, `lcurve.out`, and scheduler logs. Freezing/compression typically produces `graph.pb` and `compress.pb`; testing may produce result tables/logs; LAMMPS produces `log.lammps`, dumps, trajectories, and task-specific summaries. Report the backend, operation, input or checkpoint, job ID/status, absolute run directory, primary outputs, and `deepmd_calc.out`.

## UMA calculations

### UMA runtime contract

- Use `/home/pj24001724/ku40000345/wu/UMA-campare/.venv_uma` by default.
- Let the launcher activate that environment by setting `VIRTUAL_ENV`, updating `PATH`, and calling its Python executable directly. Do not install packages or create another environment unless the default environment fails validation.
- Use the shared fairchem and matplotlib caches under `/home/pj24001724/ku40000345/wu/UMA-campare`.
- Keep model downloads disabled by default. Set `UMA_ALLOW_DOWNLOAD=1` only when the requested model is absent and the user has approved network-backed model retrieval.
- Run CUDA jobs through PJM. Use local execution only for `UMA_DRY_RUN=1` validation.

### Prepare one UMA calculation

1. Create a timestamped run directory under the current session/workspace:

   ```bash
   ts=$(date +%Y%m%d%H%M%S)
   run_dir="${MATCLAW_SESSION_DIR:-$PWD}/mlip/${ts}.uma_<task>"
   mkdir -p "$run_dir"
   ```

2. Copy the Python entrypoint and every required input structure/configuration into `run_dir`. Prefer portable relative paths inside the Python program. Do not point a run at mutable inputs elsewhere when a calculation may need to be reproduced.
3. Inspect the Python entrypoint before submission. Confirm that its UMA model, fairchem task name, device, input filenames, convergence settings, and output filenames match the request. Remove any `os.chdir(...)` that redirects output outside `run_dir`.
4. Treat `run_dir` as both `UMA_WORK_DIR` and the calculation output location. Expected outputs include relaxed structures, energies/forces, trajectories, optimizer/MD logs, and the PJM combined stdout/stderr file.

### Validate UMA before submission

Run the bundled launcher locally in dry-run mode:

```bash
UMA_DRY_RUN=1 \
UMA_WORK_DIR="$run_dir" \
UMA_PYTHON_SCRIPT="run_gpu.py" \
bash agents/Agent/skills/mlip/scripts/submit_uma_calculation.sh
```

The preflight must report the expected absolute work directory, virtual-environment Python, entrypoint, device, thread count, cache directory, output location, and complete Python command. Fix every preflight error before submitting.

For agent tool execution, use `run_skill_script` only for this non-computing dry run:

```text
run_skill_script(
  skill_name="mlip",
  script_name="submit_uma_calculation.sh",
  args=""
)
```

Set `UMA_DRY_RUN=1`, `UMA_WORK_DIR`, and `UMA_PYTHON_SCRIPT` in the execution environment before calling it. Do not use `run_skill_script` to start a long GPU calculation.

### Submit UMA on Genkai

Submit from inside the run directory so the PJM combined log is also created there:

```bash
cd "$run_dir"
pjsub -o "$run_dir/uma_calc.out" \
  -x "UMA_WORK_DIR=$run_dir,UMA_PYTHON_SCRIPT=run_gpu.py,UMA_DEVICE=cuda,UMA_THREADS=40" \
  /absolute/path/to/agents/Agent/skills/mlip/scripts/submit_uma_calculation.sh
```

If the Python entrypoint needs command-line arguments, add `UMA_PYTHON_ARGS=<arguments>` to the comma-separated `-x` value. Use this only for simple space-separated arguments without commas; edit a copied task-specific Python/config file for complex values.

Do not submit until the user has approved the actual calculation command and resource request. The bundled PJM defaults request one GPU in `b-batch` for 72 hours.

### UMA overrides

| Variable | Default | Purpose |
|---|---|---|
| `UMA_RUNTIME_DIR` | `/home/pj24001724/ku40000345/wu/UMA-campare` | Shared UMA runtime and caches |
| `UMA_VENV_DIR` | `$UMA_RUNTIME_DIR/.venv_uma` | Virtual environment to activate |
| `UMA_PYTHON_BIN` | `$UMA_VENV_DIR/bin/python` | Explicit Python override |
| `UMA_WORK_DIR` | submission/session directory | Calculation input and output directory |
| `UMA_PYTHON_SCRIPT` | `run_gpu.py` | Python entrypoint, relative to work directory or absolute |
| `UMA_PYTHON_ARGS` | empty | Simple space-separated entrypoint arguments |
| `UMA_DEVICE` | `cuda` | Device checked before execution |
| `UMA_THREADS` | `40` | Host-side OpenMP/BLAS thread count |
| `UMA_ALLOW_DOWNLOAD` | `0` | Enable model download when set to `1` |
| `UMA_DRY_RUN` | `0` | Validate and print without computing when set to `1` |

### UMA completion report

Report the PJM job ID, model/task/device, run status, and absolute `run_dir`. List the primary output files and the combined PJM log at `run_dir/uma_calc.out`. If a calculation fails, preserve the entire run directory and quote the first actionable traceback or scheduler error; do not silently move partial outputs.
