---
name: ptomodel
description: Filter and normalize paperread surface-extraction outputs into Agent-ready modeling inputs, including facet equivalence, loaded nanoparticle species, material class, reaction type, and executable modeling task mapping.
metadata:
  tools:
    - run_skill_script
  dependent_skills:
    - surface-modeling
  tags:
    - paperread
    - surface
    - modeling
    - normalization
    - planning
---

# PToModel

Use this skill after `paperread` when the agent needs a stable bridge from
paper-extracted key information to downstream surface-modeling actions.

This skill does not run DFT or structure generation itself. It selects useful
surface-research information, normalizes equivalent expressions, and writes one
JSON file that downstream Agent steps can read directly.

```text
paperread outputs
-> ptomodel filters useful fields
-> ptomodel normalizes equivalent expressions
-> ptomodel maps to supported modeling tasks
-> surface-modeling executes supported tasks
```

## Script

Script:

```text
scripts/ptomodel_tools.py
```

Run it with `run_skill_script`:

```text
run_skill_script(
  skill_name="ptomodel",
  script_name="ptomodel_tools.py",
  args="build --relations ./paperread_output/paper_surface_relations.jsonl --table ./paperread_output/paper_table.csv --summary ./paperread_output/paper_summary.txt --output-dir ./paperread_output"
)
```

## Command

### Build PToModel JSON

```bash
python scripts/ptomodel_tools.py build \
  --relations ./paperread_output/paper_surface_relations.jsonl \
  --table ./paperread_output/paper_table.csv \
  --summary ./paperread_output/paper_summary.txt \
  --output-dir ./paperread_output
```

Main output:

- `*_ptomodel.json`

## Output Focus

The JSON should prioritize:

- surface facet / Miller index normalization such as `(1 1 1)` -> `(111)`
- loaded nanoparticle or cluster species such as `Pt13 cluster` -> `Pt`
- single-atom species normalization when present
- material class inference such as oxide, carbon material, supported catalyst,
  single-atom catalyst, defect-engineered material
- reaction type normalization such as `CO oxidation` or `OER`
- supported modeling task mapping for:
  - `vacancy_landscape`
  - `adsorbate_landscape`
  - `surface_cluster_builder`

Other inferred tasks can stay in `deferred_tasks` for later human or skill
extension.

## Call Relationship To Surface-Modeling Config

The current call relationship is:

```text
paperread outputs
-> ptomodel selects executable task names
-> ptomodel builds task_inputs from extracted paper fields
-> ptomodel loads surface-modeling parameter schema JSON
-> ptomodel writes task_parameter_schema_refs into *_ptomodel.json
-> downstream agent fills concrete argument values against that schema
-> surface-modeling script executes
```

The surface-modeling parameter schema file is:

- `agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json`

In `*_ptomodel.json`:

- top-level `surface_modeling_parameter_schema` contains the shared task schema registry
- each document's `task_inputs` contains paper-derived modeling context
- each document's `task_parameter_schema_refs` links an executable task to the matching schema entry by `task_key`
- each document's `task_argument_template` pre-expands the task schema into:
  - `arguments`: parameter skeleton with auto-filled values when safe
  - `argument_sources`: whether each parameter is auto-mapped, needs upstream structure artifacts, or still needs manual choice
  - `required_missing_parameters`: required slots still unresolved

So `ptomodel` is not supposed to invent final CLI values by itself. Its job is to:

- decide which supported task applies
- provide normalized paper evidence as `task_inputs`
- point downstream execution to the exact parameter schema that must be filled
- make paper-to-parameter links explicit where they are safe enough to materialize

## Usage Policy

- Prefer `paperread` first; use `ptomodel` on `paperread` outputs rather than on
  raw PDFs.
- Treat `selected_information` as the filtered paper evidence.
- Treat `normalized_mapping` as the downstream Agent input contract.
- When `global_executable_tasks` is non-empty, the next step can continue into
  `surface-modeling`.
- When important terms are still unmapped, follow with
  `paperread-surface-learning`.
