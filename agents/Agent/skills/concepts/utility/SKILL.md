---
name: utility
description: "Concept skill covering general-purpose utility capabilities: visualization/plotting, structure format conversion, database queries, and web search. Use this to identify which utility tool skill to load for a given support task."
metadata:
  dependent_skills:
    - plot
    - structure-conversion
    - database
    - materials-project
  tags:
    - utility
    - visualization
    - conversion
    - database
    - search
---

# Utility Skills

Utility skills provide supporting capabilities that complement simulation and training workflows. They handle tasks such as producing publication-quality plots, converting structure file formats, querying materials databases, and retrieving information from the web.

## Skill Overview

| Skill | Purpose | When to Use |
|-------|---------|------------|
| `plot` | Matplotlib-based plotting | Visualize training curves, energy-force scatter plots, property distributions |
| `structure-conversion` | Convert between structure formats (CIF, POSCAR, XYZ, etc.) | Before/after DFT or MD runs that require a specific file format |
| `database` | Query internal project database | Retrieve previously computed structures, trajectories, or metadata |
| `materials-project` | Query the Materials Project REST API | Fetch reference structures, computed properties, stability data |

## Common Use Cases

- **After training**: plot learning curves and error metrics with `plot`.
- **Before DFT**: convert ASE/CIF structures to POSCAR/ABACUS format with `structure-conversion`.
- **Candidate generation**: pull reference structures from Materials Project with `materials-project`.
- **Data bookkeeping**: store and retrieve session data with `database`.

Load the relevant skill for step-by-step instructions (e.g., `load_skill("plot")`).
