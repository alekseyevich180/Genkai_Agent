# Genkai Surface Literature Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the stable surface-literature implementation and assets into `src/genkai/`, enforce the new dependency direction, and replace the legacy surface CLI with `genkai-workflow surface`.

**Architecture:** `genkai.literature.surface` owns PDF/JSON ingestion, extraction, normalization, summaries, vocabulary, and experience data. `genkai.workflows.surface_paper` owns cross-stage orchestration and calls the public `genkai.modeling` facade, while an AST boundary test prevents new `src/genkai -> paperread` or skill-script imports.

**Tech Stack:** Python 3.12, Click, Pydantic v2, pandas, OpenAI compatibility client, pytest, setuptools/wheel, JSON/JSONL/CSV.

## Global Constraints

- Work only in `/home/pj24001724/ku40000345/wu/Genkai_Agent/Genkai_Evolution` on `feat/genkai-evolution`.
- The worktree is allowed to remove legacy `paperread.surface.*` imports and `python -m paperread.surface`; do not add compatibility shims.
- Do not change extraction prompts, schemas, scientific heuristics, or material vocabularies except for import/resource paths.
- Do not move the PToModel algorithm or surface-modeling algorithm; those remain Task 12.
- `src/genkai/literature/` must not import `paperread` or `agents.Agent.skills`.
- The existing two PToModel imports in `src/genkai/modeling/ptomodel.py` are the only temporary reverse-dependency allowlist; it must not grow.
- Keep outputs in caller-selected directories; do not add an implicit `cd` or shared output location.
- Run only offline tests, CLI help, static checks, and wheel checks. Do not run online LLM extraction, VASP, GPU, PJM, structure relaxation, training, or MD.
- Use tests before implementation and commit each task independently.

---

### Task 1: Record the Structure Baseline and Add Dependency Gates

**Files:**

- Create: `tests/architecture/__init__.py`
- Create: `tests/architecture/import_boundaries.py`
- Create: `tests/architecture/test_import_boundaries.py`
- Create: `docs/structure-baseline.md`

**Interfaces:**

- Consumes: a source root and an exact allowlist of `(relative_file, imported_module, imported_name)` tuples.
- Produces: `find_forbidden_imports(source_root: Path, allowlist: set[ImportRef]) -> set[ImportRef]` and the `ImportRef` tuple type.

- [ ] **Step 1: Write the boundary-helper tests**

Create tests using a temporary source tree. The first fixture imports
`paperread.surface.core`, the second imports
`agents.Agent.skills.mace.scripts`, and the third matches an exact allowlist.

```python
from pathlib import Path

from tests.architecture.import_boundaries import ImportRef, find_forbidden_imports


def test_forbidden_imports_are_reported_and_exact_allowlist_is_removed(tmp_path: Path):
    source = tmp_path / "src" / "genkai"
    source.mkdir(parents=True)
    (source / "bad.py").write_text(
        "from paperread.surface.core import common\n"
        "import agents.Agent.skills.mace.scripts\n",
        encoding="utf-8",
    )
    violations = find_forbidden_imports(source, set())
    assert ImportRef("bad.py", "paperread.surface.core", "common") in violations
    assert ImportRef("bad.py", "agents.Agent.skills.mace.scripts", None) in violations
```

- [ ] **Step 2: Run the helper test and verify the expected failure**

Run:

```bash
pytest tests/architecture/test_import_boundaries.py -v
```

Expected: FAIL during import because `tests.architecture.import_boundaries` does not exist.

- [ ] **Step 3: Implement the AST import scanner**

Implement `ImportRef` as a `NamedTuple`. Parse every `*.py` below the supplied
root, record `ast.Import` and `ast.ImportFrom`, retain only imports beginning
with `paperread` or `agents.Agent.skills`, and subtract only exact allowlist
entries.

```python
class ImportRef(NamedTuple):
    relative_file: str
    module: str
    name: str | None


def find_forbidden_imports(source_root: Path, allowlist: set[ImportRef]) -> set[ImportRef]:
    found: set[ImportRef] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(source_root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _forbidden(alias.name):
                        found.add(ImportRef(relative, alias.name, None))
            elif isinstance(node, ast.ImportFrom) and node.module and _forbidden(node.module):
                for alias in node.names:
                    found.add(ImportRef(relative, node.module, alias.name))
    return found - allowlist
```

- [ ] **Step 4: Add the repository gate and baseline document**

The repository test must use an exact allowlist for the current imports of
`build_modeling_checklist` and `build_ptomodel_payload` in
`src/genkai/modeling/ptomodel.py` and assert the returned violation set is
empty. Record the current top-level packages, legacy surface directories,
entrypoints (`agent`, `genkai-workflow`), material-class asset count, and the
two deferred reverse imports in `docs/structure-baseline.md` using values
measured from this checkout.

- [ ] **Step 5: Run the architecture tests**

Run:

```bash
pytest tests/architecture -v
```

Expected: PASS, with the exact Task 12 allowlist documented in the assertion.

- [ ] **Step 6: Commit the baseline and gate**

```bash
git add tests/architecture docs/structure-baseline.md
git commit -m "test: establish genkai dependency boundaries"
```

### Task 2: Move Shared LLM Configuration into Genkai

**Files:**

- Create: `src/genkai/llm.py`
- Create: `tests/literature/test_llm_config.py`
- Modify: `paperread/ReactionSeek/ReactionSeek/reaction_extract/extract_gpt.py`
- Modify: `paperread/ReactionSeek/ReactionSeek/standardize/time_standardlize.py`
- Modify: `paperread/ReactionSeek/ReactionSeek/standardize/name_to_smiles.py`
- Modify: `paperread/NERRE/general_and_mofs/utils.py`
- Modify: `paperread/NERRE/general_and_mofs/data/predict.py`
- Modify: `paperread/NERRE/doping/step2_train_predict.py`
- Delete: `paperread/genkai_api_config.py`

**Interfaces:**

- Produces: `get_api_key() -> str`, `get_base_url() -> str`, `get_model(default: str = "gpt-4o-mini") -> str`, `make_client() -> OpenAI`, and `install_openai_compat(openai_module) -> None`.
- Preserves: `LLM_API_KEY`, `OPENAI_API_KEY`, `LLM_BASE_URL`, `OPENAI_BASE_URL`, `LLM_MODEL`, and `OPENAI_MODEL` semantics.

- [ ] **Step 1: Write import-safety and configuration tests**

```python
def test_llm_module_imports_without_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    module = importlib.reload(importlib.import_module("genkai.llm"))
    assert module.get_api_key() == ""


def test_model_provider_prefix_is_normalized(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    module = importlib.reload(importlib.import_module("genkai.llm"))
    assert module.get_model() == "gpt-4o-mini"
```

Also add a source scan asserting no Python file still contains
`from genkai_api_config import` after migration.

- [ ] **Step 2: Run the tests and verify the expected failure**

Run:

```bash
pytest tests/literature/test_llm_config.py -v
```

Expected: FAIL because `genkai.llm` does not exist.

- [ ] **Step 3: Move the configuration implementation**

Move the current functions into `src/genkai/llm.py`. Resolve
`agents/Agent/.env` from the repository root when present, but do not construct
an OpenAI client at import time. Keep `make_client()` as the first point that
constructs `OpenAI(**kwargs)`.

- [ ] **Step 4: Update all remaining consumers and remove the old module**

Replace parent-directory `sys.path` searches and
`from genkai_api_config import ...` with direct imports from `genkai.llm` in
the six listed consumers. Delete `paperread/genkai_api_config.py` only after:

```bash
rg -n "genkai_api_config" paperread src tests
```

returns no source consumer.

- [ ] **Step 5: Run LLM and architecture tests**

Run:

```bash
pytest tests/literature/test_llm_config.py tests/architecture -v
python -m genkai.cli --help
```

Expected: all tests PASS and CLI help exits 0 without an API key.

- [ ] **Step 6: Commit shared configuration ownership**

```bash
git add src/genkai/llm.py tests/literature paperread
git commit -m "refactor: move llm configuration into genkai"
```

### Task 3: Move Surface Core, Extraction, and Experience into the Library

**Files:**

- Replace: `src/genkai/literature/surface.py` with package `src/genkai/literature/surface/`
- Create: `src/genkai/literature/surface/artifacts.py`
- Move: `paperread/surface/core/` to `src/genkai/literature/surface/core/`
- Move: `paperread/surface/extraction/` to `src/genkai/literature/surface/extraction/`
- Move: `paperread/surface/experience/` to `src/genkai/literature/surface/experience/`
- Move: `paperread/surface/examples/sample_surface_input.json` to `tests/fixtures/surface_literature/sample_surface_input.json`
- Modify: `src/genkai/literature/__init__.py`
- Modify: `paperread/surface/modeling/ptomodel.py`
- Modify: `paperread/surface/pipeline/runner.py`
- Modify: `tests/test_paperread_surface.py`
- Modify: `tests/integrations/test_surface_facades.py`

**Interfaces:**

- Preserves: `run_surface_extraction(request: str | Path, run_root: str | Path) -> ExtractionArtifact`.
- Produces public literature exports for tool catalog, ingestion, extraction, normalization, summary, and experience functions.
- Moves canonical resource ownership to `genkai.literature.surface.experience.material_classes`.

- [ ] **Step 1: Add target-import characterization tests**

Change literature imports and patch targets in `tests/test_paperread_surface.py`
to `genkai.literature.surface.*`, but leave PToModel imports under
`paperread.surface.modeling` and the combined pipeline import under
`paperread.surface.pipeline` until Task 4. Point `SAMPLE_INPUT` to the new test
fixture. Replace old direct-file entrypoint checks with package-module checks
for the new Genkai paths; central CLI checks are added in Task 4. Add:

```python
def test_surface_catalog_modules_resolve_from_new_owners():
    for spec in list_surface_tools():
        if spec.category != "planning":
            module = importlib.import_module(spec.module)
            assert callable(getattr(module, spec.function))
```

Add two failure-boundary characterizations:

```python
def test_empty_material_class_store_is_rejected(tmp_path):
    with pytest.raises(FileNotFoundError, match="material-class JSON assets"):
        build_surface_parameter_registry(material_class_dir=tmp_path)


def test_pdf_command_failure_identifies_executable_and_source(monkeypatch, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    error = subprocess.CalledProcessError(1, ["pdftotext", "-layout", str(pdf), "-"])
    monkeypatch.setattr(subprocess, "run", Mock(side_effect=error))
    with pytest.raises(subprocess.CalledProcessError) as caught:
        extract_pdf_text(str(pdf))
    assert "pdftotext" in caught.value.cmd
    assert str(pdf) in caught.value.cmd
```

- [ ] **Step 2: Run focused tests and verify the expected failure**

Run:

```bash
pytest tests/test_paperread_surface.py tests/integrations/test_surface_facades.py -v
```

Expected: FAIL because `genkai.literature.surface` is still a module and the
target subpackages do not exist.

- [ ] **Step 3: Convert the facade module into a package**

Move the existing artifact replay code unchanged into
`src/genkai/literature/surface/artifacts.py`. Create `surface/__init__.py` with
lazy public exports so importing it does not initialize the OpenAI client:

```python
_PUBLIC_EXPORTS = {
    "run_surface_extraction": (".artifacts", "run_surface_extraction"),
    "render_surface_tool_catalog": (".core.catalog", "render_surface_tool_catalog"),
    "collect_experience": (".experience.collect_experience", "collect_experience"),
    "ingest_pdf": (".extraction.ingest_pdf", "ingest_pdf"),
}
```

Implement `__getattr__` with `import_module` and update
`src/genkai/literature/__init__.py` to re-export only deliberate public APIs.

- [ ] **Step 4: Move implementation files and update imports**

Perform filesystem moves without copying duplicate implementations. Replace
legacy absolute imports with relative imports within
`genkai.literature.surface`. In `core/common.py`, import
`get_model` and `install_openai_compat` from `genkai.llm`. Remove direct-script
`sys.path` mutation fallbacks.

Update `paperread/surface/modeling/ptomodel.py` to import vocabulary, ontology,
and surface-index helpers from `genkai.literature.surface.core`. Do not change
its mapping logic or outputs.

Update the still-temporary `paperread/surface/pipeline/runner.py` imports for
core extraction and experience functions to the new Genkai package while
leaving its PToModel calls unchanged. This keeps the combined characterization
test passing until Task 4 splits and removes the old runner.

- [ ] **Step 5: Update the catalog and resource paths**

Set catalog module paths for migrated functions to
`genkai.literature.surface.*`. Set the planning entry to the public
`genkai.modeling.ptomodel` facade. Replace source-tree-relative
material-class discovery with `Path(__file__).parent / "material_classes"` so
the same code works in source and wheel installations. Make
`build_surface_parameter_registry` raise
`FileNotFoundError("material-class JSON assets not found: <path>")` when the
selected directory contains no `*.json` files; it must not return an empty
registry as a successful result.

- [ ] **Step 6: Run focused tests and architecture gates**

Run:

```bash
pytest tests/test_paperread_surface.py tests/integrations/test_surface_facades.py tests/literature tests/architecture -v
```

Expected: PASS for core, extraction, experience, saved replay, and deferred
PToModel behavior.

- [ ] **Step 7: Commit the library migration**

```bash
git add src/genkai/literature paperread/surface tests
git commit -m "refactor: move surface literature into genkai"
```

### Task 4: Separate Literature Processing from Workflow Orchestration and Add the New CLI

**Files:**

- Create: `src/genkai/literature/surface/pipeline/__init__.py`
- Create: `src/genkai/literature/surface/pipeline/runner.py`
- Create: `src/genkai/workflows/surface_paper.py`
- Modify: `src/genkai/cli.py`
- Create: `tests/workflow/test_surface_paper.py`
- Modify: `tests/test_paperread_surface.py`
- Modify: `tests/workflow/test_paper_to_mlip.py`
- Delete: `paperread/surface/pipeline/`

**Interfaces:**

- Produces: `run_literature_pipeline(...) -> dict[str, str]` and `run_literature_pipeline_from_pdf(...) -> dict[str, str]`.
- Produces: `initialize_surface_paper_run(input_source: str | Path, run_root: str | Path, *, input_format: Literal["auto", "json", "pdf"] = "auto", model: str | None = None, save_raw: bool = False, collect_experience_output: bool = False) -> dict[str, str]`.
- Consumes: `initialize_paper_to_mlip_run(run_root, relations)` from the existing artifact-aware reference workflow; it does not add a new PToModel legacy import.

- [ ] **Step 1: Write pipeline-boundary and workflow-output tests**

The pure pipeline test must patch the new extraction functions, run offline,
and assert it returns conditions, time, relations, summary, and optional
experience outputs but no `ptomodel_json`. The module source must not contain
`genkai.modeling` or `paperread` imports.

The workflow test must patch `initialize_paper_to_mlip_run`, call
`initialize_surface_paper_run`, and assert that the generated relations file is
passed into the existing artifact-aware initializer:

```python
def test_surface_workflow_initializes_artifact_chain_from_relations(monkeypatch, tmp_path):
    observed = {}
    monkeypatch.setattr(surface_paper, "run_literature_pipeline", lambda *a, **k: {
        "conditions_csv": "conditions.csv",
        "time_csv": "time.csv",
        "relations_jsonl": "relations.jsonl",
        "summary_txt": "summary.txt",
    })
    def initialize(run_root, relations, **kwargs):
        observed.update(run_root=Path(run_root), relations=Path(relations))
    monkeypatch.setattr(surface_paper, "initialize_paper_to_mlip_run", initialize)

    outputs = surface_paper.initialize_surface_paper_run("input.json", tmp_path)

    assert observed == {"run_root": tmp_path, "relations": Path("relations.jsonl")}
    assert outputs["manifest"] == str(tmp_path / "manifest.json")
```

- [ ] **Step 2: Write CLI tests for the new command group**

Use `click.testing.CliRunner` and assert:

```python
result = CliRunner().invoke(main, ["surface", "list-tools"])
assert result.exit_code == 0
assert "Surface tooling catalog" in result.output
```

Also assert `surface --help` lists `ingest`, `run`, `conditions`, `relations`,
`time`, `summary`, `experience`, and `registry`, but not `ptomodel`.

- [ ] **Step 3: Run the new tests and verify the expected failure**

Run:

```bash
pytest tests/workflow/test_surface_paper.py tests/workflow/test_paper_to_mlip.py -v
```

Expected: FAIL because `genkai.workflows.surface_paper` and the `surface` Click
group do not exist.

- [ ] **Step 4: Implement the pure literature pipeline**

Extract the ingestion, extraction, normalization, summary, and experience
sections from the old runner. Rename public functions to
`run_literature_pipeline` and `run_literature_pipeline_from_pdf`. These
functions must not import PToModel or compact-bundle code. They stop after
literature outputs and therefore do not return `ptomodel_json`, `modeling_plan`,
or compact-bundle paths.

- [ ] **Step 5: Implement workflow-level orchestration**

`initialize_surface_paper_run` chooses the JSON or PDF literature pipeline from
the explicit or suffix-derived input format. It requires a generated
`relations_jsonl`; otherwise it raises
`ValueError("surface workflow requires relation extraction")`. It then calls:

```python
initialize_paper_to_mlip_run(Path(run_root), Path(outputs["relations_jsonl"]))
```

and returns the literature output dictionary plus
`{"manifest": str(Path(run_root) / "manifest.json")}`. PToModel, checklist,
and structure-candidate production remain inside the existing reference
workflow, so the two-entry Task 12 allowlist does not grow.

- [ ] **Step 6: Add the Click command group**

Add `@main.group("surface")` to `src/genkai/cli.py`. Implement the nine agreed
subcommands with `click.Path(path_type=Path)` arguments and options matching
the new behavior. Import surface functions inside command bodies so
`genkai-workflow --help` remains API-key independent. Route `surface run` to
`initialize_surface_paper_run`. Do not expose legacy `--compact-output`,
`--expanded-output`, or `ptomodel`; artifact output is represented by the run
manifest.

- [ ] **Step 7: Run workflow, CLI, and architecture tests**

Run:

```bash
pytest tests/workflow/test_surface_paper.py tests/workflow/test_paper_to_mlip.py tests/architecture -v
python -m genkai.cli surface --help
python -m genkai.cli surface list-tools
```

Expected: all tests and commands PASS without network access.

- [ ] **Step 8: Commit workflow and CLI separation**

```bash
git add src/genkai/literature/surface/pipeline src/genkai/workflows src/genkai/cli.py tests paperread/surface/pipeline
git commit -m "feat: route surface literature through genkai workflow"
```

### Task 5: Remove Legacy Surface Entrypoints and Verify Wheel Assets

**Files:**

- Delete: `paperread/surface/__init__.py`
- Delete: `paperread/surface/__main__.py`
- Delete: `paperread/surface/cli.py`
- Delete: `paperread/surface/README.md`
- Delete: `paperread/surface/examples/`
- Modify: `paperread/surface/modeling/ptomodel.py`
- Modify: `pyproject.toml`
- Modify: `MANIFEST.in`
- Modify: `tests/packaging/test_wheel_contents.py`
- Modify: `tests/test_paperread_surface.py`

**Interfaces:**

- Produces: an installed wheel containing `genkai.literature.surface` Python modules and every canonical `experience/material_classes/*.json` asset.
- Removes: the `paperread.surface` package-level import and module CLI while retaining the Task 12 modeling directory as a namespace path.

- [ ] **Step 1: Write target-layout and wheel assertions**

Add a source-layout test asserting these paths do not exist:

```python
for relative in (
    "paperread/surface/core",
    "paperread/surface/extraction",
    "paperread/surface/experience",
    "paperread/surface/pipeline",
    "paperread/surface/cli.py",
    "paperread/surface/__main__.py",
    "paperread/surface/__init__.py",
):
    assert not (ROOT / relative).exists()
```

Update the wheel test to invoke `python -m genkai.cli surface --help` with API
keys removed. Compare the set of source material-class JSON filenames with the
set extracted from the wheel and assert exact equality and non-empty content.

- [ ] **Step 2: Run target tests and verify the expected failure**

Run:

```bash
pytest tests/architecture tests/packaging/test_wheel_contents.py -v
```

Expected: FAIL while legacy surface entrypoint files still exist and package
data is not explicitly declared.

- [ ] **Step 3: Remove obsolete entrypoints and direct-script assumptions**

Delete the listed files and directories after confirming their replacements
exist. In the retained Task 12 modeling module, remove `sys.path` mutation and
direct-script fallbacks; keep direct imports from the new Genkai core.

- [ ] **Step 4: Declare package data**

Add to `pyproject.toml`:

```toml
"genkai.literature.surface" = ["experience/material_classes/*.json"]
```

Update `MANIFEST.in` to include the same canonical assets in source
distributions. Do not add old surface paths back to packaging.

- [ ] **Step 5: Run source and wheel verification**

Run:

```bash
pytest tests/architecture tests/packaging/test_wheel_contents.py -v
python -m genkai.cli --help
python -m genkai.cli surface --help
```

Expected: PASS; the extracted wheel loads CLI help without API keys and
contains the exact source asset set.

- [ ] **Step 6: Commit legacy cleanup and packaging**

```bash
git add paperread/surface pyproject.toml MANIFEST.in tests/packaging tests/architecture tests/test_paperread_surface.py
git commit -m "refactor: remove legacy surface entrypoints"
```

### Task 6: Update Documentation, Logs, and Run Final Verification

**Files:**

- Modify: `README.md`
- Modify: `GENKAI_EVOLUTION_PLAN.md`
- Modify: `plan.md`
- Create: `work_logs/2026-08-03.md`
- Modify: `work_log.md`

**Interfaces:**

- Records: the new source of truth, completed Task 10–11 scope, exact validation commands, and explicit non-executed scientific workflows.

- [ ] **Step 1: Update repository documentation**

Replace statements that `paperread.surface` remains available with the new
`genkai.literature.surface` source of truth and `genkai-workflow surface`
examples. Update material-class paths and explain that Task 12 still owns the
temporary PToModel implementation under `paperread/surface/modeling`.

Mark Task 10 and Task 11 complete in `GENKAI_EVOLUTION_PLAN.md`, record the
exact reverse-dependency allowlist, and leave Task 12 pending. Update `plan.md`
only where its stage/import descriptions refer to the removed surface paths.

- [ ] **Step 2: Run focused scientific-output regressions**

Run:

```bash
pytest tests/test_paperread_surface.py tests/integrations/test_surface_facades.py tests/workflow/test_surface_paper.py tests/workflow/test_paper_to_mlip.py -v
```

Expected: PASS using mocks and saved fixtures only.

- [ ] **Step 3: Run architecture, CLI, and packaging verification**

Run:

```bash
pytest tests/architecture tests/literature tests/packaging/test_wheel_contents.py -v
python -m genkai.cli --help
python -m genkai.cli surface --help
python -m genkai.cli surface list-tools
```

Expected: PASS without API keys, network access, or external calculations.

- [ ] **Step 4: Run the broader related regression set**

Run:

```bash
pytest tests/contracts tests/workflow tests/integrations tests/skills tests/test_paperread_surface.py tests/test_surface_mp_workflow.py tests/test_agent.py -v
```

Expected: PASS. If the repository-wide `pytest -q` is also attempted, report
the existing `agent.tools.structure_builder` collection boundary separately
unless it has changed in this checkout.

- [ ] **Step 5: Write the dated work log and index entry**

`work_logs/2026-08-03.md` must list modified ownership boundaries, commit
checkpoints, actual command outputs, test counts, warnings, and failures fixed.
It must explicitly state that online LLM extraction, VASP, GPU/CUDA, PJM,
structure relaxation, DeepMD training, UMA fine-tuning, and MD did not run.

Add only a dated link to `work_log.md`; do not put detailed results in the
index.

- [ ] **Step 6: Run repository consistency checks**

Run:

```bash
rg -n "paperread\.surface\.(core|extraction|experience|pipeline|cli)" src tests README.md docs agents
git diff --check
git status --short
```

Expected: no stale production/test/documentation imports for removed modules,
no whitespace errors, and status contains only Task 10–11 documentation/log
changes not yet committed.

- [ ] **Step 7: Commit documentation and verification evidence**

```bash
git add README.md GENKAI_EVOLUTION_PLAN.md plan.md work_log.md work_logs/2026-08-03.md
git commit -m "docs: record surface literature convergence"
```

- [ ] **Step 8: Report the completion boundary**

Report source/wheel/CLI/test results, the remaining Task 12 allowlist, and all
scientific workflows not executed. Do not describe offline mocks or saved
replay as current online extraction evidence.
