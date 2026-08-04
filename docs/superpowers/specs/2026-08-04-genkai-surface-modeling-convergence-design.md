# Genkai Surface-Modeling Structure Convergence Design

**Date:** 2026-08-04

**Status:** Approved for Task 12 completion

## 1. Objective

Complete the remaining Task 12 migration by moving the production surface-modeling
algorithms from `agents/Agent/skills/surface-modeling/scripts/` into
`src/genkai/modeling/surface/`. Keep the existing Skill script paths as thin
argument/entry wrappers so documented commands and external callers continue to
work, while no domain implementation remains in the Skill directory.

This scope includes vacancy landscapes, adsorbate landscapes, Materials Project
slab construction, metal-cluster construction, surface-cluster placement, and
the optional UMA/FAIRChem cluster-search workflow. It does not execute any of
those calculators or contact Materials Project; tests use deterministic
geometry, mock calculators, `--help`, and offline validation only.

## 2. Approaches Considered

1. **Library implementation with thin Skill wrappers (selected).** Move each
   production module into a named Genkai package, fix internal imports to be
   package-relative, and leave one small wrapper at every documented Skill path.
   This gives one source of truth while preserving user-facing command paths.
2. **Delete all Skill scripts and expose only Python modules.** This produces a
   cleaner tree but breaks documented commands and existing external entrypoints
   in the current migration worktree.
3. **Keep scripts and add facades.** This preserves short-term compatibility but
   leaves duplicate ownership and fails the physical convergence requirement.

## 3. Target Package and Ownership

```text
src/genkai/modeling/surface/
├── __init__.py
├── vacancy.py
├── adsorbate.py
├── materials_project_slab.py
├── cluster_search.py
└── metal_cluster/
    ├── __init__.py
    ├── bcc.py
    ├── fcc.py
    ├── hcp.py
    ├── cluster_builder.py
    └── surface_cluster_builder.py
```

The current Skill paths remain, but contain only imports and `__main__` calls:

```text
agents/Agent/skills/surface-modeling/scripts/
├── vacancy/vacancy_landscape.py       -> genkai.modeling.surface.vacancy
├── adsorbate/adsorbate_landscape.py   -> genkai.modeling.surface.adsorbate
├── surface/materials_project_slab.py  -> genkai.modeling.surface.materials_project_slab
├── cluster_search/ads_nanocluster.py  -> genkai.modeling.surface.cluster_search
└── metal_cluster/*.py                 -> genkai.modeling.surface.metal_cluster.*
```

The wrappers may re-export public functions needed by existing characterization
tests, but may not import ASE, NumPy, pandas, SciPy, Optuna, Torch, FAIRChem,
pymatgen, or `mp_api` directly. The architecture gate scans for this rule.

## 4. Public Interfaces and Internal Imports

The moved modules preserve their existing public functions and CLI parsers.
The package-level API exposes the main task runners:

```python
from genkai.modeling.surface.adsorbate import main as adsorbate_main
from genkai.modeling.surface.cluster_search import main as cluster_search_main
from genkai.modeling.surface.materials_project_slab import main as slab_main
from genkai.modeling.surface.vacancy import main as vacancy_main
from genkai.modeling.surface.metal_cluster.surface_cluster_builder import (
    main as surface_cluster_main,
)
```

`surface_cluster_builder.py` uses relative imports for the moved metal-cluster
and slab modules. `hcp.py` and `surface_cluster_builder.py` lose their current
`sys.path` fallback branches; package execution is the only production import
route. The scripts' argument names, output file formats, mock-calculator paths,
and scientific validation thresholds are unchanged.

The canonical task schema remains owned by
`src/genkai/modeling/schema/task_parameter_schema.json`; each task's `script`
field becomes its Genkai module entry identifier (for example,
`genkai.modeling.surface.adsorbate:main`). Skill documentation continues to
show the wrapper command path for interactive use.

## 5. Error and Runtime Boundaries

- Importing the library must not instantiate a calculator, call a network API,
  load a checkpoint, or require an API key.
- `build_calculator` functions remain lazy and retain their existing explicit
  errors for missing optional runtime dependencies or model paths.
- Materials Project access remains inside the slab execution function and is
  never triggered by `--help`, package import, or offline tests.
- Mock calculators and `calculator=none` remain clearly offline evidence; no
  result is relabeled as DFT/MLIP scientific evidence.
- All output directories remain caller-selected; wrappers do not add implicit
  `cd` behavior.
- The library must not import `agents.Agent.skills` or read Skill-private files.

## 6. Testing Strategy

Tests are written before moving production files:

1. New library imports resolve all five task families and their public helper
   functions; deterministic unit assertions cover vacancy parsing, adsorbate
   site grouping, cluster geometry, and stable-facet selection.
2. Existing Skill-path characterization tests continue to run through wrappers,
   including `--help`, mock geometry, and Materials Project slab validation.
3. An AST/source gate rejects heavy scientific imports in wrappers and rejects
   any Genkai-to-Skill import.
4. A subprocess test runs each wrapper's `--help`; no calculator, API key, or
   external network is required.
5. Wheel tests import each canonical module from the extracted wheel and verify
   the task schema points to Genkai module identifiers.

Completion evidence is limited to offline algorithm behavior, wrapper behavior,
architecture ownership, and packaging. It does not claim real UMA/FAIRChem
relaxation, Materials Project retrieval, VASP, GPU/CUDA, PJM, training, or MD.

## 7. Completion Criteria

Task 12 is complete when:

1. all surface-modeling production algorithms exist under
   `src/genkai/modeling/surface/`;
2. Skill script paths are thin wrappers with no heavy/domain implementation;
3. internal imports are package-relative and no Genkai module imports Skill code;
4. the canonical schema references Genkai module entrypoints;
5. offline library, wrapper, architecture, packaging, and related regression
   tests pass;
6. the formal plan and dated work log state Task 12 complete and preserve the
   known repository-wide `agent.tools.structure_builder` collection boundary.
