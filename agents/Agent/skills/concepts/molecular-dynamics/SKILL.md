---
name: molecular-dynamics
description: Concept skill for Molecular Dynamics (MD) simulation. Describes MD ensembles, key parameters, and which tool skills to invoke for MD runs. Use this to understand MD concepts before selecting a specific simulation tool.
metadata:
  dependent_skills:
    - ase-deepmd
    - mattersim
  tags:
    - MD
    - molecular-dynamics
    - NVT
    - NPT
    - simulation
    - exploration
---

# Molecular Dynamics (MD) Simulation

Molecular Dynamics simulates the time evolution of a system of atoms by numerically integrating Newton's equations of motion under a given interatomic potential (force field). In the MLFF/PFD context, MD is primarily used for **configuration space exploration** — generating diverse, physically relevant structures for labeling and training.

## Ensembles

| Ensemble | Fixed Variables | Use Case |
|----------|----------------|---------|
| NVT | N, V, T | Fixed-volume exploration; most common for PFD |
| NPT | N, P, T | Variable-cell exploration; use when volume relaxation matters |
| NVE | N, V, E | Microcanonical; rarely used for exploration |

## Key Parameters

| Parameter | Default (PFD) | Description |
|-----------|---------------|-------------|
| Temperature | 300 K | Higher T increases structural diversity |
| Timestep | 2 fs | Standard for most solids and liquids |
| Total steps | 500 (≈1 ps) | Minimum for initial exploration |
| Save interval | 50 steps | Frames saved for entropy-based curation |
| Pressure | 0 GPa | NPT only |

## When to Use MD in a Workflow

- **PFD fine-tuning / distillation**: Step 2 — run MD with the current MLFF to generate candidate structures.
- **Materials validation**: Run short MD to check structural stability at target temperature.
- **Property sampling**: Generate an ensemble of configurations for property averaging.

## Available Tool Skills

| Skill | Best For |
|-------|---------|
| `ase-deepmd` | MD with a trained DeePMD potential via ASE |
| `mattersim` | MD with the pre-trained MatterSim universal potential |

Load the appropriate tool skill for step-by-step instructions (e.g., `load_skill("ase-deepmd")`).
