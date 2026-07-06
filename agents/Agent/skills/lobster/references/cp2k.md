# CP2K + LOBSTER

## Scope

Use this path when the user already has the CP2K-side outputs needed by their
LOBSTER installation and wants the skill to stage a reproducible LOBSTER run
directory.

As of July 6, 2026, this repository does not try to infer CP2K-specific LOBSTER
interface files automatically. Instead, the skill uses an explicit file
manifest. This is intentional because the exact exported file names and layout
can differ across environments.

## Workflow

```text
run CP2K with the projection/export settings required by your LOBSTER build
-> collect the produced files in one source directory
-> write a file-manifest JSON mapping staged names to source files
-> stage the LOBSTER directory with prepare_input_cp2k
-> run LOBSTER
-> inspect lobsterout / ICOHPLIST.lobster
```

## Commands

Generate a manifest template:

```text
run_skill_script(
  skill_name="lobster",
  script_name="lobster_tools.py",
  args="write_file_manifest --code cp2k --output ./cp2k_lobster_manifest.json"
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
  args="prepare_input_cp2k --source_dir ./cp2k_lobster_exports --species 'Ir O' --basis-file ./basis.json --manifest-file ./cp2k_lobster_manifest.json"
)
```

## File-manifest contract

The manifest is a JSON/YAML object:

```json
{
  "lobster_projection_data": "PROJECTION_DATA",
  "structure_file": "geometry.xyz",
  "main_output": "cp2k.out"
}
```

Rules:

- keys are filenames inside the staged LOBSTER work directory
- values are relative filenames under `--source_dir`
- edit the template to match the actual files produced in your CP2K workflow

## Notes

- The skill generates `lobsterin` deterministically from the species list and
  basis mapping.
- The skill does not generate CP2K input files by itself.
- If your environment standardizes CP2K export filenames later, the script can
  be tightened to validate those names directly.
