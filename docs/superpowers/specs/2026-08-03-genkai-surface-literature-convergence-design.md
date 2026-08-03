# Genkai Surface Literature Structure Convergence Design

**Date:** 2026-08-03

**Status:** Approved direction; implementation planning pending

## 1. Objective

Implement the first two tasks of controlled structure convergence in
the dedicated `Genkai_Evolution` worktree:

1. establish a measured structure baseline and enforce dependency boundaries;
2. move the stable surface-literature implementation into `src/genkai/` so the
   library owns its production code and data assets.

This worktree is an experimental area for the new structure. It does not need
to preserve the old `paperread.surface.*` Python import paths or the
`python -m paperread.surface` CLI. Scientific extraction behavior and output
content remain regression-tested even though module and command locations
change.

## 2. Scope

### 2.1 Included

- `paperread/surface/core/`
- `paperread/surface/extraction/`
- `paperread/surface/experience/`
- the literature-only part of `paperread/surface/pipeline/`
- surface tool catalog metadata and material-class JSON assets
- shared LLM configuration required by the migrated literature code
- a new `genkai-workflow surface` command group
- tests, packaging metadata, README, plan, and work-log updates directly needed
  by the migration

### 2.2 Excluded

- moving the PToModel algorithm or surface-modeling algorithm into
  `src/genkai/modeling/`; that remains Task 12
- changing extraction prompts, schemas, scientific heuristics, or material
  vocabularies except where an import or resource path must change
- real online extraction, VASP, GPU, PJM, structure relaxation, training, or MD
- reorganizing all repository tests and large fixtures; that remains Task 14
- deleting unrelated `paperread` projects

## 3. Target Structure and Ownership

The stable surface-literature implementation becomes:

```text
src/genkai/literature/surface/
├── __init__.py
├── core/
│   ├── catalog.py
│   ├── chemical_vocabulary.py
│   ├── common.py
│   ├── crystal_structures.py
│   ├── material_vocabulary.py
│   ├── surface_indices.py
│   └── surface_ontology.py
├── extraction/
│   ├── extract_surface_conditions.py
│   ├── extract_surface_relations.py
│   ├── ingest_pdf.py
│   ├── standardize_surface_time.py
│   └── summarize_surface_outputs.py
├── experience/
│   ├── collect_experience.py
│   ├── parameter_registry.py
│   ├── unknown_terms.py
│   └── material_classes/*.json
└── pipeline/
    └── runner.py
```

The existing `src/genkai/literature/surface.py` becomes the package entrypoint.
It continues to expose artifact-aware saved-extraction replay while also
providing deliberate public exports for migrated literature functions.

`paperread/surface/modeling/` remains temporarily because Task 12 owns its
physical migration. Its imports of surface vocabulary and ontology helpers are
updated to the new `genkai.literature.surface.core` locations. The rest of the
old `paperread/surface` implementation, top-level export layer, examples, and
CLI are removed once target tests pass.

## 4. Dependency Boundary

The intended dependency direction is:

```text
genkai.workflows
  |-> genkai.literature -> genkai.contracts
  `-> genkai.modeling   -> genkai.contracts
```

Sibling domain packages do not reach through each other's private modules.
Cross-stage coordination belongs in `genkai.workflows`.

Task 10 adds an AST-based architecture test that scans imports under
`src/genkai/`. It rejects imports from `paperread` and from
`agents.Agent.skills`. Because Task 12 is intentionally deferred, the two
legacy PToModel imports already present in `src/genkai/modeling/ptomodel.py` are
recorded as an exact, file-and-symbol allowlist. The allowlist cannot grow and
is documented as Task 12 debt. `src/genkai/literature/` receives no exception.

The structure baseline records:

- top-level and relevant package directories;
- `src/genkai -> paperread` imports;
- installed CLI entrypoints;
- source and wheel package/resource contents;
- surface skill entrypoints that consume the migrated APIs.

## 5. Processing and Data Flow

Pure literature processing is:

```text
PDF or JSON
  -> ingestion
  -> condition and relation extraction
  -> time normalization and summary
  -> optional experience collection
  -> literature output files / ExtractionArtifact
```

The migrated literature pipeline does not own PToModel. The old combined
surface runner is decomposed without changing output semantics:

- `genkai.literature.surface.pipeline` performs literature processing;
- a workflow-level orchestrator in `genkai.workflows` optionally calls the
  public `genkai.modeling` facade for PToModel and compact modeling-bundle
  output;
- `genkai-workflow surface run` invokes that workflow-level orchestrator;
- artifact-aware `genkai-workflow init`, `preflight`, and dry-run behavior
  continues through the existing paper-to-MLIP workflow.

The surface CLI group provides the literature commands `list-tools`, `ingest`,
`run`, `conditions`, `relations`, `time`, `summary`, `experience`, and
`registry`. A `ptomodel` action is not exposed as a literature command; modeling
remains a separate stage.

## 6. Shared LLM Configuration

The migrated literature code must not search parent directories for
`paperread/genkai_api_config.py`. The shared API configuration moves into a
normal `genkai` module and retains lazy client construction so importing the
library and requesting CLI help do not require an API key.

Other old `paperread` projects that currently import `genkai_api_config` are
updated to import the new Genkai-owned module. The old configuration file is
removed after an import scan confirms that it has no consumers. This is an
integration-path update only; provider selection and environment-variable
semantics do not change.

## 7. Migration and Failure Rules

- Use characterization tests before moving implementation files.
- Preserve callable signatures and literature output content unless this
  design explicitly changes an ownership boundary.
- Do not keep duplicate production implementations or compatibility shims for
  migrated `paperread.surface` paths.
- If a material-class asset is missing after packaging, registry construction
  fails explicitly rather than silently returning an incomplete vocabulary.
- PDF helper failures retain the failing executable and source path in the
  raised error. No fallback may fabricate extracted text.
- LLM errors propagate without writing a successful artifact or claiming
  online extraction completed.
- Existing output directories stay caller-controlled; the migration does not
  add an implicit `cd` or shared output location.
- The old surface paths are deleted only after their target imports and focused
  tests pass from the source tree.
- A wheel is accepted only after the new CLI help works without API keys and
  every canonical material-class JSON asset is present.

## 8. Testing Strategy

### 8.1 Baseline and architecture tests

- characterize source imports, CLI entrypoints, and package assets before the
  move;
- assert `genkai.literature` has no `paperread` or skill-script imports;
- assert the repository-wide reverse-import allowlist contains only the
  deferred Task 12 entries;
- assert removed surface modules are absent rather than shadowed by stale
  files.

### 8.2 Literature tests

- update surface core, extraction, experience, ingestion, normalization, and
  summary tests to import the new modules;
- update mock patch targets to the new module locations;
- retain offline characterization of condition, relation, time, summary, and
  experience outputs;
- check tool-catalog module paths resolve to importable new modules;
- check material-class registry behavior from both source and installed wheel.

### 8.3 Workflow and modeling boundary tests

- verify the pure literature pipeline does not import PToModel;
- verify the workflow-level surface runner can still produce the established
  combined outputs through `genkai.modeling`;
- retain the saved-extraction -> modeling plan -> structure-candidate artifact
  test;
- keep PToModel behavior tests while updating only the moved core-helper import
  paths.

### 8.4 CLI and packaging tests

- `genkai-workflow surface --help` and representative subcommand help exit 0;
- `python -m paperread.surface` is no longer an acceptance requirement;
- build a wheel without network dependency resolution;
- run `genkai.cli` help from the extracted wheel with API keys removed;
- verify all surface material-class JSON assets are included and loadable.

### 8.5 Final validation boundary

The completion claim is limited to source migration, import/CLI compatibility
within the new Genkai layout, offline scientific-output regressions, and wheel
packaging. It does not claim live LLM extraction or any scientific calculation.

## 9. Documentation and Completion Criteria

Update `README.md`, `GENKAI_EVOLUTION_PLAN.md`, `plan.md`, the dated work log,
and index-only `work_log.md` to describe the new source of truth and actual
validation commands.

Task 10 and Task 11 are complete when:

1. the baseline and dependency-boundary tests pass;
2. literature production code and assets exist only under `src/genkai/`;
3. new literature code has no imports from `paperread` or skill scripts;
4. the exact Task 12 allowlist has not grown;
5. new CLI commands, offline literature regressions, artifact integration, and
   wheel checks pass;
6. no real online extraction, calculation, scheduler job, training, or MD is
   represented as having run;
7. `git diff --check` passes and the work log states both executed and omitted
   validation scopes.
