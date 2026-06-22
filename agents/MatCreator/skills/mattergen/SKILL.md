---
name: mattergen
description: MatterGen is a diffusion-based generative model for inorganic crystal structure generation. Use this skill to understand what MatterGen can do and which sub-skill to load. For generation, fine-tuning, or evaluation tasks, load the appropriate sub-skill.
metadata:
  dependent_skills:
    - mattergen-generation
    - mattergen-finetune
    - mattergen-evaluation
  tags:
    - MatterGen
    - crystal-generation
    - inverse-design
    - generative-model
---

# MatterGen

MatterGen is a diffusion-based generative model for inorganic crystal structure generation. It can generate novel crystal structures either unconditionally or conditioned on target properties (chemical system, space group, band gap, bulk modulus, magnetic density, etc.).

## Capabilities

| Sub-skill | Purpose |
|-----------|---------|
| `mattergen-generation` | Generate crystal structures from a pre-trained or fine-tuned checkpoint |
| `mattergen-finetune` | Fine-tune a MatterGen checkpoint on property-labeled structures (CSV + CIF) |
| `mattergen-evaluation` | Evaluate generated structures against S.U.N. criteria (Stable, Unique, Novel) |

## When to Use

- **Discovery**: generate a batch of novel candidates for a target chemical system or property range.
- **Conditioned design**: constrain generation by space group, band gap, bulk modulus, etc.
- **Active loop**: fine-tune the model on CGCNN-predicted properties, then generate again.
- **Screening**: evaluate generated structures before passing to DFT validation.

## Typical Workflow

1. `load_skill("mattergen-generation")` — generate structures.
2. `load_skill("mattergen-evaluation")` — filter by S.U.N. criteria.
3. *(Optional)* `load_skill("mattergen-finetune")` — fine-tune on top candidates, then repeat.
