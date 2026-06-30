---
name: paperread-surface-learning
description: Export unfamiliar or unmapped surface-research terms from paperread outputs into reusable skill experience notes.
metadata:
  tools:
    - run_skill_script
  dependent_skills:
    - surface-modeling
  tags:
    - paperread
    - surface
    - learning
    - experience
    - ontology
---

# Paperread Surface Learning

Use this skill when `paperread/surface` extracts unfamiliar surface-research
terms, unsupported modeling cues, or concepts that cannot yet be mapped to an
existing surface-modeling workflow.

The purpose is to preserve experience instead of losing it:

```text
paperread extraction
-> unfamiliar term / unmapped modeling cue
-> experience note
-> later schema, prompt, planner, or surface-modeling skill update
```

This skill does not run calculations and does not modify `surface-modeling`
directly. It writes candidate experience records that can be reviewed and then
folded into future skills or planner rules.

## Script

Script:

```text
scripts/export_surface_experience.py
```

Run it with `run_skill_script`:

```text
run_skill_script(
  skill_name="paperread-surface-learning",
  script_name="export_surface_experience.py",
  args="export --relations tests/test2_api_surface_relations.jsonl --table tests/test2_api_table.csv"
)
```

## Commands

### Export From Paperread Outputs

```bash
python scripts/export_surface_experience.py export \
  --relations tests/test2_api_surface_relations.jsonl \
  --table tests/test2_api_table.csv
```

Outputs by default:

- `agents/Agent/skills/paperread-surface-learning/experience/unrecognized_surface_terms.jsonl`
- `agents/Agent/skills/paperread-surface-learning/experience/unrecognized_surface_terms.md`

The script reads:

- `*_surface_relations.jsonl`
- optional `*_table.csv`

It records terms that are present in the extraction but are not clearly mapped
to the currently supported modeling keywords or workflows.

### Export A Manual Term

Use this when the researcher sees an unfamiliar paper term directly:

```bash
python scripts/export_surface_experience.py add-term \
  --term "exsolved nanoparticle" \
  --category "surface modifier" \
  --context "Appears in a catalyst paper but is not mapped to a workflow yet." \
  --suggested-action "Decide whether this maps to cluster generation or a new exsolution workflow."
```

## Review Policy

- Treat every exported term as a candidate, not ground truth.
- Keep the original source path and context whenever possible.
- Do not immediately add a new modeling rule from one occurrence.
- Promote a term into `paperread/surface` prompt/schema or `surface-modeling`
  only after it appears in multiple papers or is important to the current project.

## Current Supported Modeling Task Names

The learning script recognizes these task names as already supported or planned:

- `vacancy_landscape`
- `adsorbate_landscape`
- `surface_cluster_builder`
- `single_atom_site`
- `doped_surface`
- `surface_functionalization`
- `slab_generation`

Terms that suggest something outside these tasks should be exported as
experience for later review.
