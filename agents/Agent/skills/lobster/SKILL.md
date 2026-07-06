---
name: lobster
description: Prepare, stage, and summarize LOBSTER bonding-analysis calculations from completed VASP, CP2K, or Quantum ESPRESSO outputs.
metadata:
  tools:
    - run_skill_script
    - load_skill_resource
  dependent_skills:
    - vasp
    - bohrium
    - dpdisp
  tags:
    - lobster
    - cohp
    - icohp
    - cobi
    - coop
    - bonding-analysis
    - vasp
---

# LOBSTER Skill

Use this skill when the user needs LOBSTER bonding analysis such as
COHP/ICOHP/COOP/COBI from an upstream electronic-structure calculation.

This repository now provides three executable staging paths:

- VASP -> LOBSTER
- CP2K -> LOBSTER
- Quantum ESPRESSO -> LOBSTER

The VASP path includes an INCAR template writer based on the local project
inputs you provided. The CP2K and QE paths use explicit file manifests instead
of hardcoded filename guesses.

The default VASP flow is:

```text
structure
-> vasp prepare_scf
-> run VASP SCF with WAVECAR/CHGCAR saved
-> lobster prepare_input
-> submit the LOBSTER directory
-> lobster read_results / collect_results
```

## Workflow selection

- For VASP production usage, read:
  `load_skill_resource(skill_name="lobster", path="references/vasp.md")`
- For CP2K compatibility guidance, read:
  `load_skill_resource(skill_name="lobster", path="references/cp2k.md")`
- For Quantum ESPRESSO compatibility guidance, read:
  `load_skill_resource(skill_name="lobster", path="references/quantum-espresso.md")`

All three paths are now staged through `lobster_tools.py`.

## Mandatory VASP workflow sequence

1. Run a converged VASP SCF first.
2. Ensure the VASP run kept the files needed by LOBSTER:
   - `POSCAR`
   - `POTCAR`
   - `INCAR`
   - `KPOINTS`
   - `WAVECAR`
   - `CHGCAR`
3. Use `prepare_input` to stage one LOBSTER job directory.
4. Run LOBSTER in that directory on the target machine.
5. Use `read_results` or `collect_results` after the job finishes.

## VASP prerequisites

For the upstream SCF, the local project references indicate this pattern:

- `ISPIN = 1`
- `ENCUT = 400-500`
- `ALGO = Normal`
- `EDIFF = 1E-5`
- `NELM = 300-1000`
- `ISMEAR = 1` or `-5`
- `SIGMA = 0.05`
- `IBRION = -1`
- `NSW = 0`
- `ISIF = 2`
- `NPAR = 5-10`
- `LREAL = Auto`
- `NSIM = 1`
- `LPLANE = .TRUE.`
- `IVDW = 12` when that dispersion model is part of the project workflow
- `ISYM = -1`
- `LWAVE = .TRUE.`
- `LCHARG = .FALSE.` or `.TRUE.` depending on whether CHGCAR is needed later
- sufficiently large `NBANDS`

Do not start from a relaxation directory unless it also contains a valid final
static wavefunction for LOBSTER.

To generate a starter INCAR in the same style:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="write_vasp_incar --nbands 346 --output ./INCAR"
)
```

## Script

Run the bundled script with `run_skill_script`:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="prepare_input --scf_dir ./vasp/scf_001 --basis-functions '{\"Fe\": \"3d 4s 4p\", \"O\": \"2s 2p\"}'"
)
```

Every command prints JSON to stdout and exits 0 on success, 1 on error.

## Commands

### prepare_input

Stage a LOBSTER calculation directory from a completed VASP SCF directory.

```bash
python lobster_tools.py prepare_input \
  --scf_dir ./vasp/scf_001 \
  --basis-functions '{"Fe": "3d 4s 4p", "O": "2s 2p"}' \
  [--basis-set pbeVaspFit2015] \
  [--task standard] \
  [--copy-files]
```

Notes:

- `--scf_dir` must point to the finished VASP SCF directory.
- `--basis-functions` is a JSON object mapping each POSCAR species to one
  LOBSTER basis string.
- `--copy-files` copies the VASP files. By default the tool creates symlinks,
  which is safer for large `WAVECAR` files.
- The generated `lobsterin` is intentionally minimal and explicit.

### write_basis_template

Generate a JSON template listing all species from `POSCAR`.

```bash
python lobster_tools.py write_basis_template \
  --scf_dir ./vasp/scf_001
```

Use this when the species list is known but the basis mapping still needs to be
 filled in.

### write_file_manifest

Generate a starter file-manifest JSON for CP2K or QE.

```bash
python lobster_tools.py write_file_manifest \
  --code cp2k \
  --output ./cp2k_lobster_manifest.json
```

```bash
python lobster_tools.py write_file_manifest \
  --code qe \
  --output ./qe_lobster_manifest.json
```

The values in the generated file are placeholders. Replace them with the actual
relative file paths produced by your environment.

### write_vasp_incar

Write a VASP static `INCAR` template intended for LOBSTER runs.

```bash
python lobster_tools.py write_vasp_incar \
  --nbands 346 \
  [--encut 500] \
  [--nelm 1000] \
  [--ismear -5] \
  [--npar 5] \
  [--lcharg] \
  [--output ./INCAR]
```

Use this when the user wants the VASP side of the LOBSTER workflow written in
the same skill-oriented style as the other calculation skills.

### prepare_input_cp2k

Stage a LOBSTER directory from prepared CP2K outputs.

```bash
python lobster_tools.py prepare_input_cp2k \
  --source_dir ./cp2k_lobster_exports \
  --species "Ir O" \
  --basis-file ./basis.json \
  --manifest-file ./cp2k_lobster_manifest.json
```

Requirements:

- `--species` or `--species-file`
- `--basis-functions` or `--basis-file`
- `--file-manifest` or `--manifest-file`

### prepare_input_qe

Stage a LOBSTER directory from prepared Quantum ESPRESSO outputs.

```bash
python lobster_tools.py prepare_input_qe \
  --source_dir ./qe_lobster_exports \
  --species "Ir O" \
  --basis-file ./basis.json \
  --manifest-file ./qe_lobster_manifest.json
```

Requirements:

- `--species` or `--species-file`
- `--basis-functions` or `--basis-file`
- `--file-manifest` or `--manifest-file`

### read_results

Read one finished LOBSTER directory and return a compact JSON summary.

```bash
python lobster_tools.py read_results \
  --calc_dir ./lobster/lobster_scf_001_20260706120000
```

Returned fields include:

- `charge_spilling_percent`
- `total_spilling_percent`
- `basis_functions`
- `bond_count`
- `most_bonding_pair`

If `ICOHPLIST.lobster` exists, the strongest bonding interaction is identified
from the most negative ICOHP value.

### collect_results

Read several finished LOBSTER directories and aggregate them.

```bash
python lobster_tools.py collect_results \
  --dirs ./lobster/job_001 ./lobster/job_002
```

## Knowledge Loop Policy

This skill should also use the Agent knowledge loop. LOBSTER runs often expose
reusable project-specific choices, especially basis functions, upstream SCF
requirements, bonding descriptors, and failure modes.

The intended loop is:

```text
completed VASP / CP2K / QE calculation
-> LOBSTER staging
-> lobsterin, basis, manifest, and output summary
-> bonding-analysis result or failure warning
-> reusable workflow memory
-> durable skill knowledge after repeated evidence
```

Before staging a LOBSTER job:

- Search existing skill knowledge for the target code path, element basis
  functions, SCF file requirements, and prior LOBSTER warnings.
- Reuse known basis-function mappings for the same element and pseudopotential
  family when they are available.
- Confirm upstream SCF outputs include the files required by the selected code
  path before generating `lobsterin`.

During staging and result reading, preserve compact structured evidence:

- Upstream code, source directory, species list, basis functions, basis set,
  task type, and generated `lobsterin` options.
- Required upstream files that were present or missing.
- `charge_spilling_percent`, `total_spilling_percent`, `bond_count`, and
  `most_bonding_pair` from `read_results`.
- Strong ICOHP/COHP/COBI/COOP patterns that are relevant to the material or
  reaction being studied.
- Failure mode, such as missing wavefunction, incompatible projection data,
  high spilling, wrong species order, or incomplete `ICOHPLIST.lobster`.

After result collection:

- Treat a successful element/basis/workflow combination as a reusable memory
  candidate.
- Treat repeated high spilling or missing-file errors as warnings that should
  be promoted after enough evidence.
- Use `agent knowledge distill --min-evidence 3` when the same basis mapping,
  SCF prerequisite, or failure warning appears across several jobs.
- Use `agent knowledge seed` after updating this skill or any LOBSTER reference
  guide so the graph can retrieve the new workflow knowledge.

## Other codes

- CP2K executable workflow details are in `references/cp2k.md`
- Quantum ESPRESSO executable workflow details are in `references/quantum-espresso.md`

## Submission

This skill only prepares and reads LOBSTER jobs. Submission can be handled with
the same cluster workflow used for VASP, for example via `bohrium` or `dpdisp`,
as long as the remote environment has a working `lobster` executable.

## Config

`config.yaml` controls the default work directory:

```yaml
work_dir: lobster
```
