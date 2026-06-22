---
name: dft-calculation
description: Concept skill for Density Functional Theory (DFT) calculations. Describes what DFT is, when to use it, and which tool skills to invoke for DFT jobs. Use this to understand the DFT landscape before selecting a specific code (VASP or ABACUS).
metadata:
  dependent_skills:
    - vasp
    - abacus
  tags:
    - DFT
    - ab-initio
    - first-principles
    - labeling
    - electronic-structure
---

# DFT Calculation

Density Functional Theory (DFT) is an ab initio quantum-mechanical method that computes the electronic structure of materials from first principles. It is the standard approach for generating accurate reference energies, forces, and stresses used to label training data for machine learning force fields (MLFFs), as well as for validating candidate structures in materials design workflows.

## When to Use DFT

- **Labeling structures** for MLFF training or fine-tuning (PFD workflow).
- **Validating top candidates** from screening or generation workflows.
- **Computing ground-truth properties** (band gaps, formation energies, elastic constants) that require quantum accuracy.
- **Benchmarking** a force field against DFT reference values.

## Key Parameters

| Parameter | Typical Default | Notes |
|-----------|-----------------|-------|
| `kspacing` | 0.14 Å⁻¹ | Controls k-point density; smaller = more accurate but slower |
| Functional | PBE (GGA) | Use PBE+U or hybrid for correlated/magnetic systems |
| Pseudopotentials | PAW / ONCV | Code-dependent; verify compatibility with the element set |
| Energy cutoff | Code-dependent | Set per pseudopotential recommendation |

## Available Tool Skills

| Skill | Code | Best For |
|-------|------|---------|
| `abacus` | ABACUS | Open-source; preferred for Chinese HPC clusters and PFD workflows |
| `vasp` | VASP | Commercial; widely used; load `vasp` skill for VASP-specific instructions |

Load the appropriate tool skill (e.g., `load_skill("abacus")`) for step-by-step instructions on preparing inputs, submitting jobs, and collecting results.
