---
name: mlip
description: Prepare, validate, and submit UMA/fairchem machine-learning interatomic potential calculations on Genkai with the established PJM launcher and UMA virtual environment. Use for MLIP or UMA structure relaxation, molecular dynamics, energy/force inference, GPU calculations, PJM submission, restart preparation, or locating and reporting calculation outputs.
---

# MLIP calculations with UMA

Use `scripts/submit_uma_calculation.sh` as the single execution launcher. Keep each calculation self-contained in one run directory so inputs, generated structures, trajectories, logs, and scheduler output remain together.

## Runtime contract

- Use `/home/pj24001724/ku40000345/wu/UMA-campare/.venv_uma` by default.
- Let the launcher activate that environment by setting `VIRTUAL_ENV`, updating `PATH`, and calling its Python executable directly. Do not install packages or create another environment unless the default environment fails validation.
- Use the shared fairchem and matplotlib caches under `/home/pj24001724/ku40000345/wu/UMA-campare`.
- Keep model downloads disabled by default. Set `UMA_ALLOW_DOWNLOAD=1` only when the requested model is absent and the user has approved network-backed model retrieval.
- Run CUDA jobs through PJM. Use local execution only for `UMA_DRY_RUN=1` validation.

## Prepare one calculation

1. Create a timestamped run directory under the current session/workspace:

   ```bash
   ts=$(date +%Y%m%d%H%M%S)
   run_dir="${MATCLAW_SESSION_DIR:-$PWD}/mlip/${ts}.uma_<task>"
   mkdir -p "$run_dir"
   ```

2. Copy the Python entrypoint and every required input structure/configuration into `run_dir`. Prefer portable relative paths inside the Python program. Do not point a run at mutable inputs elsewhere when a calculation may need to be reproduced.
3. Inspect the Python entrypoint before submission. Confirm that its UMA model, fairchem task name, device, input filenames, convergence settings, and output filenames match the request. Remove any `os.chdir(...)` that redirects output outside `run_dir`.
4. Treat `run_dir` as both `UMA_WORK_DIR` and the calculation output location. Expected outputs include relaxed structures, energies/forces, trajectories, optimizer/MD logs, and the PJM combined stdout/stderr file.

## Validate before submission

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

## Submit on Genkai

Submit from inside the run directory so the PJM combined log is also created there:

```bash
cd "$run_dir"
pjsub -o "$run_dir/uma_calc.out" \
  -x "UMA_WORK_DIR=$run_dir,UMA_PYTHON_SCRIPT=run_gpu.py,UMA_DEVICE=cuda,UMA_THREADS=40" \
  /absolute/path/to/agents/Agent/skills/mlip/scripts/submit_uma_calculation.sh
```

If the Python entrypoint needs command-line arguments, add `UMA_PYTHON_ARGS=<arguments>` to the comma-separated `-x` value. Use this only for simple space-separated arguments without commas; edit a copied task-specific Python/config file for complex values.

Do not submit until the user has approved the actual calculation command and resource request. The bundled PJM defaults request one GPU in `b-batch` for 72 hours.

## Overrides

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

## Completion report

Report the PJM job ID, model/task/device, run status, and absolute `run_dir`. List the primary output files and the combined PJM log at `run_dir/uma_calc.out`. If a calculation fails, preserve the entire run directory and quote the first actionable traceback or scheduler error; do not silently move partial outputs.
