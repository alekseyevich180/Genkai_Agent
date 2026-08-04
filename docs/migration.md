# Migration and deprecation guide

## Current owners

| Previous location | Current owner | Compatibility status |
| --- | --- | --- |
| `paperread/surface/*` literature pipeline | `src/genkai/literature/surface/` | removed from source and wheel; use Genkai APIs |
| `paperread/surface/modeling/*` | `src/genkai/modeling/` | removed; use `genkai.modeling.ptomodel` |
| `agents/Agent/skills/surface-modeling/scripts/*` algorithms | `src/genkai/modeling/surface/` | thin Skill wrappers retained |
| VASP/dataset/MLIP stable gates | `src/genkai/compute/`, `src/genkai/datasets/`, `src/genkai/mlip/` | Skill runtime launchers retained |

## Migration rules

- New code must import `genkai.*`; do not add imports from `paperread.surface`.
- New surface tasks should use the canonical module identifiers in
  `src/genkai/modeling/schema/task_parameter_schema.json`.
- Skill script paths remain supported only as thin CLI compatibility entries.
- `paperread/NERRE` and `paperread/ReactionSeek` are retained research assets;
  they are not part of the Genkai surface workflow owner migration.

## Deprecated/generated paths

The ignored `build/`, `*.egg-info/`, `__pycache__/`, and `.pytest_cache/` paths
are local build or test state and must not be used as wheel source. Rebuild the
wheel from a clean worktree when checking package contents.
