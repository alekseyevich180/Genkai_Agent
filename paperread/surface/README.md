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

- `*_text.txt`: raw text extracted from PDF when the input is a PDF
- `*_sections.json`: section split result when the input is a PDF
- `*_conditions_input.json`: condition-extraction input generated from PDF
- `*_relations_input.json`: relation-extraction input generated from PDF
- `*_raw.csv`: raw LLM responses for condition extraction
- `*_table.csv`: structured condition table
- `*_time.csv`: standardized time table
- `*_surface_relations.jsonl`: structured material/reaction relation output

## Scripts

- `ingest_pdf.py`
  - Extracts PDF text with `pdftotext`
  - Reads PDF metadata with `pdfinfo`
  - Splits paper text into sections and prepares condition/relation JSON inputs

- `run_surface_pipeline.py`
  - Unified entrypoint for surface-material reaction processing
  - Runs PDF ingestion when needed, then condition extraction, time standardization, and relation extraction

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
      surface/support, facet, active site, defect, dopant/modifier, loading

- `standardize_surface_time.py`
  - Input: CSV with `Index` and `Time`
  - Output: CSV with standardized time values
  - Use case: normalize annealing, reaction, adsorption, and cycling times.

- `extract_surface_relations.py`
  - Input: JSON records with `Title`/`title` and `Text`/`Procedure`/`Abstract`
  - Output: JSONL
  - Use case: extract materials, surfaces, facets, dopants, defects, adsorbates,
    properties, reaction parameters, material parameters, and their links from abstracts or discussion text.

## Example usage

```bash
python -m paperread.surface.run_surface_pipeline paper.json --output-dir paperread/surface/output
python -m paperread.surface.run_surface_pipeline paper.pdf --output-dir paperread/surface/output
python -m paperread.surface.extract_surface_conditions samples.json
python -m paperread.surface.standardize_surface_time input.csv output.csv
python -m paperread.surface.extract_surface_relations samples.json
```

## Recommended usage pattern

For papers focused on surface-material reactions:

1. Use `run_surface_pipeline.py` as the default entrypoint.
2. Read `*_table.csv` for reaction and material parameters.
3. Read `*_surface_relations.jsonl` for structured entities and links.
4. Use `standardize_surface_time.py` separately only if you already have a
   condition table and want to normalize time values again.

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
