# Genkai PToModel Structure Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the stable PToModel mapping, modeling checklist, and task schema into `src/genkai/modeling/`, remove their legacy owners, and eliminate the final `src/genkai -> paperread` reverse imports.

**Architecture:** Pure PToModel rules live in `genkai.modeling.mapping`; `genkai.modeling.ptomodel` remains the stable public API and artifact-aware facade. Checklist logic and the canonical surface-task schema become library-owned, while the PToModel Skill retains only argument handling and delegation.

**Tech Stack:** Python 3.12, importlib.resources, argparse, JSON/JSONL/CSV, Pydantic v2 artifacts, pytest, setuptools/wheel.

## Global Constraints

- Work only in `/home/pj24001724/ku40000345/wu/Genkai_Agent/Genkai_Evolution` on `feat/genkai-evolution`.
- Preserve PToModel mapping rules, task selection, CLI arguments, JSON keys, and `schema_version=1.0`.
- Do not retain duplicate production implementations or compatibility shims under `paperread.surface.modeling`.
- `src/genkai/` must not import `paperread` or `agents.Agent.skills`; the Task 12 allowlist ends empty.
- Keep the PToModel Skill as an on-demand thin entry; do not move external runtime launchers into the library in this slice.
- Do not run online LLM extraction, VASP, GPU/CUDA, PJM, relaxation, training, or MD.
- Use a failing test before each production behavior change and commit each independently verifiable task.

---

### Task 1: Move the Pure Mapping and Canonical Schema into Genkai

**Files:**

- Create: `src/genkai/modeling/mapping.py`
- Create: `src/genkai/modeling/schema/__init__.py`
- Create: `src/genkai/modeling/schema/task_parameter_schema.json`
- Modify: `src/genkai/modeling/ptomodel.py`
- Modify: `src/genkai/modeling/__init__.py`
- Modify: `tests/test_paperread_surface.py`
- Create: `tests/modeling/__init__.py`
- Create: `tests/modeling/test_ptomodel_resources.py`
- Delete: `paperread/surface/modeling/ptomodel.py`
- Delete: `agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json`

**Interfaces:**

- Consumes: public surface vocabulary and ontology functions from `genkai.literature.surface.core`.
- Produces: `build_ptomodel_payload(...) -> dict[str, Any]`, `generate_ptomodel_output(...) -> dict[str, str]`, and `main(argv: list[str] | None = None) -> int` through `genkai.modeling.ptomodel`.
- Produces: `_load_surface_modeling_parameter_schema() -> dict[str, Any]` using the packaged canonical JSON resource.

- [ ] **Step 1: Write target-import and package-resource tests**

Update PToModel imports in `tests/test_paperread_surface.py` to:

```python
from genkai.modeling.ptomodel import (
    build_ptomodel_payload,
    generate_ptomodel_output,
)
```

Create `tests/modeling/test_ptomodel_resources.py`:

```python
from importlib.resources import files

from genkai.modeling.ptomodel import _load_surface_modeling_parameter_schema


def test_canonical_task_schema_is_owned_by_genkai() -> None:
    resource = files("genkai.modeling.schema").joinpath(
        "task_parameter_schema.json"
    )
    assert resource.is_file()
    registry = _load_surface_modeling_parameter_schema()
    assert registry["schema_version"] == "1.0"
    assert set(registry["tasks"]) == {
        "vacancy_landscape",
        "adsorbate_landscape",
        "surface_cluster_builder",
        "surface_cluster_mlip_search",
    }
    assert registry["schema_resource"] == (
        "genkai.modeling.schema:task_parameter_schema.json"
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/modeling/test_ptomodel_resources.py \
  tests/test_paperread_surface.py -q --tb=short
```

Expected: collection fails because the public module does not yet export the
mapping API and the Genkai-owned schema resource does not exist.

- [ ] **Step 3: Move the implementation and schema without duplication**

Move the legacy PToModel implementation to
`src/genkai/modeling/mapping.py`. Move the schema JSON to
`src/genkai/modeling/schema/task_parameter_schema.json` and add an empty
`schema/__init__.py`.

Replace repository-relative schema lookup in `mapping.py` with:

```python
from importlib.resources import files


TASK_SCHEMA_PACKAGE = "genkai.modeling.schema"
TASK_SCHEMA_NAME = "task_parameter_schema.json"


def _load_surface_modeling_parameter_schema() -> dict[str, Any]:
    resource = files(TASK_SCHEMA_PACKAGE).joinpath(TASK_SCHEMA_NAME)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    tasks = payload.get("tasks")
    if payload.get("schema_version") != "1.0" or not isinstance(tasks, dict) or not tasks:
        raise ValueError("invalid canonical surface-modeling task schema")
    return {
        "schema_version": payload["schema_version"],
        "schema_path": f"{TASK_SCHEMA_PACKAGE}:{TASK_SCHEMA_NAME}",
        "schema_resource": f"{TASK_SCHEMA_PACKAGE}:{TASK_SCHEMA_NAME}",
        "tasks": tasks,
    }
```

In `genkai.modeling.ptomodel`, import and re-export the pure mapping functions:

```python
from genkai.modeling.mapping import (
    _load_surface_modeling_parameter_schema,
    build_ptomodel_payload,
    generate_ptomodel_output,
    main,
)
```

Update `build_modeling_plan` to use the local public API and set
`producer="genkai.modeling.ptomodel"`. Add a normal `if __name__ == "__main__"`
guard in the public module so the existing catalog check
`python -m genkai.modeling.ptomodel --help` continues to exercise the CLI.

- [ ] **Step 4: Run focused mapping tests and verify GREEN**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/modeling/test_ptomodel_resources.py \
  tests/test_paperread_surface.py \
  tests/integrations/test_surface_facades.py -q --tb=short
```

Expected: PASS with the existing hand-checked task mapping and artifact
assertions unchanged except for the canonical schema resource identifier.

- [ ] **Step 5: Commit the mapping ownership change**

```bash
git add src/genkai/modeling tests/modeling tests/test_paperread_surface.py \
  tests/integrations/test_surface_facades.py \
  paperread/surface/modeling/ptomodel.py \
  agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json
git commit -m "refactor: move ptomodel mapping into genkai"
```

### Task 2: Move Checklist Ownership and Thin the PToModel Skill Entry

**Files:**

- Create: `src/genkai/modeling/checklist.py`
- Modify: `src/genkai/modeling/ptomodel.py`
- Modify: `agents/Agent/skills/ptomodel/scripts/ptomodel_tools.py`
- Modify: `tests/test_surface_mp_workflow.py`
- Create: `tests/skills/test_ptomodel_entrypoint.py`
- Delete: `paperread/surface/modeling/job_bundle.py`
- Delete: `paperread/surface/modeling/__init__.py`

**Interfaces:**

- Consumes: PToModel plan dictionaries and generated literature output paths.
- Produces: `build_modeling_checklist(plan: dict[str, Any]) -> dict[str, Any]` and `write_compact_job_bundle(...) -> dict[str, str]` from `genkai.modeling.checklist`.
- Preserves: `python agents/Agent/skills/ptomodel/scripts/ptomodel_tools.py build ...`.

- [ ] **Step 1: Write target-owner and real-entrypoint tests**

Change `tests/test_surface_mp_workflow.py` to import:

```python
from genkai.modeling.checklist import write_compact_job_bundle
```

Create `tests/skills/test_ptomodel_entrypoint.py` with a subprocess `--help`
test and an offline minimal build test. The build fixture contains one literal
relations JSONL row, and assertions check exit code 0 plus the generated
`sample_ptomodel.json` keys `schema_version`, `documents`, and
`surface_modeling_parameter_schema`.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/test_surface_mp_workflow.py \
  tests/skills/test_ptomodel_entrypoint.py -q --tb=short
```

Expected: collection fails because `genkai.modeling.checklist` does not exist.

- [ ] **Step 3: Move checklist code and rewire the thin entry**

Move `paperread/surface/modeling/job_bundle.py` to
`src/genkai/modeling/checklist.py`. Import `build_modeling_checklist` from that
module in `genkai.modeling.ptomodel`. Change the Skill wrapper import to:

```python
from genkai.modeling.ptomodel import main as ptomodel_main
```

Remove the now-empty legacy modeling package. Do not copy parsing, mapping, or
checklist rules into the Skill script.

- [ ] **Step 4: Run the checklist and entrypoint tests and verify GREEN**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/test_surface_mp_workflow.py \
  tests/skills/test_ptomodel_entrypoint.py \
  tests/integrations/test_surface_facades.py -q --tb=short
```

Expected: PASS; the real Skill subprocess uses the Genkai-owned implementation.

- [ ] **Step 5: Commit the checklist and thin entry**

```bash
git add src/genkai/modeling agents/Agent/skills/ptomodel/scripts \
  paperread/surface/modeling tests/test_surface_mp_workflow.py \
  tests/skills/test_ptomodel_entrypoint.py
git commit -m "refactor: make ptomodel skill a thin genkai entry"
```

### Task 3: Close Dependency Gates and Package the Canonical Schema

**Files:**

- Modify: `tests/architecture/test_import_boundaries.py`
- Modify: `tests/packaging/test_wheel_contents.py`
- Modify: `pyproject.toml`
- Modify: `agents/Agent/skills/ptomodel/SKILL.md`
- Modify: `agents/Agent/skills/surface-modeling/SKILL.md`
- Modify: `README.md`
- Modify: `GENKAI_EVOLUTION_PLAN.md`

**Interfaces:**

- Enforces: `find_forbidden_imports(ROOT / "src" / "genkai", set()) == set()`.
- Packages: `genkai/modeling/schema/task_parameter_schema.json` in source and wheel.

- [ ] **Step 1: Tighten architecture and wheel tests**

Replace the Task 12 allowlist with an empty set and extend the absent-path
assertion with `paperread/surface/modeling`. Extend the wheel test to compare
the source schema and extracted-wheel schema byte-for-byte and load its JSON to
assert the four canonical task names.

- [ ] **Step 2: Run the gates and verify RED**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/architecture \
  tests/packaging/test_wheel_contents.py -q --tb=short
```

Expected: wheel check fails until setuptools package-data includes the schema.

- [ ] **Step 3: Add package data and update canonical paths**

Add to `[tool.setuptools.package-data]`:

```toml
"genkai.modeling" = ["schema/*.json"]
```

Update both Skill documents, README, and the Task 12 status in
`GENKAI_EVOLUTION_PLAN.md` to name
`src/genkai/modeling/schema/task_parameter_schema.json` as the source of truth.
State that only the PToModel slice is complete and the structure-generation
algorithm slice remains pending.

- [ ] **Step 4: Run gates and related regression and verify GREEN**

Run:

```bash
../.venv/bin/python -m pytest \
  tests/architecture tests/modeling \
  tests/integrations/test_surface_facades.py \
  tests/workflow/test_surface_paper.py \
  tests/workflow/test_paper_to_mlip.py \
  tests/skills/test_ptomodel_entrypoint.py \
  tests/packaging/test_wheel_contents.py \
  tests/test_paperread_surface.py \
  tests/test_surface_mp_workflow.py -q --tb=short
```

Expected: PASS with no Task 12 reverse-import exception and with the same schema
content in the source tree and wheel.

- [ ] **Step 5: Commit the closed boundary**

```bash
git add tests/architecture tests/packaging pyproject.toml README.md \
  GENKAI_EVOLUTION_PLAN.md agents/Agent/skills/ptomodel/SKILL.md \
  agents/Agent/skills/surface-modeling/SKILL.md
git commit -m "test: close ptomodel ownership boundary"
```

### Task 4: Record Fresh Verification and Handoff

**Files:**

- Create: `work_logs/2026-08-04.md`
- Modify: `work_log.md`

**Interfaces:**

- Records: exact executed commands, counts, warnings, known full-suite boundary,
  and explicit non-executed scientific/runtime validation.

- [ ] **Step 1: Run completion scans**

Run:

```bash
rg -n "paperread\.surface\.modeling|agents/Agent/skills/surface-modeling/schema/task_parameter_schema\.json" \
  src tests agents README.md GENKAI_EVOLUTION_PLAN.md pyproject.toml
rg -n "TBD|TODO|<implementation-date>" \
  docs/superpowers/specs/2026-08-04-genkai-ptomodel-convergence-design.md \
  docs/superpowers/plans/2026-08-04-genkai-ptomodel-convergence.md
git diff --check
git status --short --branch
```

Expected: no legacy production/schema reference, no plan placeholder, no
whitespace error, and only intended changes before the final documentation
commit.

- [ ] **Step 2: Run the full related regression once more**

Run the Task 3 Step 4 command without reusing prior output. Record the exact
pass/subtest/warning counts. Then run repository collection once:

```bash
../.venv/bin/python -m pytest -q --tb=short
```

Record the actual result without treating the known `agent.tools` collection
boundary as part of the focused pass claim.

- [ ] **Step 3: Write the dated log and index**

Create `work_logs/2026-08-04.md` with scope, commits, moved/deleted ownership,
fresh verification output, the remaining surface-algorithm slice, and the list
of external/scientific runs not performed. Add only its link to `work_log.md`.

- [ ] **Step 4: Verify documentation and commit**

```bash
git diff --check
git status --short --branch
git add work_logs/2026-08-04.md work_log.md \
  docs/superpowers/plans/2026-08-04-genkai-ptomodel-convergence.md
git commit -m "docs: record ptomodel convergence milestone"
```
