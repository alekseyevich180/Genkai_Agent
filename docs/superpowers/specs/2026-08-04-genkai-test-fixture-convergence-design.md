# Genkai Test and Fixture Convergence Design

## Goal

Complete Task14 by making test tiers explicit and separating compatibility and
large paper/generated fixtures from ordinary unit tests.

## Test tiers

- `tests/contracts/`: artifact and manifest contracts.
- `tests/architecture/`: import and ownership gates.
- `tests/modeling/`, `tests/literature/`, `tests/mlip/`: focused unit tests.
- `tests/integrations/`, `tests/workflow/`: offline multi-component tests.
- `tests/compatibility/`: legacy Skill/script-path and characterization tests.
- `tests/external/`: reserved tests requiring external runtimes; collection is
  opt-in and no external tests run in the default offline suite.

Register markers `unit`, `contract`, `integration`, `compatibility`, and
`external`; tests declare their tier through module-level markers. The default
pytest command excludes `external` using `addopts`, while explicit external
selection remains possible.

## Fixtures

Keep small deterministic fixtures under `tests/fixtures/`. Move paper PDFs and
large generated experience directories into `tests/fixtures/archives/` and add
`tests/fixtures/README.md` with source, license/provenance, intended consumer,
and offline/network policy. Tests must refer to fixture paths through a shared
`tests/fixtures/paths.py` helper rather than duplicating absolute paths.

## Compatibility

Move root-level `test_paperread_surface.py` and `test_surface_mp_workflow.py`
to `tests/compatibility/`, updating only their project-root calculation. Their
legacy path loading and mock behavior remain unchanged.

## Verification

Run marker collection, focused unit/contract/integration/compatibility tests,
and a default offline suite. Confirm `pytest -m external` collects only the
reserved external tier and is not executed.
