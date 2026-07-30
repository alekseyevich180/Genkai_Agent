---
name: guide-for-model-training
description: General guideline for MLFF model training. Describes the decision flow for choosing between pre-trained model validation, fine-tuning on available data, and launching a full PFD workflow.
metadata:
  dependent_skills:
    - machine-learning-force-field
    - dft-calculation
    - mace
    - deepmd
    - uma
    - abacus
  tags:
    - model
    - fine-tune
    - machine-learning-force-field
---

Model training is a dynamic, iterative process. Follow this decision flow and revisit earlier steps if results are unsatisfactory.

## Decision Flow

### Stage 1 — Check the Pre-trained Model
- Always try the pre-trained model first.
- Use the `mace` skill for the project's pretrained-potential energy, force,
  and relaxation baseline unless the user explicitly selects another model.
- Query the available domain datasets. If not sure, ALWAYS ask user.
- Query the selected domain datasets for the target system. If it is available, validate the pre-trained model for it.
- If validation passes, stop here — no training is needed.

### Stage 2 — Fine-tune UMA on Available Data
- If dataset available and pre-trained model does not perform adequately, fine-tune it using the existing dataset.
- Use the `uma` skill for surface/adsorption fine-tuning, ASE-LMDB preparation,
  resume, and fine-tuned-model evaluation.
- Prefer this over more complex workflows whenever data is available.
- Evaluate the fine-tuned model; if results are sufficient, stop here.

### Stage 3 — Train DeepMD / PFD Workflow
- If no available dataset or fine-tuned model is insufficient, launch the PFD workflow.
- Use the `deepmd` skill for explicit DeepMD data preparation, training,
  restart, freezing, compression, and testing.
- PFD iteratively generates new data via MD exploration, labels it, and retrains until convergence.
- See `pfd-finetuning` guide for full details.

## General Notes
- Always evaluate the model after each step before proceeding to the next.
- Prefer the simplest effective strategy — avoid PFD if fine-tuning suffices.
- Each step may require multiple rounds of interaction and parameter adjustment.
