# Quantum ESPRESSO + LOBSTER

## Scope

Use this path when the user already has the QE-side outputs needed by their
LOBSTER installation and wants the skill to stage a reproducible LOBSTER run
directory.

As of July 6, 2026, this repository does not hardcode one QE export layout into
the script. The skill therefore uses an explicit file manifest, which is safer
than guessing the exact `.save` or post-processing file layout used in a given
environment.

## Workflow

```text
run QE with the export/projection settings required by your LOBSTER build
-> collect the produced files in one source directory
-> write a file-manifest JSON mapping staged names to source files
-> stage the LOBSTER directory with prepare_input_qe
-> run LOBSTER
-> inspect lobsterout / ICOHPLIST.lobster
```

## Commands

Generate a manifest template:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="write_file_manifest --code qe --output ./qe_lobster_manifest.json"
)
```

Example basis file:

```json
{
  "Ir": "5d 6s 6p",
  "O": "2s 2p"
}
```

Stage the run:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="prepare_input_qe --source_dir ./qe_lobster_exports --species 'Ir O' --basis-file ./basis.json --manifest-file ./qe_lobster_manifest.json"
)
```

## File-manifest contract

The manifest is a JSON/YAML object:

```json
{
  "lobster_projection_data": "prefix.save",
  "structure_file": "pwscf.in",
  "main_output": "pwscf.out"
}
```

Rules:

- keys are filenames inside the staged LOBSTER work directory
- values are relative filenames under `--source_dir`
- edit the template to match the actual files produced in your QE workflow

## Notes

- The skill generates `lobsterin` deterministically from the species list and
  basis mapping.
- The skill does not generate QE input files by itself.
- If your environment later settles on a fixed QE-to-LOBSTER export layout, the
  script can be upgraded to validate that layout directly.
