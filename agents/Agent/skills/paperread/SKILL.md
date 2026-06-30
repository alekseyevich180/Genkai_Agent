---
name: paperread
description: Read surface-research PDFs or JSON records and extract structured reaction, material, and modeling information for downstream agent workflows.
metadata:
  tools:
    - run_skill_script
  dependent_skills:
    - paperread-surface-learning
    - surface-modeling
  tags:
    - paperread
    - pdf
    - extraction
    - surface
    - literature
---

# Paperread

Use this skill when the task starts from a paper PDF or a prepared JSON text
record and the agent needs structured outputs instead of a free-form summary.

This skill is the entrypoint for the local `paperread/surface` pipeline:

```text
paper PDF or JSON text
-> paperread extraction
-> table / time / relations / summary
-> optional experience collection
-> downstream surface-modeling or later skill updates
```

## Script

Script:

```text
scripts/paperread_tools.py
```

Run it with `run_skill_script`:

```text
run_skill_script(
  skill_name="paperread",
  script_name="paperread_tools.py",
  args="surface-pipeline --input /abs/path/to/paper.pdf --output-dir ./paperread_output --collect-experience"
)
```

## Main Commands

### Surface Pipeline

Default command for a surface-material reaction paper:

```bash
python scripts/paperread_tools.py surface-pipeline \
  --input /abs/path/to/paper.pdf \
  --output-dir ./paperread_output \
  --collect-experience
```

Supported input:

- PDF paper
- JSON file containing paper text records

Main outputs:

- `*_table.csv`
- `*_time.csv`
- `*_surface_relations.jsonl`
- `*_summary.txt`

Optional intermediate outputs:

- `*_text.txt`
- `*_sections.json`
- `*_conditions_input.json`
- `*_relations_input.json`
- `*_raw.csv`

Use `--keep-intermediate` when debugging extraction quality.
Use `--save-raw` when raw condition rows are needed.

### Collect Experience From Existing Outputs

```bash
python scripts/paperread_tools.py collect-experience \
  --relations ./paperread_output/paper_surface_relations.jsonl \
  --table ./paperread_output/paper_table.csv \
  --write-run-file \
  --write-markdown
```

Use this when extraction has already run and you only want to accumulate
useful or unfamiliar material/modeling information for later review.

### Initialize Experience Store

```bash
python scripts/paperread_tools.py init-material-classes \
  --output-dir paperread/surface/experience
```

## Recommended Usage Policy

- Use `surface-pipeline` as the default paperread entrypoint.
- Read `*_summary.txt` first for a quick modeling-oriented overview.
- Read `*_surface_relations.jsonl` when the task needs structured entities,
  surfaces, facets, adsorbates, defects, single atoms, clusters, or suggested
  modeling tasks.
- Read `*_table.csv` when the task needs preparation or reaction conditions.
- If paperread extracts unfamiliar terms or unsupported modeling cues, follow
  with the `paperread-surface-learning` skill.
- If the extracted paper clearly maps to a supported modeling workflow, follow
  with `surface-modeling`.
