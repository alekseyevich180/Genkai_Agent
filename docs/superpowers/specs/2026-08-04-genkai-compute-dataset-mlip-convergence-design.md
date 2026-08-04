# Genkai Compute, Dataset, and MLIP Convergence Design

## Goal

Close Task13 by making the existing compute, dataset, and MLIP library APIs the
single source of stable contracts while retaining Skill scripts as external
runtime and CLI entrypoints. No training, scheduler submission, GPU inference,
VASP execution, or online service access is part of this change.

## Ownership boundary

- `src/genkai/compute/vasp.py` owns VASP input/result artifact contracts and
  optional `dpdata` loading.
- `src/genkai/datasets/` owns ASE-readable label, geometry, split-inventory,
  leakage, and dataset artifact validation.
- `src/genkai/mlip/protocol.py` owns run modes, artifact integrity gates,
  training evidence gates, and launcher marker validation.
- `src/genkai/mlip/{mace,deepmd,uma}.py` owns role-specific command
  specifications and production/dry-run preflight.
- Skill scripts may parse legacy CLI arguments, prepare external runtime
  command lines, and submit only when explicitly invoked; they must not define
  a second dataset audit, artifact gate, or MLIP role contract.

## Contract registry

Add a small dependency-free registry under `src/genkai/mlip/launchers.py` with
the canonical launcher names, environment variables, required source markers,
and role names used by the three adapters. Adapters consume this registry;
tests use it to audit the shipped shell entrypoints. The registry validates
textual protocol ownership without importing torch, fairchem, DeepMD, MACE, or
UMA.

## Compatibility and safety

Existing public Python functions and Skill command flags remain unchanged.
Legacy data-preparation scripts continue to own format conversion, while their
validation paths call `genkai.datasets`. Library imports remain offline and
lazy for optional dependencies. The adapter layer produces command
specifications only and never submits PJM jobs.

## Verification

- TDD tests fail if a registry entry is missing, a launcher script drops a
  required marker, or a Skill validation script stops importing the canonical
  dataset audit.
- Existing compute/dataset/MLIP integration tests remain green.
- `--help` and `bash -n` checks run for all in-scope VASP/MACE/DeepMD/UMA
  entrypoints.
- Wheel build and extracted-wheel import checks remain offline.
- Full repository collection remains separately reported if the pre-existing
  `agent.tools.structure_builder` import blocker persists.
