# Automatic modeling test

Date: 2026-08-05

This directory tests structure generation after the paperread and PToModel
stages. It does not contain a scientific energy calculation or relaxed model.

## Inputs resolved from the paper workflow

- Material: rutile SnO2
- Surface hypothesis: SnO2 (101)
- Adsorbate selected by the current PToModel ordering: H2
- Adsorption-site element: Sn
- Test coverage counts: 1 and 2 molecules

The paper reports a 0.26 nm lattice spacing corresponding to the (101) plane.
Treating this observation as an exposed (101) surface is a modeling hypothesis,
not a surface assignment established by the paper.

## Slab generation

The Materials Project-backed slab builder selected stable entry `mp-856`
(rutile, `P4_2/mnm`, zero energy above hull), then constructed the explicitly
requested (101) slab.

- Slab atoms: 120 (`Sn40O80`)
- Candidate terminations: 2
- Selected termination: symmetric termination index 1
- Slab/vacuum settings: 12 A minimum slab, 15 A requested vacuum, 2x2 repeat
- Measured periodic vacuum gap: 20.488477 A
- API key persisted: no

See `sno2_101/surface_manifest.json` for provenance and checks.

## Adsorbate landscape

The adsorbate workflow used:

- 2 detected top-layer Sn sites;
- 8 single-adsorbate placement trials;
- coverage counts 1 and 2;
- uniform, clustered, and random patterns;
- `calculator=none` and `max_steps=0`.

Six candidate CIF files were generated. All are ASE-readable. Single-H2
candidates contain 122 atoms, double-H2 candidates contain 124 atoms, and the
minimum adsorbate-surface distance is approximately 2.985 A.

Values in `adsorbate_coverage_landscape.csv` come from the built-in mock test
calculator. They are useful only for testing ranking and file generation and
must not be interpreted as adsorption energies. Consequently,
`workflow_test_best_candidate.cif` is a workflow-test candidate, not a stable
structure.

## Automation gaps found

1. `build_surface_candidates()` prepares `candidates.json` but does not invoke
   the modeling algorithms; an execution layer still has to resolve and run the
   commands.
2. PToModel leaves the surface structure, molecular structure, and coverage
   count unresolved. This test supplied them using Materials Project, ASE H2,
   and a minimal 1/2 coverage heuristic.
3. The paper's main selective pair is PAC12IMI-acetone, but the current task
   input ordering selects H2 as the first adsorbate. Pair-specific prioritization
   is not yet represented in the automatic executor.
4. `surface_functionalization` is recommended but deferred because it has no
   active executable implementation in the current surface-modeling task set.
   Therefore, no PAC12IMI/PAC10CA/PAG3 monolayer was constructed.

No VASP, MLIP, DFT, relaxation, GPU/PJM, training, or molecular dynamics task
was started.
