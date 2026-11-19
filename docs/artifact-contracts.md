# Genkai artifact contracts

`src/genkai/contracts/` defines the stable hand-off format between literature,
modeling, compute, dataset, and MLIP stages. Every artifact has a type and
`schema_version`, a run-relative POSIX path, SHA-256, producer and parent IDs,
plus independent execution, evidence, and validation states.

The stable artifact chain is:

```text
paper -> extraction -> modeling-plan -> structure-set
-> calculation-input -> calculation-result -> dataset
-> model -> evaluation
```

Large trajectories and checkpoints stay in files. `manifest.json` contains
only references and provenance, is written atomically, and rejects absolute or
parent-escaping artifact paths. Shared executables and checkpoints use
`ExternalResourceRef`; they remain read-only and are not copied into the run.

Execution state and evidence are deliberately separate. In particular, VASP
input preparation is `prepared`, not `dft_calculated`; simulated labels are
always `evidence_level=mock`. DeepMD and UMA production preflight reject mock
datasets, while dry-run may preserve them with an explicit warning.

Use:

```python
from genkai.workflow.store import load_manifest

manifest = load_manifest(run_root)
for artifact in manifest.artifacts:
    print(artifact.artifact_id, artifact.artifact_type, artifact.evidence_level)
```

Incompatible artifact changes increment the schema major version. Consumers
declare requirements such as `dataset@1`; the workflow validator rejects
missing producers, wrong artifact types, incompatible majors, and cycles before
external execution.

## Saved literature inputs

Relation extraction writes one JSON object per line. The shared reader in
`genkai.literature.surface.core.records` also accepts historical concatenated,
pretty-printed JSON objects and JSON arrays. Artifact ingestion validates the
whole input, writes canonical JSONL to `stages/01_paperread/extraction.jsonl`,
and records the original file's hash as `metadata.source_sha256`. The artifact's
own `sha256` always describes the canonical run-local file.

`run_surface_extraction(..., conditions_csv=...)` optionally copies the condition
CSV to `stages/01_paperread/conditions.csv`. Its reference is stored on the
`ExtractionArtifact` and propagated to the `ModelingPlanArtifact`:

```json
{
  "conditions_table": {
    "path": "stages/01_paperread/conditions.csv",
    "sha256": "<SHA-256 of the saved CSV bytes>",
    "source_uri": "<original CSV path>"
  }
}
```

PToModel verifies that the path stays inside the run and that the hash matches
before writing a plan. `plan.json.sources` uses run-relative relation/condition
paths in artifact-backed runs. The standalone mapping API continues to use its
supplied input paths. Existing runs without a condition reference remain supported.

Condition rows match exact document IDs or `<document_id>_<paragraph_number>`.
The single-paper PDF route also recognizes its historical `surface_conditions_N`
and `surface_relations` ID pair. Other unmatched IDs never fall back to row order.
Each document preserves `condition_rows`; only non-conflicting values are used as
fallbacks when relation fields are absent. `condition_conflicts` and
`conditions_unmatched` produce `conditions` review items in the checklist. These
are planning review items, not a new execution task or a claim that an experiment
has been reproduced. Selecting among experimental procedures remains a review step.

`genkai-workflow init RUN --relations RELATIONS --conditions TABLE` supports
offline replay. `surface run` forwards its extracted condition CSV automatically.
Both default to `--modeling-mode prepare`, retaining the existing prepared
structure placeholder. With `--modeling-mode structure-only`, they instead call
the existing `genkai.modeling.surface.executor.execute_surface_plan` after planning.
Python callers pass `modeling_mode="structure-only"` and optionally a
`SurfaceExecutionOverrides` instance as `modeling_overrides` to either workflow API.
Overrides in prepare mode and unknown modes are rejected before extraction.

A successful structure-only run links `paper -> extraction -> modeling-plan ->
structure-set` in the manifest. The structure-set references the actual extxyz
file and its hash, keeps the modeling plan as its parent, and records the existing
executor's report, selected/skipped tasks and resolved parameters. Its execution
state is `succeeded`, evidence level is `heuristic`, calculator is `none`, and
`scientific_calculation_started` is false. `initialize_surface_paper_run` additionally
returns `structures_extxyz` and `execution_report` paths. It still invokes paper
extraction; structure-only controls modeling, not the extraction provider.

Missing execution inputs raise `SurfaceExecutionBlocked` (CLI exit 2), retaining
the extraction and modeling-plan artifacts. No empty structure-set is published
as a successful result. Resume with `surface execute --run-root RUN` and reviewed
inputs. Runtime execution failures retain the executor's failed stage and do not
fall back to a prepared placeholder. The executor builds slab, `vacancy_landscape`,
`surface_cluster_builder`, `sam_functionalization`, `ald_overlayer`, `amorphous_slab`
and `adsorbate_landscape` tasks; generic termination, dopant and single-atom tasks are
reported as skipped. Each frame's `info` carries `task`, `role`, `label` (`task:index`)
and, except for base surfaces, `built_on` (the label of the surface it was built on).
The execution report adds `base_surface`, `chain` (`enabled` and the steps of
`--chain`), `task_records` (builder manifests and vacancy indices), per-frame summaries,
and `resolution.defaults_used` for values taken from `--accept-defaults`; the
structure-set metadata repeats `chain`, `base_surface` and `defaults_used`.
