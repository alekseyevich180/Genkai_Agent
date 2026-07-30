---
name: mace
description: Use when structures need pretrained MACE energy, force, or relaxation inference; do not use for DeepMD training or UMA fine-tuning.
metadata:
  maturity: stable
  domain: mlip
  tools:
    - run_bash
  dependent_skills: []
  consumes:
    - structure-set@1
  produces:
    - calculation-result@1
  entrypoints:
    - scripts/submit_mace_calculation.sh
---

# MACE calculations on Genkai

Use `scripts/submit_mace_calculation.sh` with the established runtime at
`/home/pj24001724/ku40000345/wu/MACE`. Keep each calculation and all outputs in
one caller-owned run directory.

## Workflow

1. Create a timestamped directory and copy every structure or task-specific
   entrypoint into it.
2. Inspect the selected model, device, task, convergence settings, and outputs.
3. Run the launcher with `MACE_DRY_RUN=1`.
4. Start a real calculation only after the user approves the model, resources,
   and exact command. Use PJM for CUDA or long calculations.
5. Report the model, task, device, run directory, result files, and scheduler
   log without overstating a dry-run as scientific validation.

## Dry-run

```bash
run_dir="${MATCLAW_SESSION_DIR:-$PWD}/mace_run"
mkdir -p "$run_dir"
cp POSCAR "$run_dir/"

MACE_DRY_RUN=1 \
MACE_WORK_DIR="$run_dir" \
MACE_DEVICE=cpu \
MACE_MODEL=small \
MACE_PYTHON_ARGS="--input POSCAR --task single-point" \
bash agents/Agent/skills/mace/scripts/submit_mace_calculation.sh
```

Use `run_skill_script` only for this non-computing dry-run:

```text
run_skill_script(
  skill_name="mace",
  script_name="submit_mace_calculation.sh",
  args=""
)
```

## Submission

After approval, submit from the run directory:

```bash
cd "$run_dir"
pjsub -o "$run_dir/mace_calc.out" \
  -x "MACE_WORK_DIR=$run_dir,MACE_DEVICE=cuda,MACE_MODEL=small,MACE_THREADS=40,MACE_PYTHON_ARGS=--input POSCAR --task relax --fmax 0.05 --steps 500" \
  /absolute/path/to/agents/Agent/skills/mace/scripts/submit_mace_calculation.sh
```

Genkai `pjsub -x` assignments are comma-separated. Use a copied Python
entrypoint or configuration instead of complex shell arguments.

## Key overrides

| Variable | Default |
|---|---|
| `MACE_RUNTIME_DIR` | `/home/pj24001724/ku40000345/wu/MACE` |
| `MACE_VENV_DIR` | `$MACE_RUNTIME_DIR/.venv` |
| `MACE_WORK_DIR` | submission/session directory |
| `MACE_PYTHON_SCRIPT` | shared generic MACE entrypoint |
| `MACE_PYTHON_ARGS` | empty |
| `MACE_MODEL` | `small` |
| `MACE_DEVICE` | `cuda` |
| `MACE_THREADS` | `40` |
| `MACE_DRY_RUN` | `0` |

The generic single-point workflow writes `results.json` and
`evaluated.extxyz`; relaxation additionally writes `relaxed.extxyz`,
`optimization.traj`, and `optimization.log`.
