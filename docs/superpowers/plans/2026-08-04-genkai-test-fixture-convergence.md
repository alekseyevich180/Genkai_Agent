# Genkai Test and Fixture Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Task14 by enforcing test tiers and documenting/separating large fixtures.

**Architecture:** Pytest markers describe contract, unit, integration, compatibility, and external tiers. Compatibility tests move under `tests/compatibility`; external tests are reserved under `tests/external`. Fixture paths and provenance are centralized under `tests/fixtures/`.

**Tech Stack:** Python 3.12, pytest, pathlib, JSON/JSONL/ASE fixtures.

## Global Constraints

- Offline tests must not fetch papers, call APIs, run VASP, train MLIPs, or submit jobs.
- Preserve compatibility test behavior and legacy script-path checks.
- Do not alter production code.
- Full repository collection remains separately reported if the existing `agent.tools.structure_builder` blocker persists.

---

### Task 1: Add test-tier markers and collection gates

**Files:**

- Create: `tests/conftest.py`
- Create: `tests/test_test_tiers.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path


def test_test_tier_markers_are_registered() -> None:
    config = Path("pyproject.toml").read_text(encoding="utf-8")
    for marker in ("unit", "contract", "integration", "compatibility", "external"):
        assert f"{marker}:" in config


def test_external_tests_have_a_dedicated_directory() -> None:
    assert Path("tests/external").is_dir()
```

- [ ] **Step 2: Run RED**

Run `../.venv/bin/python -m pytest tests/test_test_tiers.py -q`; expect failure because markers and directory are absent.

- [ ] **Step 3: Implement marker registration**

Add `tests/conftest.py` with `pytest_configure` marker registration and
`pyproject.toml` pytest options:

```toml
[tool.pytest.ini_options]
markers = [
  "unit: isolated deterministic test",
  "contract: artifact or API contract test",
  "integration: offline multi-component test",
  "compatibility: legacy entrypoint compatibility test",
  "external: requires external runtime or network and is opt-in",
]
addopts = "-m 'not external'"
```

Create empty `tests/external/__init__.py` and mark existing tiered test modules
with module-level `pytestmark` declarations.

- [ ] **Step 4: Run GREEN**

Run the same command; expect 2 passed, then run `pytest --markers` and confirm all five markers are listed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/conftest.py tests/test_test_tiers.py tests/external
git commit -m "test: define explicit pytest tiers"
```

### Task 2: Move compatibility tests and centralize fixture paths

**Files:**

- Move: `tests/test_paperread_surface.py` -> `tests/compatibility/test_paperread_surface.py`
- Move: `tests/test_surface_mp_workflow.py` -> `tests/compatibility/test_surface_mp_workflow.py`
- Create: `tests/compatibility/__init__.py`
- Create: `tests/fixtures/README.md`
- Create: `tests/fixtures/paths.py`
- Modify: moved tests and any fixture consumers

- [ ] **Step 1: Add failing location tests**

Extend `tests/test_test_tiers.py`:

```python
def test_legacy_characterization_tests_are_compatibility_tests() -> None:
    assert Path("tests/compatibility/test_paperread_surface.py").is_file()
    assert Path("tests/compatibility/test_surface_mp_workflow.py").is_file()
```

- [ ] **Step 2: Run RED**

Run `../.venv/bin/python -m pytest tests/test_test_tiers.py -q`; the new paths fail until moved.

- [ ] **Step 3: Move files and repair only project-root calculation**

Use `PROJECT_ROOT = Path(__file__).resolve().parents[2]` in both moved tests;
add `pytestmark = pytest.mark.compatibility` and preserve all assertions,
mocks, and legacy path loading.

- [ ] **Step 4: Verify compatibility tests**

Run:

```bash
../.venv/bin/python -m pytest tests/compatibility tests/test_test_tiers.py -q --tb=short
```

Expect the same compatibility count as before plus tier tests.

- [ ] **Step 5: Commit**

```bash
git add tests/compatibility tests/test_test_tiers.py tests/test_paperread_surface.py tests/test_surface_mp_workflow.py
git commit -m "test: isolate compatibility characterization suite"
```

### Task 3: Mark existing tiers and close Task14 documentation

**Files:**

- Modify: `tests/contracts/*.py`, `tests/architecture/*.py`, `tests/modeling/*.py`, `tests/literature/*.py`, `tests/mlip/*.py`, `tests/integrations/*.py`, `tests/workflow/*.py`, `tests/packaging/*.py`
- Modify: `GENKAI_EVOLUTION_PLAN.md`
- Modify: `README.md`
- Modify: `work_logs/2026-08-04.md`

- [ ] **Step 1: Add module markers**

Use one `pytestmark` per module: contract tests use `contract`, focused library
tests use `unit`, integration/workflow/packaging use `integration`, and moved
compatibility tests use `compatibility`. Add `tests/external/README.md` stating
that external tests are opt-in and currently empty.

- [ ] **Step 2: Run tiered offline suite**

Run `../.venv/bin/python -m pytest tests/contracts tests/architecture tests/modeling tests/literature tests/mlip tests/integrations tests/workflow tests/compatibility tests/packaging tests/test_test_tiers.py -q --tb=short`; record the result.

- [ ] **Step 3: Verify external exclusion**

Run `../.venv/bin/python -m pytest --collect-only -q -m external`; confirm no external tests execute and default collection reports the marker configuration.

- [ ] **Step 4: Update plan/readme/log**

Mark Task14 complete, link the design/plan and fixture inventory, and record
exact test counts and the pre-existing full-suite collection blocker.

- [ ] **Step 5: Commit and verify clean state**

```bash
git add tests GENKAI_EVOLUTION_PLAN.md README.md work_logs/2026-08-04.md docs/superpowers
git commit -m "test: reorganize tiers and fixture provenance"
git status --short
```
