---
name: machine-learning-force-field
description: Concept skill for Machine Learning Force Fields (MLFFs). Describes what MLFFs are, the distinction between training and inference, and which tool skills to use. Load this before selecting a specific MLFF framework (DeePMD, MatterSim, etc.).
metadata:
  dependent_skills:
    - deepmd
    - mattersim
    - ase-deepmd
  tags:
    - MLFF
    - machine-learning-potential
    - deep-potential
    - force-field
    - training
---

# Machine Learning Force Field (MLFF)

A Machine Learning Force Field (MLFF) is a surrogate model trained on DFT reference data that predicts atomic energies and forces at a fraction of the computational cost. MLFFs enable large-scale and long-timescale molecular dynamics simulations that would be prohibitively expensive with DFT directly.

## Workflow Phases

| Phase | Description |
|-------|-------------|
| **Pre-trained model** | A general-purpose model trained on large, diverse datasets. Try this first. |
| **Fine-tuning** | Adapts a pre-trained model to a target system using domain-specific DFT data. |
| **Training from scratch** | Used in distillation: train a lightweight student model on teacher-labeled data. |
| **Inference / MD** | Deploy the trained model for structure relaxation or molecular dynamics. |

## When to Use

- Run MD exploration to sample the configuration space of a new material.
- Relax generated structures before DFT validation.
- Screen large candidate sets efficiently before expensive DFT runs.
- Replace DFT in high-throughput workflows after validating accuracy.

## Available Tool Skills

| Skill | Framework | Best For |
|-------|-----------|---------|
| `deepmd` | DeePMD-kit | Training and fine-tuning DPA-1/DPA-2 models; PFD workflow |
| `mattersim` | MatterSim | Pre-trained universal MLFF; structure relaxation and MD |
| `ase-deepmd` | ASE + DeePMD | Running MD with a trained DeePMD model via ASE interface |

Load the appropriate tool skill for detailed instructions (e.g., `load_skill("deepmd")`).

## Choosing a Framework

- Use `deepmd` when you need to **train or fine-tune** a model on your own DFT dataset.
- Use `mattersim` when you want a **pre-trained universal model** without retraining.
- Use `ase-deepmd` when you need to run **MD simulations** with a trained DeePMD potential.
