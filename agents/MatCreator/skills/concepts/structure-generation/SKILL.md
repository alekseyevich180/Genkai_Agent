---
name: structure-generation
description: Concept skill for crystal structure generation and atomic structure manipulation. Covers generative models for inverse design as well as manual structure building. Use this to understand the structure generation landscape before selecting a specific tool.
metadata:
  dependent_skills:
    - mattergen
    - atomic-structure
  tags:
    - structure-generation
    - inverse-design
    - crystal
    - mattergen
    - ASE
---

# Structure Generation

Structure generation refers to creating atomic structures — either from scratch (generative models) or by building/modifying them manually. It is the entry point for materials design workflows, providing candidate structures for subsequent relaxation, property prediction, and DFT validation.

## Approaches

| Approach | Description | When to Use |
|----------|-------------|------------|
| **Generative model (MatterGen)** | Diffusion-based model that generates novel crystal structures conditioned on desired properties | Inverse design, discovery of new phases |
| **Manual construction (ASE)** | Build structures from scratch, cut surfaces, create supercells, add defects | Specific geometries, controlled modifications |
| **Database retrieval** | Pull known structures from Materials Project or AFLOW | Starting point, reference structures |

## MatterGen Workflow

1. **Generate** — sample candidate structures from the model checkpoint.
2. **Evaluate** — assess structural validity (S.U.N. criteria: Stable, Unique, Novel).
3. **Fine-tune** — adapt the model to bias generation toward target properties (optional).

## When to Use

- **Materials design**: generate a batch of candidates for downstream screening.
- **PFD / active learning**: build initial structures and supercells as starting configurations.
- **Defect or surface studies**: manually construct specific geometries with ASE.

## Available Tool Skills

| Skill | Purpose |
|-------|---------|
| `mattergen-generation` | Generate crystal structures with the MatterGen diffusion model |
| `mattergen-finetune` | Fine-tune MatterGen on property-conditioned data |
| `mattergen-evaluation` | Evaluate generated structures for S.U.N. criteria |
| `atomic-structure` | Build, inspect, and modify atomic structures using ASE |

Load the appropriate tool skill for detailed instructions (e.g., `load_skill("mattergen-generation")`).
