# Surface Reaction Toolkit

This directory is a unified subproject for extracting information about
chemical reactions on surface materials. It combines:

- `ReactionSeek`-style experimental condition extraction
- `NERRE`-style material and relation extraction
- PDF ingestion and section routing for papers

The result is one workflow for surface-material chemistry rather than two
separate tools.

## Main workflow

Use `run_surface_pipeline.py` when the target is a surface-material reaction
paper and you want one pass that produces both tabular conditions and
structured relations. The input can be either JSON text records or a PDF file.

```bash
python -m paperread.surface.run_surface_pipeline \
  paperread/surface/examples/sample_surface_input.json \
  --output-dir paperread/surface/output
```

```bash
python -m paperread.surface.run_surface_pipeline \
  your_surface_paper.pdf \
  --output-dir paperread/surface/output
```

Outputs:

- `*_table.csv`: structured condition table
- `*_time.csv`: standardized time table
- `*_surface_relations.jsonl`: structured material/reaction relation output
- `*_summary.txt`: human-readable summary aligned with the extracted results
- `*_ptomodel.json`: filtered and normalized Agent-oriented bridge from paper key information to modeling inputs
- `material_classes/*.json`: material-class experience records when
  `--collect-experience` is enabled
- `agents/Agent/skills/paperread/experience/surface_parameter_registry.json`:
  reusable parameter vocabulary regenerated from the canonical material-class
  experience store

Optional outputs:

- `*_text.txt`, `*_sections.json`, `*_conditions_input.json`, `*_relations_input.json`
  - only when `--keep-intermediate` is enabled
- `*_raw.csv`
  - only when `--save-raw` is enabled

## Scripts

- `surface_ontology.py`
  - Shared task names, material-class rules, keyword buckets, and
    normalization vocabulary used by the surface pipeline and learning tools.

- `ingest_pdf.py`
  - Extracts PDF text with `pdftotext`
  - Reads PDF metadata with `pdfinfo`
  - Splits paper text into sections and prepares condition/relation JSON inputs

- `run_surface_pipeline.py`
  - Unified entrypoint for surface-material reaction processing
  - Runs PDF ingestion when needed, then condition extraction, time standardization, and relation extraction
  - Automatically generates `*_ptomodel.json` after the extraction stage
  - By default keeps only final outputs to avoid duplicate files
  - Can also collect paperread experience with `--collect-experience`

- `ptomodel.py`
  - Input:
    - `*_surface_relations.jsonl`
    - optional `*_table.csv`
    - optional `*_summary.txt`
    - optional `*_time.csv`
  - Output:
    - `*_ptomodel.json`
  - Use case: filter useful information and normalize equivalents such as facet
    indices, nanoparticle species, material classes, and reaction types so the
    Agent can use them as modeling inputs.

- `extract_surface_conditions.py`
  - Input: JSON records with `Title`/`title` and `Text`/`Procedure`/`Abstract`
  - Output:
    - `<prefix>_raw.csv`
    - `<prefix>_table.csv`
  - Use case: extract preparation and experimental conditions from methods-like text.
  - Extracted parameter groups:
    - Reaction parameters: reaction type, feed/concentration, atmosphere, pressure,
      gas flow, solvent, pH, temperature, time, potential/bias, current density,
      conversion, selectivity, yield, rate/activity, stability/cycles
    - Material parameters: composition, phase, morphology/size, surface area,
      surface/support, facet, surface termination, active site, defect,
      dopant/modifier, loading
    - Modeling-oriented keywords: surface/slab, adsorbate, adsorption site,
      coverage, oxygen vacancy, defect, cluster, single atom, modifier, and
      related phrases that can drive downstream structure generation

- `standardize_surface_time.py`
  - Input: CSV with `Index` and `Time`
  - Output: CSV with standardized time values
  - Use case: normalize annealing, reaction, adsorption, and cycling times.

- `extract_surface_relations.py`
  - Input: JSON records with `Title`/`title` and `Text`/`Procedure`/`Abstract`
  - Output: JSONL
  - Use case: extract materials, surfaces, facets, dopants, defects, adsorbates,
    properties, reaction parameters, material parameters, modeling keywords, and
    their links from abstracts or discussion text.
  - Additional modeling fields include:
    - `surface_terminations`
    - `slab_models`
    - `vacancy_models`
    - `adsorption_sites`
    - `coverage`
    - `clusters`
    - `single_atoms`
    - `modifiers`
    - `modeling_keywords`
    - `recommended_modeling_tasks`

Supported `recommended_modeling_tasks` values currently align with the Agent
surface-modeling direction:

- `vacancy_landscape`
- `adsorbate_landscape`
- `surface_cluster_builder`
- `single_atom_site`
- `doped_surface`
- `surface_functionalization`
- `slab_generation`

- `collect_experience.py`
  - Input: `*_surface_relations.jsonl` and/or `*_table.csv`
  - Output:
    - `material_classes/<material_class>.json`: default cumulative keyword
      inventory grouped by inorganic material type
    - `<stem>.json`: optional per-run aggregate only when `--write-run-file`
      is passed
    - `<stem>.md`: optional human-readable review report only when
      `--write-markdown` is passed
  - Use case: collect known useful information and unknown/unmapped extraction
    information by surface-research category so prompts, schema, planner rules,
    or Agent skills can be improved later without a bloated item-by-item log.
  - Research categories follow a NERRE/ReactionSeek-style target schema rather
    than extracting every text item:
    - `surface_materials`
    - `surface_structure`
    - `defects_active_sites`
    - `adsorption_reaction`
    - `clusters_single_atoms`
    - `modeling_tasks`
    - `unknown_information`
  - The default long-term experience store is organized by inorganic material
    type rather than by paper.
  - The material-class files emphasize keyword frequencies and descriptor
    buckets such as materials, surface/support, states, dopants/modifiers,
    active sites, adsorbates/reactants, coverage, clusters/single atoms, and
    reactions. They intentionally avoid long per-paper source lists.
  - The canonical experience store can be converted into a reusable parameter
    registry so later extractions can reuse previously learned material,
    loading, coordination, support, and reaction vocabulary.
  - Current inorganic material classes include:
    - `single_atom_catalysts`
    - `supported_catalysts`
    - `metals_alloys`
    - `oxides`
    - `hydroxides_oxyhydroxides`
    - `sulfides`
    - `selenides_tellurides`
    - `nitrides`
    - `carbides_mxenes`
    - `phosphides_phosphates`
    - `halides`
    - `carbon_materials`
    - `perovskites_spinels`
    - `zeolites_silicates`
    - `mofs_coordination_polymers`
    - `borides`
    - `defect_engineered_materials`
    - `surface_functionalized_materials`
    - `battery_electrode_materials`
    - `other_inorganic_materials`
  - Generic performance metrics, reaction parameters, and applications are not
    collected as experience unless they are already represented by the target
    surface/material/modeling fields.

## Example usage

```bash
python -m paperread.surface.run_surface_pipeline paper.json --output-dir paperread/surface/output
python -m paperread.surface.run_surface_pipeline paper.pdf --output-dir paperread/surface/output
python -m paperread.surface.run_surface_pipeline paper.pdf --output-dir paperread/surface/output --keep-intermediate --save-raw
python -m paperread.surface.run_surface_pipeline paper.pdf --output-dir paperread/surface/output --collect-experience
python -m paperread.surface.ptomodel --relations paper_surface_relations.jsonl --table paper_table.csv --summary paper_summary.txt --output-dir paperread/surface/output
python -m paperread.surface.extract_surface_conditions samples.json
python -m paperread.surface.standardize_surface_time input.csv output.csv
python -m paperread.surface.extract_surface_relations samples.json
python -m paperread.surface.collect_experience --relations paper_surface_relations.jsonl --table paper_table.csv
python -m paperread.surface.collect_experience --relations paper_surface_relations.jsonl --table paper_table.csv --write-run-file --write-markdown
python -m paperread.surface.collect_experience --init-material-classes --output-dir paperread/surface/experience
```

## Recommended usage pattern

For papers focused on surface-material reactions:

1. Use `run_surface_pipeline.py` as the default entrypoint.
2. Read `*_table.csv` for reaction and material parameters.
3. Read `*_surface_relations.jsonl` for structured entities and links.
4. Read `*_ptomodel.json` when the next step is Agent-side surface modeling
   rather than manual inspection.
5. Read the modeling keyword sections in `*_summary.txt` when you want a short
   human summary before opening the full plan.
6. Enable `--collect-experience` when you want to preserve useful and unknown
   extraction information for later prompt/schema/planner improvements.
7. Rebuild or inspect the reusable registry when you want later paperread runs
   to reuse learned parameter vocabulary:

```bash
python agents/Agent/skills/paperread/scripts/paperread_tools.py build-parameter-registry
```
8. Use `standardize_surface_time.py` separately only if you already have a
   condition table and want to normalize time values again.
9. Enable `--keep-intermediate` only when you need PDF text, section diagnostics,
   or generated JSON inputs for debugging.

For PDF input, the workflow is:

1. `pdftotext` extracts raw paper text
2. `pdfinfo` provides title metadata when available
3. `ingest_pdf.py` splits sections into:
   - method/experimental-oriented text for condition extraction
   - abstract/results/discussion-oriented text for relation extraction
4. `run_surface_pipeline.py` sends those two routed inputs into the existing extraction chain

## Input format

Both dict-style and list-style JSON are supported.

Dict-style example:

```json
{
  "doc1": {
    "Title": "CO oxidation on Pt/CeO2(111)",
    "Text": "Pt was deposited on CeO2(111) and reduced under H2 at 300 C for 2 h."
  }
}
```

List-style example:

```json
[
  {
    "title": "Methanol adsorption on TiO2",
    "abstract": "Methanol adsorption on rutile TiO2(110) was studied by ..."
  }
]
```
