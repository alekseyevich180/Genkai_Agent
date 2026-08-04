# Genkai PToModel Structure Convergence Design

**Date:** 2026-08-04

**Status:** Approved for the one-hour continuous optimization slice

## 1. Objective

Complete the first independently verifiable slice of Task 12 by moving the
stable PToModel mapping, modeling-checklist logic, and task-parameter schema
from legacy `paperread` and Skill-owned locations into `src/genkai/modeling/`.
After this slice, `src/genkai/` has no reverse import into `paperread`, while
the PToModel Skill remains an on-demand thin command entry.

The ASE, pymatgen, Optuna, and FAIRChem surface-structure algorithms remain a
separate Task 12 slice. They are larger runtime components and are not mixed
into this ownership change.

## 2. Considered Approaches

1. **Staged vertical convergence (selected).** Move PToModel, checklist, and
   their schema together, remove the corresponding legacy implementation, and
   verify the complete input-to-artifact path before moving structure builders.
2. **One-shot Task 12 migration.** Move PToModel and all surface-modeling
   scripts together. This combines more than 3,600 lines of optional-runtime
   code with the mapping migration and weakens failure isolation.
3. **Facade-only rewiring.** Keep the old implementation and adjust imports.
   This would preserve the reverse ownership problem and would not produce
   physical structure convergence.

## 3. Target Ownership

```text
src/genkai/modeling/
├── __init__.py
├── ptomodel.py               # artifact-aware facade and stable mapping API
├── checklist.py              # modeling checklist and compact bundle writer
├── schema/
│   └── task_parameter_schema.json
└── surface.py                # existing candidate-plan facade

agents/Agent/skills/ptomodel/scripts/ptomodel_tools.py
                              # thin argparse entry calling genkai.modeling
```

The following legacy files are removed rather than retained as duplicate
implementations or compatibility shims:

- `paperread/surface/modeling/ptomodel.py`
- `paperread/surface/modeling/job_bundle.py`
- `paperread/surface/modeling/__init__.py`
- `agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json`

The canonical schema is a package resource owned by `genkai.modeling`. Skill
documentation points to that source of truth; it does not keep a second copy.

## 4. Public Interfaces and Data Flow

`genkai.modeling.ptomodel` owns and exports:

```python
build_ptomodel_payload(
    relations_jsonl: str,
    table_csv: str | None = None,
    summary_txt: str | None = None,
    time_csv: str | None = None,
) -> dict[str, Any]

generate_ptomodel_output(
    relations_jsonl: str,
    output_dir: str,
    stem: str,
    table_csv: str | None = None,
    summary_txt: str | None = None,
    time_csv: str | None = None,
) -> dict[str, str]

build_modeling_plan(
    extraction: ExtractionArtifact,
    run_root: str | Path,
) -> ModelingPlanArtifact

main(argv: list[str] | None = None) -> int
```

`genkai.modeling.checklist` owns and exports:

```python
build_modeling_checklist(plan: dict[str, Any]) -> dict[str, Any]

write_compact_job_bundle(
    *,
    output_dir: str,
    outputs: dict[str, str],
    source_path: str | None = None,
    cleanup_generated: bool = True,
) -> dict[str, str]
```

The data flow remains:

```text
surface relations + optional CSV/summary/time
-> build_ptomodel_payload
-> plan.json
-> build_modeling_checklist
-> checklist.json
-> ModelingPlanArtifact + RunManifest stage
```

PToModel continues to depend on public surface-literature vocabulary and
ontology APIs. It resolves `task_parameter_schema.json` with
`importlib.resources`, so source and installed-wheel behavior use the same
resource without repository-relative path traversal.

## 5. Behavioral and Failure Boundaries

- Preserve existing PToModel mapping rules, task selection, argument bindings,
  output keys, schema version, and CLI arguments.
- Update provenance ownership from the legacy module to
  `genkai.modeling.ptomodel`.
- Missing or malformed canonical schema data fails explicitly; PToModel must
  not silently produce an empty task registry.
- The architecture gate has an empty reverse-import allowlist after migration.
- The PToModel Skill parses user-facing arguments and calls the public library
  entry. It does not contain mapping or checklist rules.
- The `surface-modeling` Skill continues to own external-runtime launchers and
  experimental structure algorithms until the next Task 12 design slice.
- No online LLM request, VASP, GPU/CUDA, PJM job, model training, relaxation,
  or molecular dynamics run is part of this change.

## 6. Testing and Packaging

Use characterization tests before moving production code. The migration is
accepted only when current PToModel behavior passes through the new imports and
the old package is absent.

Required evidence:

1. PToModel characterization tests import `genkai.modeling.ptomodel` and retain
   hand-checked mapping assertions.
2. Checklist and compact-bundle tests import `genkai.modeling.checklist`.
3. A schema-resource test loads the canonical task registry from both source
   and a built wheel.
4. The PToModel Skill `--help` and a minimal offline `build` call execute the
   thin entry against the new library.
5. The architecture test reports no forbidden `src/genkai -> paperread` or
   Skill-script imports and uses no Task 12 allowlist.
6. Focused literature, workflow, integration, Skill-entry, and packaging tests
   pass; `git diff --check` is clean.

Repository-wide `pytest` remains a separate boundary because the current
checkout still lacks `agent.tools.structure_builder`. This slice does not hide
or claim to fix that pre-existing collection error.

## 7. Completion Criteria

This slice is complete when:

1. PToModel, checklist, and schema production ownership exists only under
   `src/genkai/modeling/`;
2. `paperread/surface/modeling/` and the Skill-owned schema copy are absent;
3. the PToModel Skill is a thin library entry;
4. the reverse-import allowlist is empty and the boundary test passes;
5. focused source and wheel regressions pass with unchanged scientific mapping
   behavior;
6. the dated work log records exact commands, results, and unexecuted external
   or scientific validation.
