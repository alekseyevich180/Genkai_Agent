# Genkai Compute, Dataset, and MLIP Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Task13 by centralizing compute, dataset, MLIP, and launcher contracts under `src/genkai/` while keeping Skills as thin external-runtime entrypoints.

**Architecture:** Add a dependency-free launcher contract registry in `src/genkai/mlip/launchers.py`. Existing adapters consume the registry; Skill scripts retain CLI/runtime orchestration but not dataset audits, artifact gates, or role contracts.

**Tech Stack:** Python 3.12, pytest, ASE, shell syntax checks, setuptools/wheel.

## Global Constraints

- Do not run VASP, GPU/CUDA, PJM, MACE/DeepMD/UMA inference or training, or online services.
- Preserve public adapter signatures and existing Skill command flags.
- Keep optional imports lazy and library imports offline.
- Do not add a `src/genkai -> agents.Agent.skills` or `src/genkai -> paperread` dependency.

---

### Task 1: Define the canonical launcher contract registry

**Files:**

- Create: `src/genkai/mlip/launchers.py`
- Test: `tests/mlip/test_launcher_contracts.py`

**Interfaces:**

- `LauncherContract(name: str, environment_variable: str, role: str, required_markers: tuple[str, ...])`
- `LAUNCHER_CONTRACTS: Mapping[str, LauncherContract]`
- `get_launcher_contract(name: str) -> LauncherContract`

- [ ] **Step 1: Write failing tests**

```python
from genkai.mlip.launchers import LAUNCHER_CONTRACTS, get_launcher_contract


def test_registry_covers_all_adapter_roles() -> None:
    assert set(LAUNCHER_CONTRACTS) == {"mace", "deepmd", "uma"}
    assert get_launcher_contract("mace").environment_variable == "GENKAI_MACE_LAUNCHER"
    assert "MACE_WORK_DIR" in get_launcher_contract("mace").required_markers


def test_unknown_launcher_is_rejected() -> None:
    try:
        get_launcher_contract("vasp")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown launcher must fail closed")
```

- [ ] **Step 2: Run the test and verify RED**

Run `../.venv/bin/python -m pytest tests/mlip/test_launcher_contracts.py -q`.
Expected: collection fails because `genkai.mlip.launchers` does not exist.

- [ ] **Step 3: Implement the minimal registry**

Use frozen dataclasses and exact existing marker names from the adapters:
MACE (`MACE_WORK_DIR`, `MACE_PYTHON_ARGS`, `MACE_DRY_RUN`), DeepMD
(`DEEPMD_WORK_DIR`, `DEEPMD_ARGS`, `DEEPMD_REQUIRED_PATHS`, `DEEPMD_DRY_RUN`),
and UMA (`UMA_FINETUNE_WORK_DIR`, `UMA_FINETUNE_CONFIG`,
`UMA_FINETUNE_DRY_RUN`, `UMA_FINETUNE_BASE_MODEL_PATH`,
`UMA_FINETUNE_BASE_MODEL_SHA256`).

- [ ] **Step 4: Run the test and verify GREEN**

Run the same pytest command; expect 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/genkai/mlip/launchers.py tests/mlip/test_launcher_contracts.py
git commit -m "feat: define canonical MLIP launcher contracts"
```

### Task 2: Make adapters consume the registry and audit Skill boundaries

**Files:**

- Modify: `src/genkai/mlip/mace.py`
- Modify: `src/genkai/mlip/deepmd.py`
- Modify: `src/genkai/mlip/uma.py`
- Modify: `tests/architecture/test_import_boundaries.py`
- Modify: `tests/architecture/import_boundaries.py`
- Test: `tests/mlip/test_launcher_contracts.py`

**Interfaces:**

- Adapter marker validation uses `get_launcher_contract()` rather than local
  duplicate tuples.
- `find_skill_dataset_contract_violations()` reports Skill Python files that
  define audit/gate logic without importing `genkai.datasets` or
  `genkai.mlip.protocol`.

- [ ] **Step 1: Add failing static-boundary tests**

Scan `agents/Agent/skills/{vasp,mace,deepmd,uma}/scripts` and assert that
`validate_uma_finetune_data.py` imports `genkai.datasets.ase`, while no Skill
script defines `training_dataset_gate`, `artifact_integrity_gate`, or
`audit_dataset_splits`.

- [ ] **Step 2: Run tests and verify RED**

Run `../.venv/bin/python -m pytest tests/architecture tests/mlip/test_launcher_contracts.py -q`.
The new registry-consumption assertions fail until adapters are updated.

- [ ] **Step 3: Replace local marker tuples with registry lookups**

Import `get_launcher_contract` in each adapter and pass
`contract.environment_variable` and `contract.required_markers` to
`resolve_launcher`; preserve command arguments and environment output.

- [ ] **Step 4: Run focused integration tests**

Run `../.venv/bin/python -m pytest tests/architecture tests/mlip tests/integrations/test_compute_dataset_mlip_contracts.py -q --tb=short`.
Expect all tests to pass without starting an external runtime.

- [ ] **Step 5: Commit**

```bash
git add src/genkai/mlip tests/architecture
git commit -m "refactor: route MLIP adapters through canonical contracts"
```

### Task 3: Verify legacy entrypoints, packaging, and document Task13

**Files:**

- Modify: `tests/packaging/test_wheel_contents.py`
- Modify: `README.md`
- Modify: `GENKAI_EVOLUTION_PLAN.md`
- Modify: `work_logs/2026-08-04.md`

- [ ] **Step 1: Add packaging assertions**

Assert the extracted wheel imports `genkai.mlip.launchers`, exposes all three
contracts, and contains no `agents.Agent.skills` imports in `src/genkai`.

- [ ] **Step 2: Run offline entrypoint checks**

Run the focused integration suite, VASP `--help`, shell `bash -n` checks for
MACE/DeepMD/UMA, and a no-isolation wheel build. Do not invoke the commands
without `--help` or dry-run markers.

- [ ] **Step 3: Update status and log**

Mark Task13 complete while explicitly preserving the external-runtime boundary
and record the pre-existing full-suite collection blocker if present.

- [ ] **Step 4: Commit and verify clean state**

```bash
git add tests/packaging/test_wheel_contents.py README.md GENKAI_EVOLUTION_PLAN.md work_logs/2026-08-04.md
git commit -m "docs: close compute dataset and MLIP convergence"
git status --short
```
