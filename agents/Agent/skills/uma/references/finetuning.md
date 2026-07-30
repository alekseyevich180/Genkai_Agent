# UMA fine-tuning on Genkai

Use this reference only for UMA dataset preparation, fine-tuning, checkpoint
resume, or fine-tuned-model handoff. Pretrained UMA inference remains in
`SKILL.md`.

## Contents

- Runtime contract
- Scientific decisions before conversion
- Project layout
- Dataset preparation
- Training and resume
- Completion and model handoff
- Source basis

## Runtime contract

- Reuse `/home/pj24001724/ku40000345/wu/UMA-campare/.venv_uma`.
- The verified environment contains `fairchem-core 2.21.0`, Torch
  `2.8.0+cu128`, `fairchem`, and cached `uma-s-1p2`. The current installation
  is editable from `UMA-campare/fairchem-src` at tag
  `fairchem_core-2.21.0`; the preparation launcher also discovers a wheel
  layout without relying on a hard-coded Python minor version.
- Keep raw data, audit reports, ASE-LMDB, generated Hydra YAML, runs,
  checkpoints, and evaluation reports in the caller's project.
- Keep Hugging Face offline unless the user explicitly approves a model
  download. Disable W&B by default.
- Treat every Hydra YAML containing `_target_` as executable code. Run only a
  locally generated or otherwise trusted configuration.
- A 2.21.0 wheel contains `create_uma_finetune_dataset.py`, but omits its
  repository-level Hydra templates. The skill therefore vendors the matching
  official templates from the `fairchem_core-2.21.0` tag under
  `assets/fairchem-core-2.21.0/`, so project behavior does not depend on a
  mutable external source checkout.
- `ase-db-backends 0.10.0` requests a 2 TiB writable LMDB map while the Genkai
  login environment can impose a much smaller virtual-memory limit. The
  preparation launcher scopes the writable map to 16 GiB per shard through a
  compatibility wrapper. Override `UMA_FINETUNE_LMDB_MAP_SIZE_BYTES` only when
  dataset size and the execution node's limits justify it.

The installed converter is the source of truth for CLI syntax. It accepts
`--regression-tasks` (plural), only train/val directories, and the task names
`omol`, `odac`, `oc20`, `oc25`, `omat`, and `omc`. It does not accept `oc22`.
Although `uma-s-1p2` can expose an `oc22` inference task, PBE+U oxide
fine-tuning needs a separately maintained and validated task configuration.
Never relabel PBE+U data as `oc25` or bypass the converter check. Preserve the
independent test split outside ASE-LMDB generation for final evaluation.

## Scientific decisions before conversion

1. Fix one internally consistent DFT labeling standard, including functional,
   dispersion, pseudopotential, Hubbard U, spin, cutoff, k-points, smearing,
   dipole correction, convergence, units, and stress convention.
2. Select exactly one UMA task supported by the actual converter. Use `oc25`
   only for RPBE+D3 surface/adsorption data. Do not combine task heads in a
   first fine-tuning campaign.
3. Use `ef` for fixed-cell surface relaxation and MD; use `efs` only when
   stress labels are consistent and required. Avoid energy-only training when
   force-driven simulations are the goal.
4. Split by complete trajectory or physical group. Never randomly distribute
   neighboring frames across train, validation, and test.
5. Include clean slab and gas-phase references when adsorption energies are a
   target. Include distorted, trajectory, and controlled repulsive
   configurations rather than only relaxed minima.
6. Establish an original-UMA baseline and a fixed test set before training.
7. For a surface reaction, include reactants, intermediates, products,
   transition-state or NEB/path images, approach/desorption and distorted
   configurations, plus matching clean-slab and gas-phase references.
   Paper-derived adsorption candidates alone do not cover a reaction pathway.

## Project layout

```text
uma_surface_finetune/
├── data/
│   ├── train/
│   ├── val/
│   ├── test/
│   └── lmdb/
├── metadata/
├── runs/
└── reports/
```

The audit checks readable frames, finite cell/positions, energy labels,
requested force/stress labels, suspicious short distances, severe overlaps,
exact duplicates within a split, and exact leakage across all present
train/val/test splits. The test split is audited but is never sent to the
converter. The audit cannot verify DFT convergence, units, theory-level
consistency, or semantic trajectory grouping; inspect those from provenance
metadata.

## Dataset preparation

Preview without reading or converting structures:

```bash
UMA_FINETUNE_DRY_RUN=1 \
UMA_FINETUNE_WORK_DIR="$run_dir" \
UMA_FINETUNE_TASK=oc25 \
UMA_FINETUNE_REGRESSION_TASKS=ef \
UMA_FINETUNE_BASE_MODEL=uma-s-1p2 \
bash agents/Agent/skills/uma/scripts/prepare_uma_finetune_dataset.sh
```

Remove `UMA_FINETUNE_DRY_RUN=1` only after checking the printed paths. The
script first writes `metadata/uma_finetune_data_audit.json`, then creates a new
`data/lmdb/` and the generated `uma_sm_finetune_template.yaml`. It subsequently
rejects non-empty `*.failed`, reads train/val ASE-LMDB back, and composes the
Hydra configuration before writing
`metadata/uma_finetune_dataset_verification.json`. The official converter
refuses an existing output directory; use a versioned new directory instead of
overwriting a prior dataset.

Key preparation overrides:

| Variable | Default |
|---|---|
| `UMA_FINETUNE_TRAIN_DIR` | `$work_dir/data/train` |
| `UMA_FINETUNE_VAL_DIR` | `$work_dir/data/val` |
| `UMA_FINETUNE_TEST_DIR` | `$work_dir/data/test` when present; audit only |
| `UMA_FINETUNE_OUTPUT_DIR` | `$work_dir/data/lmdb` |
| `UMA_FINETUNE_AUDIT_REPORT` | `$work_dir/metadata/uma_finetune_data_audit.json` |
| `UMA_FINETUNE_VERIFY_REPORT` | `$work_dir/metadata/uma_finetune_dataset_verification.json` |
| `UMA_FINETUNE_TASK` | `oc25` |
| `UMA_FINETUNE_REGRESSION_TASKS` | `ef` |
| `UMA_FINETUNE_BASE_MODEL` | `uma-s-1p2` |
| `UMA_FINETUNE_NUM_WORKERS` | `1` for the first diagnosable conversion |
| `UMA_FINETUNE_MIN_DISTANCE` | `0.6` A warning threshold |
| `UMA_FINETUNE_REJECT_DISTANCE` | `0.4` A hard rejection threshold |
| `UMA_FINETUNE_LMDB_MAP_SIZE_BYTES` | `17179869184` (16 GiB per shard) |

## Training and resume

Inspect both generated YAML files before use. Confirm task, label set, absolute
dataset paths, base model, `epochs` versus `steps`, learning rate, batch size,
neighbor count, validation/checkpoint cadence, and output directory. A
conservative first comparison commonly explores `lr=2e-4`, `1e-4`, and `5e-5`
with independent runs; do not copy the MACE from-scratch learning rate.

Preview the exact command:

```bash
UMA_FINETUNE_DRY_RUN=1 \
UMA_FINETUNE_WORK_DIR="$run_dir" \
UMA_FINETUNE_CONFIG="$run_dir/data/lmdb/uma_sm_finetune_template.yaml" \
UMA_FINETUNE_RUN_DIR="$run_dir/runs" \
UMA_FINETUNE_ARGS="epochs=20 lr=1e-4 batch_size=2 max_neighbors=300" \
bash agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh
```

For common overrides, the launcher also accepts
`UMA_FINETUNE_EPOCHS`, `UMA_FINETUNE_STEPS`, `UMA_FINETUNE_LR`,
`UMA_FINETUNE_BATCH_SIZE`, `UMA_FINETUNE_MAX_NEIGHBORS`, and
`UMA_FINETUNE_ID`. Set only one of epochs or steps. Use
`UMA_FINETUNE_ARGS` for additional simple Hydra overrides, and do not repeat a
key already supplied through a dedicated variable. The dry-run composes the
trusted Hydra configuration and checks `scheduler.mode=LOCAL`, one matching
train/val task, and exactly one active training-length control.

After the user approves model, task, data version, hyperparameters, resources,
and exact command, submit from the project directory:

```bash
cd "$run_dir"
pjsub -o "$run_dir/uma_finetune.out" \
  -x "UMA_FINETUNE_WORK_DIR=$run_dir,UMA_FINETUNE_CONFIG=$run_dir/data/lmdb/uma_sm_finetune_template.yaml,UMA_FINETUNE_RUN_DIR=$run_dir/runs,UMA_FINETUNE_DEVICE=cuda,UMA_FINETUNE_THREADS=40,UMA_FINETUNE_ARGS=epochs=20 lr=1e-4 batch_size=2 max_neighbors=300" \
  /absolute/path/to/agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh
```

Genkai `pjsub -x` assignments are comma-separated; the Hydra override value
contains spaces but no commas. For complex overrides, edit a copied trusted
YAML instead of relying on shell argument splitting.

Resume from a generated checkpoint configuration:

```bash
UMA_FINETUNE_DRY_RUN=1 \
UMA_FINETUNE_MODE=resume \
UMA_FINETUNE_WORK_DIR="$run_dir" \
UMA_FINETUNE_CONFIG="$run_dir/runs/<run>/checkpoints/final/resume.yaml" \
bash agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh
```

Do not call `run_skill_script` for conversion, training, resume, or evaluation;
it is permitted only for the launchers' non-computing dry runs.

## Completion and model handoff

Preserve the generated configuration, audit JSON, dataset checksums, software
versions, random seed, GPU information, training log, best checkpoint,
`resume.yaml`, and `inference_ckpt.pt`. Load the final inference checkpoint
with `load_predict_unit()` and always use the same task name used for
fine-tuning.

Compare original UMA and the fine-tuned model on:

- energy and force MAE/RMSE, including surface and adsorbate atom subsets;
- adsorption, surface, defect, and reaction energies;
- site ordering and relaxed geometry;
- short 300 K and high-temperature stability checks;
- bulk, gas molecule, new surface, and new-defect subsets for catastrophic
  forgetting.

Training loss alone is not an acceptance criterion.

## Source basis

- Verified local Genkai guide and example:
  `/home/pj24001724/ku40000345/wu/UMA-campare/finetune/UMA_表面知识微调操作指南.md`
  and `/home/pj24001724/ku40000345/wu/UMA-campare/finetune/example/`
- FAIRChem `fairchem_core-2.21.0` fine-tuning documentation:
  <https://github.com/facebookresearch/fairchem/blob/fairchem_core-2.21.0/docs/core/common_tasks/fine_tuning.md>
- Version-matched dataset converter:
  <https://github.com/facebookresearch/fairchem/blob/fairchem_core-2.21.0/src/fairchem/core/scripts/create_uma_finetune_dataset.py>
- Version-matched Hydra templates:
  <https://github.com/facebookresearch/fairchem/tree/fairchem_core-2.21.0/configs/uma/finetune>
