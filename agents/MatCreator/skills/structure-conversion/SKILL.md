---
name: structure-conversion
description: Convert crystal structure files between extxyz and CIF, including splitting multi-frame extxyz into per-frame CIF files.
metadata:
  tools:
    - run_python_file
  tags:
    - structure
    - conversion
    - extxyz
    - cif
    - ASE
---

## Overview

Use the CLI script `structure_conversion_tools.py` (located alongside this file) to convert structure files between `extxyz` and `cif`. It mirrors the behavior of the former `ase_structure_convert_tool` and is especially useful for turning MatterGen multi-frame `extxyz` outputs into per-frame `cif` files.

Every command writes a JSON object to stdout and exits **0** on success or **1** on error. Always parse the JSON output and confirm `"status": "success"`.

```bash
python skills/structure_conversion/structure_conversion_tools.py convert <input_file> <output_path> [options]
```

## Supported Conversions

- `cif` -> `extxyz`
- single-frame `extxyz` or `xyz` -> single `cif`
- multi-frame `extxyz` or `xyz` -> directory of per-frame `cif` files
- `extxyz` or `xyz` -> `extxyz`

For multi-frame `extxyz` input, never collapse all frames into one `cif`. Write one `cif` file per frame using stable names such as `frame_000001.cif`.

## Command

### `convert`

Convert a structure file and return output metadata.

**Positional arguments**
| Argument | Description |
|---|---|
| `input_file` | Source structure path. Supported: `.extxyz`, `.xyz`, `.cif` |
| `output_path` | Output file path or output directory |

**Optional arguments**
| Flag | Type | Description |
|---|---|---|
| `--output-format` | str | Explicit target format: `cif` or `extxyz`. If omitted, infer from `output_path` |

**JSON response fields**
```
status, message, output_mode, output_format, frame_count, output_path, output_paths
```

## Recommended Behavior

- Prefer directory outputs when converting multi-frame `extxyz` to `cif`
- Always return absolute paths
- Report the output mode, frame count, output directory or file, and all generated paths
- Surface exact parsing or conversion errors from ASE

## Examples

```bash
# Multi-frame extxyz to per-frame CIF directory
python skills/structure_conversion/structure_conversion_tools.py convert \
    generated.extxyz converted_cifs --output-format cif

# Single CIF to extxyz
python skills/structure_conversion/structure_conversion_tools.py convert \
    structure.cif structure.extxyz
```

## Notes

- This skill is commonly used after `mattergen` generation and before downstream property prediction
- If `output_format` is omitted, the script infers it from `output_path`
- If the input contains multiple frames and the target is `cif`, the result is a directory, not a single file
