# Migration and deprecation guide

## Current owners

| Previous location | Current owner | Compatibility status |
| --- | --- | --- |
| `paperread/surface/*` literature pipeline | `src/genkai/literature/surface/` | removed from source and wheel; use Genkai APIs |
| `paperread/surface/modeling/*` | `src/genkai/modeling/` | removed; use `genkai.modeling.ptomodel` |
| `agents/Agent/skills/surface-modeling/scripts/*` algorithms | `src/genkai/modeling/surface/` | thin Skill wrappers retained |
| Materials Project slab facet/termination logic | `src/genkai/modeling/surface/slab.py` | `materials_project_slab` and the `slab_generation` Skill call it; Miller indices refer to the conventional cell |
| (new, 2026-11-16) SAM, ALD amorphous-overlayer and pure amorphous-surface builders | `src/genkai/modeling/surface/sam.py`, `amorphous_overlayer.py`, `amorphous_slab.py`; shared `substrate.py`, `sites.py`, `structure_io.py` | Skill scripts `scripts/sam/sam_builder.py`, `scripts/ald/ald_overlayer.py` and `scripts/amorphous/amorphous_slab.py` are thin wrappers; not yet registered in the structure-only executor |
| (new, 2026-11-16) MLIP screening layer | `src/genkai/modeling/surface/calculators.py`, `sam_search.py`, `amorphous_screen.py`; island search stays in `cluster_search.py` | Skill scripts `scripts/sam/sam_search.py` and `scripts/amorphous/amorphous_screen.py` are thin wrappers; `calculator=none` is a mock for local tests |
| VASP/dataset/MLIP stable gates | `src/genkai/compute/`, `src/genkai/datasets/`, `src/genkai/mlip/` | Skill runtime launchers retained |
| paperread experience export rules | `src/genkai/literature/surface/experience/export_unknown_terms.py` | Skill script is a thin wrapper |

## Migration rules

- New code must import `genkai.*`; do not add imports from `paperread.surface`.
- New surface tasks should use the canonical module identifiers in
  `src/genkai/modeling/schema/task_parameter_schema.json`.
- Skill script paths remain supported only as thin CLI compatibility entries.
- `legacy/paperread/NERRE` and `legacy/paperread/ReactionSeek` are retained research assets;
  they are not part of the Genkai surface workflow owner migration.

## Deprecated/generated paths

The ignored `build/`, `*.egg-info/`, `__pycache__/`, and `.pytest_cache/` paths
are local build or test state and must not be used as wheel source. Rebuild the
wheel from a clean worktree when checking package contents.
