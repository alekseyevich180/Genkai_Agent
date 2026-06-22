---
name: mattergen-generation
description: Generate inorganic crystal structures with MatterGen, supporting unconditional sampling, property-conditioned generation, and sampling from custom trained or finetuned checkpoints.
tags: [MatterGen, crystal generation, inverse design]
tools: [run_bash]
dependent_skills: []
---
# MatterGen Skill

Use this skill to generate inorganic crystal structures with MatterGen through the official CLI. Prefer direct shell commands.


## Available Pre-trained Checkpoints

Common upstream checkpoint names include:
- `mattergen_base`
- `mp_20_base`
- `chemical_system` with `--properties-to-condition-on "{'chemical_system': 'Li-O'}"`
- `space_group` with `--properties-to-condition-on "{'space_group': 62}"`
- `dft_mag_density` with `--properties-to-condition-on "{'dft_mag_density': 0.5}"`
- `dft_band_gap` with `--properties-to-condition-on "{'dft_band_gap': 1.5}"`
- `ml_bulk_modulus` with `--properties-to-condition-on "{'ml_bulk_modulus': 120.0}"`
- `dft_mag_density_hhi_score` with `--properties-to-condition-on "{'dft_mag_density': 0.5, 'hhi_score': 2000.0}"`
- `chemical_system_energy_above_hull` with `--properties-to-condition-on "{'chemical_system': 'Li-O', 'energy_above_hull': 0.05}"`



## Generation on local

Invocation note:
- For local execution, it is fine to use an explicit environment-prefixed path such as `"${MATTERGEN_ENV}/bin/mattergen-generate"` when you need to pin the executable.
- For remote submission through `dpdisp`, use the CLI name directly in the task command, such as `mattergen-generate`, `mattergen-evaluate`, `mattergen-finetune`, or `mattergen-train`. Do not prepend `${MATTERGEN_ENV}/bin/` or any local environment path, because the command should resolve inside the remote runtime environment.

Parameter rule:
- If `--pretrained-name mattergen_base` is used, `--properties-to-condition-on` is optional and generation can be unconditional.
- If any other pre-trained checkpoint is used, `--properties-to-condition-on` must be provided and should match the property or properties expected by that checkpoint.
- If you want to sample from a model trained or finetuned by yourself, replace `--pretrained-name ...` with `--model_path /abs/path/to/model_dir`, following the official README.

### Unconditional generation

```bash
ts=$(date +"%Y%m%d%H%M%S")
outdir="mattergen/${ts}.mattergen_generate"
"${MATTERGEN_ENV}/bin/mattergen-generate" "$outdir" \
  --pretrained-name mattergen_base \
  --batch_size=16 \
  --num_batches=1
```

### Property or Multi-property conditioned generation

```bash
ts=$(date +"%Y%m%d%H%M%S")
outdir="/tmp/mattergen/${ts}.mattergen_generate"
"${MATTERGEN_ENV}/bin/mattergen-generate" "$outdir" \
  --pretrained-name chemical_system_energy_above_hull \
  --batch_size=16 \
  --num_batches=1 \
  --properties_to_condition_on="{'energy_above_hull': 0.05, 'chemical_system': 'Li-O'}" \
  --diffusion_guidance_factor=2.0
```

### Generation from a local trained or finetuned model

Use `--model_path` when sampling from a model you trained or finetuned yourself.

Example for property-conditioned generation:

```bash
ts=$(date +"%Y%m%d%H%M%S")
outdir="/tmp/mattergen/${ts}.mattergen_generate"
"${MATTERGEN_ENV}/bin/mattergen-generate" "$outdir" \
  --model_path /abs/path/to/model_dir \
  --batch_size=16 \
  --num_batches=1 \
  --properties_to_condition_on="{'dft_band_gap': 1.5}" \
  --diffusion_guidance_factor=2.0
```

Report at minimum:
- The generated `extxyz` path
- The exact output directory





## Generation on Bohrium

When submitting MatterGen jobs to Bohrium through `dpdisp`, Bohrium-specific submission settings, including authentication, project, image, and machine type, can be read from environment variables such as 'BOHRIUM_MAT_IMAGE' and 'BOHRIUM_MAT_MACHINE'. For the `dpdisp` submission procedure, refer to the `dpdisp` skill documentation.

-  When using Bohrium, `forward_files` should include the pretrained model directory. The local pretrained model path can be obtained from the environment variable `mattergen_model`, with one folder per pretrained model name, such as `mattergen_base`. Users can also specify the model path.
- `backward_files` should include the generated result path so outputs are retrieved, for example the generation output directory.


Prepare a writable local job directory first:

```bash
ts=$(date +"%Y%m%d%H%M%S")
outdir="matg/${ts}.mattergen_generate"
mkdir -p "$outdir"
cd "$outdir"
```

Then copy the pretrained MatterGen model directory into `"$outdir"`.

In `submission.json`:

- set `forward_files` to the model directory name inside `"$outdir"`, for example `mattergen_base`
- set `backward_files` to the generation output directory, for example `results`
- set `command` to a generation command such as:

```bash
mattergen-generate results/ \
  --model_path=model \
  --batch_size=16 \
  --num_batches=1 \
  --properties_to_condition_on="{'dft_band_gap': 1.5}" \
  --diffusion_guidance_factor=2.0
```

`--model_path` must point to the actual model location available inside the submitted job, so after copying the checkpoint into `"$outdir"` it should usually be a relative path such as `mattergen_base`.




### Expected Outputs

When running generation on Bohrium, make sure `backward_files` includes the generated result directory from the command line, for example the timestamped output directory created as `${outdir}`.
