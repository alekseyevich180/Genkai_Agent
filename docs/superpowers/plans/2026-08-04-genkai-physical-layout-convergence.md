# Genkai Physical Layout Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply scheme A physically in the isolated worktree by separating archived research assets from active Genkai source ownership.

**Architecture:** `src/genkai/` is the reusable library owner; `agents/Agent/skills/` is the decision/CLI layer; `legacy/` contains retained standalone historical research assets. No active code path depends on the archived assets.

**Tech Stack:** Git path moves, Python AST/reference scan, pytest, setuptools/wheel.

## Global Constraints

- Modify only `/home/pj24001724/ku40000345/wu/Genkai_Agent/Genkai_Evolution` on `feat/genkai-evolution`.
- Do not modify the parent `main` worktree.
- Preserve archived file contents; do not rewrite scientific assets.
- Do not run network, VASP, GPU/PJM, MLIP, training, or MD workloads.

---

### Task 1: Establish the physical ownership gate

**Files:**

- Create: `tests/architecture/test_physical_layout.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_legacy_research_assets_have_an_archive_owner() -> None:
    assert (ROOT / "legacy" / "paperread" / "NERRE").is_dir()
    assert (ROOT / "legacy" / "paperread" / "ReactionSeek").is_dir()


def test_active_source_has_no_legacy_paperread_package() -> None:
    assert not (ROOT / "paperread" / "NERRE").exists()
    assert not (ROOT / "paperread" / "ReactionSeek").exists()
```

- [ ] **Step 2: Run RED**

Run `../.venv/bin/python -m pytest tests/architecture/test_physical_layout.py -q`; expect both tests to fail before the move.

- [ ] **Step 3: Move the retained assets**

Create `legacy/paperread/`, move the two tracked directories without editing
their files, and add `legacy/README.md` with the ownership statement.

- [ ] **Step 4: Run GREEN**

Run the same test; expect 2 passed.

- [ ] **Step 5: Commit**

```bash
git add legacy tests/architecture/test_physical_layout.py paperread
git commit -m "refactor: archive standalone paperread research assets"
```

### Task 2: Remove stale packaging ownership and verify references

**Files:**

- Modify: `pyproject.toml`
- Modify: `tests/packaging/test_wheel_contents.py`
- Modify: `README.md`
- Modify: `GENKAI_EVOLUTION_PLAN.md`

- [ ] **Step 1: Add failing wheel/reference assertions**

Assert the wheel has no `paperread/` entries and the source tree has no imports
whose module starts with `paperread.NERRE` or `paperread.ReactionSeek`.

- [ ] **Step 2: Remove package discovery target**

Change setuptools package discovery from `include = ["agent*", "agents*", "genkai*", "paperread*"]` to `include = ["agent*", "agents*", "genkai*"]`; document the new `legacy/` owner in README and the formal plan.

- [ ] **Step 3: Build and test cleanly**

Remove ignored build metadata, build a no-isolation wheel, run the physical-layout,
packaging, architecture, compatibility, and focused integration suites. Confirm
the wheel contains Genkai/Agent packages but no archived `paperread/` files.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/packaging README.md GENKAI_EVOLUTION_PLAN.md
git commit -m "chore: close active package ownership boundary"
```

### Task 3: Record the convergence checkpoint

**Files:**

- Modify: `docs/migration.md`
- Modify: `work_logs/2026-08-05.md`

- [ ] **Step 1: Record exact physical layout and tests**

Document the move, clean-wheel result, unchanged parent worktree, and any
pre-existing full-suite blocker.

- [ ] **Step 2: Run final status checks and commit**

Run `git diff --check`, `git status --short`, and the focused offline suite;
commit the log and migration updates.
