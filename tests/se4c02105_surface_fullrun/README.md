# se4c02105 full no-calculation workflow test

Date: 2026-08-05

Input: `../se4c02105.pdf`

Paper: *Effect of the Chemical Structure of a Self-Assembled Monolayer on
the Gas-Sensing Behavior of SnO2 Nanowires*, ACS Sensors 2025, 10, 741-750,
DOI 10.1021/acssensors.4c02105.

## Execution boundary

- PDF ingestion, section routing, structured-output parsing, time-table
  generation, summary generation, experience collection, artifact
  initialization, PToModel mapping, surface-candidate preparation, mock DFT
  result registration, mock dataset preparation, and MLIP preflight were run.
- No VASP, MACE inference, DeepMD training, UMA fine-tuning, GPU/PJM job,
  relaxation, molecular dynamics, or scientific calculation was run.
- The repository mock label fixture was used only to exercise the downstream
  dataset and MLIP dry-run contracts.

## LLM boundary

The first online extraction attempt reached the configured provider but failed
with HTTP 410 `github_models_retirement_brownout`. GitHub Models was fully
retired on 2026-07-30, so the configured provider can no longer complete this
workflow.

To exercise all remaining code paths without changing provider credentials,
the extraction layer was rerun with deterministic mocked LLM responses grounded
in the PDF text. See `mocked_extraction_provenance.json`. These outputs must not
be represented as a successful live-provider extraction.

## Results

- Condition rows: 7
- Extracted material families: pristine, PAC12IMI-functionalized,
  PAC10CA-functionalized, and PAG3-functionalized SnO2 nanowires
- Recommended modeling tasks: `surface_functionalization`,
  `adsorbate_landscape`, and `slab_generation`
- PToModel executable task: `adsorbate_landscape`
- Prepared structure count: 0
- Manual/upstream requirements:
  - a real SnO2 surface structure;
  - molecular structure input;
  - a coverage-count decision.

All MACE, DeepMD, and UMA dry-run preflights returned `passed: true` with
expected warnings about mock/unvalidated inputs and missing external runtimes.
All three production preflights returned `passed: false`, confirming that the
mock artifacts cannot enter a production calculation or training route.

## Automatic modeling follow-up

The follow-up structure-generation test is recorded in
`automatic_modeling/README.md`. It generated a Materials Project-backed
SnO2(101) slab and six H2 adsorption candidates with the built-in mock
calculator. The test also showed that the current PToModel-to-modeling bridge
still requires an execution layer to resolve structure files and coverage
choices; it is not yet a completely automatic paper-to-structure executor.

## Integration finding

`extract_relations()` currently writes an indented multi-line JSON object to a
file named `.jsonl`, while artifact replay reads one JSON object per physical
line. Direct replay therefore failed with `JSONDecodeError`. The original file
is preserved as `se4c02105_conditions_input_surface_relations.jsonl`; the
semantically identical one-line recovery file
`se4c02105_conditions_input_surface_relations_compact.jsonl` was used to
continue the dry-run. No source-code fix was made during this test.
