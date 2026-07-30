---
name: uma
description: Use when a validated labeled dataset and base UMA checkpoint require single-task fine-tuning, resume, or acceptance evaluation; do not use for DeepMD training or MACE inference.
metadata:
  maturity: stable
  domain: mlip
  tools:
    - run_bash
  dependent_skills: []
  consumes:
    - dataset@1
    - model@1
  produces:
    - model@1
    - evaluation@1
  entrypoints:
    - scripts/prepare_uma_finetune_dataset.sh
    - scripts/submit_uma_finetuning.sh
---

# UMA fine-tuning on Genkai

Read [references/finetuning.md](references/finetuning.md) before preparing data,
training, resuming, or handing off a checkpoint. Reuse
`/home/pj24001724/ku40000345/wu/UMA-campare/.venv_uma`; keep data, reports,
LMDB, configurations, runs, and checkpoints in the caller's project.

## Role boundary

- Use this skill for UMA fine-tuning and fine-tuned-model evaluation.
- Route explicit DeepMD training to the `deepmd` skill.
- Route pretrained MACE inference or relaxation to the `mace` skill.
- Do not treat paper-derived adsorption candidates or mock labels as a usable
  surface-reaction training set.

## Required sequence

1. Fix one DFT label standard and one converter-supported UMA task.
2. Build physically grouped `data/train/`, `data/val/`, and untouched
   `data/test/` splits. For reactions, cover reactants, intermediates,
   products, path/transition images, distorted states, clean slabs, and
   gas-phase references.
3. Dry-run dataset preparation, then audit all present splits. Convert only
   train/val to ASE-LMDB.
4. Require zero audit errors, zero non-empty `*.failed`, successful LMDB
   readback, and a successfully composed trusted Hydra configuration.
5. Establish the original `uma-s-1p2` baseline on the fixed test set.
6. Dry-run the training launcher. Submit only after user approval.
7. Resume with the generated `resume.yaml`; evaluate `inference_ckpt.pt` with
   the same task used during fine-tuning.

## Scripts

| Script | Purpose |
|---|---|
| `prepare_uma_finetune_dataset.sh` | Audit splits, convert train/val, verify LMDB and Hydra |
| `submit_uma_finetuning.sh` | Compose launch config, dry-run, train, or resume |
| `validate_uma_finetune_data.py` | Label, overlap, duplicate, and leakage audit |
| `verify_uma_finetune_dataset.py` | Converter log, LMDB readback, and Hydra checks |
| `validate_uma_finetune_launch.py` | Non-training Hydra launch preflight |

## Dataset dry-run

```bash
UMA_FINETUNE_DRY_RUN=1 \
UMA_FINETUNE_WORK_DIR="$run_dir" \
UMA_FINETUNE_TASK=oc25 \
UMA_FINETUNE_REGRESSION_TASKS=ef \
UMA_FINETUNE_BASE_MODEL=uma-s-1p2 \
bash agents/Agent/skills/uma/scripts/prepare_uma_finetune_dataset.sh
```

The installed `fairchem-core 2.21.0` convenience converter accepts `omol`,
`odac`, `oc20`, `oc25`, `omat`, and `omc`, but not `oc22`. Never relabel PBE+U
oxide data as `oc25` to bypass that restriction.

## Training dry-run

```bash
UMA_FINETUNE_DRY_RUN=1 \
UMA_FINETUNE_WORK_DIR="$run_dir" \
UMA_FINETUNE_CONFIG="$run_dir/data/lmdb/uma_sm_finetune_template.yaml" \
UMA_FINETUNE_RUN_DIR="$run_dir/runs" \
UMA_FINETUNE_EPOCHS=1 \
UMA_FINETUNE_LR=1e-4 \
UMA_FINETUNE_BATCH_SIZE=1 \
UMA_FINETUNE_MAX_NEIGHBORS=300 \
bash agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh
```

Use `run_skill_script` only with `UMA_FINETUNE_DRY_RUN=1`. Never use it to
convert real data, train, resume, or evaluate a model.

## Handoff boundary

Preserve the audit and verification reports, generated YAML, dataset
checksums, DFT provenance, software versions, random seed, GPU information,
training log, best checkpoint, `resume.yaml`, and `inference_ckpt.pt`.
Training loss alone is not acceptance evidence; compare energy/force errors,
adsorption/reaction energetics, site ordering, relaxation, short MD, and
catastrophic-forgetting subsets against the original UMA.
