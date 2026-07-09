---
name: paperread
description: Read surface-research PDFs or JSON records and extract structured reaction, material, and modeling information for downstream agent workflows.
metadata:
  tools:
    - run_skill_script
  dependent_skills:
    - ptomodel
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

This skill is the entrypoint for the local `paperread/surface` pipeline and
its reusable surface-paper experience loop:

```text
paper PDF or JSON text
-> paperread extraction
-> table / time / relations / summary / ptomodel json
-> optional experience collection
-> unknown-term export / parameter registry update
-> downstream ptomodel / surface-modeling or later skill updates
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
- `*_ptomodel.json`

Optional intermediate outputs:

- `*_text.txt`
- `*_sections.json`
- `*_conditions_input.json`
- `*_relations_input.json`
- `*_raw.csv`

Use `--keep-intermediate` when debugging extraction quality.
Use `--save-raw` when raw condition rows are needed.

The pipeline now also writes `*_ptomodel.json`, but the preferred downstream
entrypoint for this bridge step is the separate `ptomodel` skill.

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

### Export Unknown Terms

Use this when extraction finds unfamiliar surface-research terms, unsupported
modeling cues, or concepts that cannot yet be mapped to a supported workflow.

```bash
python scripts/paperread_tools.py export-unknown-terms \
  --relations ./paperread_output/paper_surface_relations.jsonl \
  --table ./paperread_output/paper_table.csv
```

Default outputs:

- `agents/Agent/skills/paperread/experience/unrecognized_surface_terms.jsonl`
- `agents/Agent/skills/paperread/experience/unrecognized_surface_terms.md`

### Add A Manual Term

Use this when the researcher sees an unfamiliar paper term directly:

```bash
python scripts/paperread_tools.py add-term \
  --term "exsolved nanoparticle" \
  --category "surface modifier" \
  --context "Appears in a catalyst paper but is not mapped to a workflow yet." \
  --suggested-action "Decide whether this maps to cluster generation or a new exsolution workflow."
```

### Build Parameter Registry

Build the reusable surface vocabulary from material-class experience:

```bash
python scripts/paperread_tools.py build-parameter-registry
```

Default outputs:

- `agents/Agent/skills/paperread/experience/surface_parameter_registry.json`
- `agents/Agent/skills/paperread/experience/surface_parameter_registry.md`

## Recommended Usage Policy

- Use `surface-pipeline` as the default paperread entrypoint.
- Read `*_summary.txt` first for a quick modeling-oriented overview.
- Read `*_surface_relations.jsonl` when the task needs structured entities,
  surfaces, facets, adsorbates, defects, single atoms, clusters, or suggested
  modeling tasks.
- Read `*_ptomodel.json` when the task should directly continue into
  `surface-modeling` rather than stopping at literature extraction.
- Read `*_table.csv` when the task needs preparation or reaction conditions.
- If paperread extracts unfamiliar terms or unsupported modeling cues, use
  `export-unknown-terms` or `add-term` inside this skill.
- If the extracted paper clearly maps to a supported modeling workflow, follow
  with `surface-modeling`.

## Knowledge Loop Policy

This skill must participate in the Agent knowledge loop:

```text
paper PDF / JSON
-> structured extraction
-> experience collection
-> material-class keyword statistics
-> parameter registry
-> ptomodel / surface-modeling reuse
-> repeated evidence promoted into durable knowledge
```

Before reading a new batch of papers, prefer existing reusable knowledge over
starting from a blank prompt:

- Check `paperread/surface/experience/material_classes/*.json` for known
  material classes, active sites, adsorbates, dopants, defects, reactions, and
  modeling keywords.
- Check `agents/Agent/skills/paperread/experience/surface_parameter_registry.json`
  for vocabulary that should guide extraction.
- Use `agent knowledge stats` when the user wants to inspect the graph state
  before a large paper-reading run.

During extraction, preserve structured evidence that can be reused later:

- Keep `*_surface_relations.jsonl` as the main entity and relation record.
- Keep `*_table.csv` for preparation, reaction, amount, and condition evidence.
- Keep `*_ptomodel.json` for downstream task mapping.
- Use `--collect-experience` whenever the output should improve future
  paper-reading or modeling.

After extraction, do not treat the paper summary as the final knowledge store.
Run experience collection so repeated terms become statistics:

- Collect material identity, element composition, material class, surface,
  facet, termination, defect, dopant, active site, adsorbate, coverage,
  cluster, single atom, modifier, reaction, and modeling task keywords.
- Store only compact source/context examples; the goal is keyword statistics
  and reusable parameter cues, not a long source list.
- Send unfamiliar or unmapped terms to this skill's unknown-term experience
  store with `export-unknown-terms` or `add-term`.

Class-specific reuse rules:

- Treat mineral or structure-prototype names as crystal-structure cues, not
  generic material names. Reuse the surface crystal-structure dictionary for
  terms such as rutile, anatase, brookite, spinel, normal spinel, inverse
  spinel, perovskite, fluorite, wurtzite, rocksalt, pyrochlore, delafossite,
  brucite, and corundum. These terms often imply crystal system, likely space
  group family, and which facet notation may be meaningful.
- Treat repeated composite material names, variable compositions, and adsorbed
  intermediate formulae through the surface material vocabulary before adding
  them to unknown terms. Examples include graphitic carbon nitride (`g-C3N4`),
  layered double hydroxides (`LDH`, `NiFe LDH`, `NiCo LDH/CC`), black
  phosphorus, BSCF-type perovskites, `NixPy`, single-atom/support shorthand,
  electrolyte concentrations, and adsorbed species notation such as `*OH`,
  `*O`, `*OOH`, `Hads`, and `OHads`.
- `supported_catalysts`: track support, loaded species, loading amount,
  nanoparticle or cluster identity, and exposed support facet.
- `carbon_materials`: track 2D carbon host, doped element, N/O/S coordination,
  vacancy or defect motif, and single-atom center.
- `metals_alloys`: track alloy elements, high-entropy composition, element
  ratios, and exposed crystal face.
- `oxides`: track oxide formula, polymorph, space group, surface facet,
  termination, oxygen vacancy, and dopant.
- `perovskites_spinels`: track A/B-site species, substitution, oxygen vacancy,
  space group, and exposed facet.

When enough repeated evidence exists, use the Agent graph commands to turn
working memory into durable knowledge:

- `agent knowledge seed` after skill or guide updates.
- `agent knowledge distill --min-evidence 3` after repeated successful
  extraction patterns appear.
- `agent knowledge migrate` only when old memory stores need to be unified into
  `know_do_graph.db`.
