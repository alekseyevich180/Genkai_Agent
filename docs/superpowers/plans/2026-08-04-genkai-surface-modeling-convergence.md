# Genkai Surface-Modeling Structure Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every surface-modeling production algorithm into `src/genkai/modeling/surface/` and leave only thin Skill wrappers at the documented script paths.

**Architecture:** Genkai owns vacancy, adsorbate, slab, cluster, and cluster-search implementations. Skill files remain external decision/CLI entries and re-export only the moved public functions required by existing callers. Internal imports become package-relative, and the canonical task schema points to Genkai module entrypoints.

**Tech Stack:** Python 3.12, ASE, NumPy, pandas, SciPy, Optuna, Torch, pymatgen, mp-api, optional FAIRChem; pytest, AST inspection, setuptools/wheel.

## Global Constraints

- Work only in `/home/pj24001724/ku40000345/wu/Genkai_Agent/Genkai_Evolution` on `feat/genkai-evolution`.
- Preserve existing function names, CLI flags, output formats, mock-calculator behavior, and scientific thresholds.
- No production algorithm or heavy scientific import may remain in `agents/Agent/skills/surface-modeling/scripts/`.
- `src/genkai/` must not import `agents.Agent.skills`, `paperread`, or Skill-private files.
- Preserve lazy optional runtime behavior; imports and `--help` must not call network services or instantiate calculators.
- Do not run online LLM, Materials Project retrieval, VASP, GPU/CUDA, PJM, training, relaxation, or MD.
- Write a failing test before each production move and commit each independently verifiable task.

---

### Task 1: Establish the New Library Imports and Wrapper Boundary

**Files:**

- Create: `src/genkai/modeling/surface/__init__.py`
- Create: `tests/modeling/test_surface_algorithm_ownership.py`
- Modify: `tests/architecture/test_import_boundaries.py`
- Modify: `tests/packaging/test_wheel_contents.py`

**Interfaces:**

- Produces importable modules `genkai.modeling.surface.vacancy`, `adsorbate`,
  `materials_project_slab`, `cluster_search`, and
  `genkai.modeling.surface.metal_cluster.{bcc,fcc,hcp,cluster_builder,surface_cluster_builder}`.
- Enforces that Skill wrappers contain no imports from `ase`, `numpy`, `pandas`,
  `scipy`, `optuna`, `torch`, `fairchem`, `pymatgen`, or `mp_api`.

- [ ] **Step 1: Write the failing library and wrapper tests**

Create `tests/modeling/test_surface_algorithm_ownership.py`:

```python
import importlib


def test_surface_algorithm_modules_have_library_owners() -> None:
    modules = (
        "genkai.modeling.surface.vacancy",
        "genkai.modeling.surface.adsorbate",
        "genkai.modeling.surface.materials_project_slab",
        "genkai.modeling.surface.cluster_search",
        "genkai.modeling.surface.metal_cluster.bcc",
        "genkai.modeling.surface.metal_cluster.fcc",
        "genkai.modeling.surface.metal_cluster.hcp",
        "genkai.modeling.surface.metal_cluster.cluster_builder",
        "genkai.modeling.surface.metal_cluster.surface_cluster_builder",
    )
    for name in modules:
        module = importlib.import_module(name)
        assert module.__file__.startswith(str(__file__).split("/tests/")[0])


def test_deterministic_surface_helpers_are_available() -> None:
    from genkai.modeling.surface.adsorbate import maximum_non_overlapping_site_groups
    from genkai.modeling.surface.materials_project_slab import parse_miller_index
    from genkai.modeling.surface.vacancy import parse_vacancy_counts

    assert parse_vacancy_counts("1,2", oxygen_count=5) == [1, 2]
    assert maximum_non_overlapping_site_groups([(0, 1), (1, 2), (2, 3)]) == 2
    assert parse_miller_index("0,0,0,1") == (0, 0, 1)
```

Extend `tests/architecture/test_import_boundaries.py` with an AST scan over
`agents/Agent/skills/surface-modeling/scripts`. For every Python import, reject
the heavy module roots listed above unless the file is under `tests/` (there is
no exception for production wrappers). Add an assertion that every non-empty
script contains `genkai.modeling.surface`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/modeling/test_surface_algorithm_ownership.py \
  tests/architecture -q --tb=short
```

Expected: collection fails because the new library modules do not exist, and
the wrapper scan reports the existing heavy imports.

- [ ] **Step 3: Add the package namespace only**

Create `src/genkai/modeling/surface/__init__.py` and
`src/genkai/modeling/surface/metal_cluster/__init__.py` with explicit public
task names but no optional-runtime imports:

```python
"""Stable surface-modeling algorithm ownership."""

__all__ = [
    "adsorbate",
    "cluster_search",
    "materials_project_slab",
    "vacancy",
]
```

- [ ] **Step 4: Re-run the ownership tests and confirm the expected module failure**

Run the Step 2 command. It must now collect the package but fail only because
the concrete algorithm modules have not moved yet.

- [ ] **Step 5: Commit the red boundary checkpoint**

```bash
git add src/genkai/modeling/surface tests/modeling tests/architecture/test_import_boundaries.py
git commit -m "test: define surface modeling ownership boundary"
```

### Task 2: Move Vacancy and Adsorbate Algorithms

**Files:**

- Move: `agents/Agent/skills/surface-modeling/scripts/vacancy/vacancy_landscape.py` -> `src/genkai/modeling/surface/vacancy.py`
- Move: `agents/Agent/skills/surface-modeling/scripts/adsorbate/adsorbate_landscape.py` -> `src/genkai/modeling/surface/adsorbate.py`
- Create: thin wrappers at the two original paths
- Modify: `tests/test_paperread_surface.py`

**Interfaces:**

- Preserves all public helpers and `main()` in the moved modules.
- Preserves the original two Skill commands through wrappers.

- [ ] **Step 1: Move the two implementations without changing logic**

Move the files, then update only the module-level ownership and imports needed
for package loading. Do not alter sampling, geometry, calculator, output, or
plotting code.

- [ ] **Step 2: Replace the old files with thin wrappers**

Use this exact pattern for `vacancy_landscape.py` and
`adsorbate_landscape.py`:

```python
from genkai.modeling.surface.vacancy import *
from genkai.modeling.surface.vacancy import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
```

Use the corresponding module name for the adsorbate wrapper. Keep explicit
private helper imports only where current tests require them.

- [ ] **Step 3: Run library, wrapper, and deterministic tests**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/modeling/test_surface_algorithm_ownership.py \
  tests/test_paperread_surface.py -q --tb=short
```

Expected: all existing adsorbate/vacancy characterization assertions pass and
the wrapper source scan reports no heavy imports.

- [ ] **Step 4: Commit the two algorithm moves**

```bash
git add src/genkai/modeling/surface agents/Agent/skills/surface-modeling/scripts \
  tests/test_paperread_surface.py
git commit -m "refactor: move vacancy and adsorbate modeling into genkai"
```

### Task 3: Move Slab and Metal-Cluster Algorithms

**Files:**

- Move: `scripts/surface/materials_project_slab.py` -> `src/genkai/modeling/surface/materials_project_slab.py`
- Move: `scripts/metal_cluster/{bcc,fcc,hcp,cluster_builder,surface_cluster_builder}.py` -> `src/genkai/modeling/surface/metal_cluster/`
- Modify: moved `surface_cluster_builder.py` imports to package-relative imports
- Create: thin wrappers at all original surface and metal-cluster paths
- Modify: `tests/test_surface_mp_workflow.py`

**Interfaces:**

- Preserves `resolve_stable_facet`, `validate_surface_slab`,
  `download_stable_surface`, cluster builders, and CLI flags.
- Internal imports resolve through `genkai.modeling.surface.metal_cluster` and
  `genkai.modeling.surface.materials_project_slab`; no `sys.path` mutation or
  `surface.*` fallback remains.

- [ ] **Step 1: Add a failing package-relative import test**

Add to `tests/modeling/test_surface_algorithm_ownership.py`:

```python
def test_surface_cluster_builder_uses_library_slab_and_cluster_modules() -> None:
    from genkai.modeling.surface.metal_cluster import surface_cluster_builder

    assert surface_cluster_builder.place_cluster_on_surface
    assert surface_cluster_builder.get_geometric_center
```

Run the ownership test; it fails until the moved package is present.

- [ ] **Step 2: Move implementations and repair only import paths**

Move the files. In `surface_cluster_builder.py`, replace both fallback import
branches with:

```python
from ..materials_project_slab import (
    download_stable_surface,
)
from .bcc import build_bcc110_bridge_cluster
from .cluster_builder import (
    build_nanocluster,
    resolve_cluster_element,
)
from .fcc import build_fcc111_cluster, resolve_fcc_rows
from .hcp import build_hcp0001_cluster, parse_row_sequence as parse_hcp_rows
```

In `hcp.py`, use the same package-relative cluster-builder import:

```python
from .cluster_builder import resolve_cluster_element, resolve_lattice_constants
```
Remove all `sys.path.insert` and direct `surface.*` fallbacks from moved code.

- [ ] **Step 3: Add wrappers and run geometry/slab tests**

Wrappers re-export the moved public functions and call `main` under the normal
guard. For `materials_project_slab.py`, explicitly re-export the private
`_select_bulk_document` helper used by the existing characterization test.

Run:

```bash
../.venv/bin/python -m pytest \
  tests/modeling/test_surface_algorithm_ownership.py \
  tests/test_surface_mp_workflow.py -q --tb=short
```

Expected: deterministic slab and cluster geometry tests pass without an API key
or network access.

- [ ] **Step 4: Commit slab and cluster ownership**

```bash
git add src/genkai/modeling/surface agents/Agent/skills/surface-modeling/scripts \
  tests/test_surface_mp_workflow.py
git commit -m "refactor: move slab and cluster modeling into genkai"
```

### Task 4: Move Optional Cluster Search and Update the Canonical Schema

**Files:**

- Move: `scripts/cluster_search/ads_nanocluster.py` -> `src/genkai/modeling/surface/cluster_search.py`
- Create: thin wrapper at `scripts/cluster_search/ads_nanocluster.py`
- Modify: `src/genkai/modeling/schema/task_parameter_schema.json`
- Modify: `agents/Agent/skills/surface-modeling/SKILL.md`
- Modify: `agents/Agent/skills/ptomodel/SKILL.md`
- Modify: `tests/modeling/test_ptomodel_resources.py`
- Modify: `tests/packaging/test_wheel_contents.py`

**Interfaces:**

- Preserves `ads_nanocluster.py` CLI and helper functions while keeping
  FAIRChem/Torch imports lazy inside calculator construction.
- Schema `script` fields become module identifiers:
  `genkai.modeling.surface.vacancy:main`,
  `genkai.modeling.surface.adsorbate:main`,
  `genkai.modeling.surface.metal_cluster.surface_cluster_builder:main`, and
  `genkai.modeling.surface.cluster_search:main`.

- [ ] **Step 1: Add the schema and wheel assertions before moving search**

Extend the resource test:

```python
def test_schema_points_to_genkai_surface_modules() -> None:
    from genkai.modeling.ptomodel import _load_surface_modeling_parameter_schema

    scripts = {
        task["script"]
        for task in _load_surface_modeling_parameter_schema()["tasks"].values()
    }
    assert all(value.startswith("genkai.modeling.surface.") for value in scripts)
```

Add the same assertion to the extracted-wheel subprocess check.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
../.venv/bin/python -m pytest tests/modeling/test_ptomodel_resources.py -q --tb=short
```

Expected: fail because the schema still contains Skill script paths.

- [ ] **Step 3: Move search code, create wrapper, and update schema**

Move the search implementation unchanged except for package ownership. The
wrapper follows the established import-and-main pattern. Replace only the four
schema `script` values with the four Genkai module identifiers listed above.

- [ ] **Step 4: Run optional-runtime import and wrapper help checks**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/modeling/test_ptomodel_resources.py \
  tests/modeling/test_surface_algorithm_ownership.py \
  tests/skills/test_ptomodel_entrypoint.py \
  tests/packaging/test_wheel_contents.py -q --tb=short
```

Also run `--help` through all five wrapper paths. No model, calculator, API key,
or network request may be started.

- [ ] **Step 5: Commit optional search and schema ownership**

```bash
git add src/genkai/modeling/surface src/genkai/modeling/schema \
  agents/Agent/skills/surface-modeling/scripts \
  agents/Agent/skills/surface-modeling/SKILL.md \
  agents/Agent/skills/ptomodel/SKILL.md tests/modeling tests/packaging
git commit -m "refactor: move surface modeling algorithms into genkai"
```

### Task 5: Close Task 12 Documentation and Verification Gates

**Files:**

- Modify: `tests/architecture/test_import_boundaries.py`
- Modify: `README.md`
- Modify: `GENKAI_EVOLUTION_PLAN.md`
- Modify: `docs/structure-baseline.md`
- Modify: `work_logs/2026-08-04.md`
- Modify: `work_log.md`

- [ ] **Step 1: Tighten architecture and wrapper ownership assertions**

Assert the Genkai-to-Skill import set is empty, all wrapper files are thin, and
all canonical modules are present. Keep historical baseline references clearly
labeled as historical; current status must say Task 12 complete.

- [ ] **Step 2: Run the complete related regression**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/architecture tests/modeling \
  tests/integrations/test_surface_facades.py \
  tests/workflow/test_surface_paper.py \
  tests/workflow/test_paper_to_mlip.py \
  tests/skills/test_ptomodel_entrypoint.py \
  tests/packaging/test_wheel_contents.py \
  tests/test_paperread_surface.py tests/test_surface_mp_workflow.py -q --tb=short
```

Run repository collection separately and record the existing
`agent.tools.structure_builder` error without claiming full-suite success.

- [ ] **Step 3: Update the dated log and index**

Record moved modules, wrapper count, exact test results, commits, and explicit
non-executed scientific/runtime checks in `work_logs/2026-08-04.md`.

- [ ] **Step 4: Final scan and commit**

```bash
rg -n "from (ase|numpy|pandas|scipy|optuna|torch|fairchem|pymatgen|mp_api)" \
  agents/Agent/skills/surface-modeling/scripts
rg -n "paperread|agents\.Agent\.skills" src/genkai/modeling
git diff --check
git status --short --branch
git add README.md GENKAI_EVOLUTION_PLAN.md docs/structure-baseline.md \
  work_log.md work_logs/2026-08-04.md tests/architecture
git commit -m "docs: complete task12 surface modeling convergence"
```
