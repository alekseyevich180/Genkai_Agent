---
name: mattergen-finetune
description: Finetune MatterGen models and produce a reusable finetuned checkpoint for downstream crystal generation.
tags: [MatterGen, training, finetuning]
tools: [run_bash]
dependent_skills: []
---
# MatterGen Skill

Use this skill to train or finetune MatterGen models through the official CLI. Prefer direct shell commands.

## Available Pre-trained Checkpoints

Common upstream checkpoint names include the following model-name to property-name mappings:
- `mattergen_base`
- `mp_20_base`
- `chemical_system` -> `chemical_system`
- `space_group` -> `space_group`
- `dft_mag_density` -> `dft_mag_density`
- `dft_band_gap` -> `dft_band_gap`
- `ml_bulk_modulus` -> `ml_bulk_modulus`
- `dft_mag_density_hhi_score` -> `dft_mag_density`, `hhi_score`
- `chemical_system_energy_above_hull` -> `chemical_system`, `energy_above_hull`




## Finetuning

The current MatCreator workflow supports:
- property finetuning through `mattergen-finetune`.

For local runs, MatterGen is installed in a virtual environment, so you should use ${MATTERGEN_ENV}/bin/mattergen-finetune. On Bohrium, use mattergen-finetune directly.

The official MatterGen README also documents:
- dataset preprocessing with `csv-to-dataset`
- single-property finetuning
- multi-property finetuning
- custom-property finetuning

Reference:
- Official README: https://github.com/microsoft/mattergen/blob/main/README.md


### Dataset preprocessing

MatterGen training expects a preprocessed dataset cache. The official README uses:

Cached dataset directory referenced by `data_module.root_dir`. In practice, this means the remote task must receive the cache contents needed for all splits used by MatterGen, including `train`, `val`, and `test`. Do not upload only the top-level command script while leaving the cache behind locally.

If you already have numbered CIF files and a CSV with `id,0,property`, first build MatterGen-ready CSV files with inline CIF contents:

```bash
python skills/mattergen/build_cif_property_csv.py \
  /abs/path/to/cif_dir \
  /abs/path/to/id_prop.csv \
  dft_band_gap \
  --split-dir /abs/path/to/my_csvs \
  --test-ratio 0.1 
```

The split step is expected to create three non-empty files:
- `train.csv`
- `val.csv`
- `test.csv`

If the dataset is too small, or the requested ratios would make any split empty, the script should fail instead of writing an empty split.

This writes:
- a full table such as `/abs/path/to/cif_dir/mattergen_property.csv`
- a split directory such as `/abs/path/to/my_csvs/`
- `/abs/path/to/my_csvs/train.csv`
- `/abs/path/to/my_csvs/val.csv`
- `/abs/path/to/my_csvs/test.csv`

Each split CSV contains: 
- `material_id`
- the requested property column 
- `cif`

Then transform csv file to cache for mattergen:
```bash
"${MATTERGEN_ENV}/bin/csv-to-dataset" \
  --csv-folder /abs/path/to/my_csvs \
  --dataset-name my_csvs \
  --cache-folder /abs/path/to/datasets/cache
```



## Property finetuning on local


In most cases, start from `mattergen_base` and finetune on the target property data. If the target property is already covered by an existing pretrained property model, you can also finetune from that pretrained property model. The local pretrained model path can be obtained from the environment variable `mattergen_model`, with one folder per pretrained model name, such as `mattergen_base`

For custom property finetuning, follow this workflow:

1. Build split CSVs from numbered CIF files and property labels.
2. Convert the split CSV folder into a MatterGen cache with `csv-to-dataset`.
3. If the property is truly new, add the property name to MatterGen's property registry and add a matching property-embedding config.
4. Run `mattergen-finetune` on the cached dataset.


If the target property is not one of the built-in MatterGen properties from the official README, also follow the official custom-property setup:
- add the property name to `PROPERTY_SOURCE_IDS` in MatterGen
- add the property column to the split CSVs before preprocessing
- re-run `csv-to-dataset`
- add a matching property embedding config under `mattergen/conf/lightning_module/diffusion_module/model/property_embeddings/`



### Multi-property finetuning

Example:

```bash
ts=$(date +"%Y%m%d%H%M%S")
outdir="mattergen/${ts}.mattergen_finetune"
mkdir -p "$outdir"
cd "$workdir"

"${MATTERGEN_ENV}/bin/mattergen-finetune" \
  adapter.model_path=/abs/path/mattergen_base \
  data_module=mp_20 \
  data_module.root_dir=/abs/path/to/datasets/cache/mp_20 \
  +lightning_module/diffusion_module/model/property_embeddings@adapter.adapter.property_embeddings_adapt.$PROPERTY1=$PROPERTY1 \
  +lightning_module/diffusion_module/model/property_embeddings@adapter.adapter.property_embeddings_adapt.$PROPERTY2=$PROPERTY2 \
  ~trainer.logger \
  data_module.properties="[\"$PROPERTY1\",\"$PROPERTY2\"]" \
  hydra.run.dir=results
```

- `adapter.model_path=MODEL_NAME`: `MODEL_NAME` should be a reaaly path.
- `data_module.root_dir=data_path`: `data_path` should be a reaaly absolute path.
- `PROPERTY1` and `PROPERTY2` must be replaced with the actual property names used by the dataset and configuration. If only one property is used, include only one property in the command.






## Finetuning on Bohrium

When submitting MatterGen jobs to Bohrium through `dpdisp`, Bohrium-specific submission settings, including authentication, project, image, and machine type, can be read from environment variables such as 'BOHRIUM_MAT_IMAGE' and 'BOHRIUM_MAT_MACHINE'. For the `dpdisp` submission procedure, refer to the `dpdisp` skill documentation.

- When using Bohrium, you must use model_path; pretrained_name cannot be used.
- When using Bohrium, `forward_files` should include the pretrained model directory. The local pretrained model path can be obtained from the environment variable `mattergen_model`, with one folder per pretrained model name, such as `mattergen_base`. If the target property is already covered by an existing pretrained property model, you can also finetune from that pretrained property model.



Prepare a writable local job directory first:

```bash
ts=$(date +"%Y%m%d%H%M%S")
workdir="matg/${ts}.mattergen_finetune"
mkdir -p "$workdir"
cd "$workdir"
```

Then copy the dataset cache produced by `csv-to-dataset` into `"$workdir"`.

Then copy the model into `"$workdir"`.

In `submission.json`:

- set `forward_files` to include two entries: the pretrained model directory, such as `mattergen_base`, and the specific dataset directory, for example `my_bandgap_dataset`
- set `backward_files` to the generation output directory, for example `results`
- set `command` to a generation command such as:


```bash
mattergen-finetune adapter.model_path=MODEL_NAME data_module=mp_20 data_module.root_dir=data_path +lightning_module/diffusion_module/model/property_embeddings@adapter.adapter.property_embeddings_adapt.$PROPERTY1=$PROPERTY1 +lightning_module/diffusion_module/model/property_embeddings@adapter.adapter.property_embeddings_adapt.$PROPERTY2=$PROPERTY2 ~trainer.logger data_module.properties=["$PROPERTY1","$PROPERTY2"] hydra.run.dir=results
```

- `adapter.model_path=MODEL_NAME`: `MODEL_NAME` can be a relativate path, such as 'mattergen_base'.
- `data_module.root_dir=data_path`: Because the Bohrium remote root is `${REMOTE_ROOT}`, so `data_path` should be an absolute path start with `${REMOTE_ROOT}`. It should usually be an absolute path such as `${REMOTE_ROOT}/my_dataset`.
- `PROPERTY1` and `PROPERTY2` must be replaced with the actual property names used by the dataset and configuration. If only one property is used, include only one property in the command.



An example for single-property finetune command:

```bash
mattergen-finetune adapter.model_path=${REMOTE_ROOT}/home/zdj/softutils/mattergen/checkpoints/mattergen_base data_module=mp_20 data_module.root_dir=${REMOTE_ROOT}/my_dataset +lightning_module/diffusion_module/model/property_embeddings@adapter.adapter.property_embeddings_adapt.$PROPERTY1=$PROPERTY1 ~trainer.logger data_module.properties=["$PROPERTY1"] hydra.run.dir=results
```




## Finetuning Outputs

Hydra finetuning runs typically write outputs under the hydra.run.dir in the command, including:
- `.hydra/config.yaml`
- `lightning_logs/version_0/metrics.csv`
- `lightning_logs/version_0/checkpoints/last.ckpt`

After finetuning completes, package the trained result into a standard reusable model directory using the files under the `results` directory. The target layout should be:

```text
~/model/new_model/
  config.yaml
  checkpoints/
    last.ckpt
```

Use:
- `results/config.yaml` as `my_new_model/config.yaml`
- `results/lightning_logs/version_0/checkpoints/last.ckpt` as `my_new_model/checkpoints/last.ckpt`

Example:

```bash
ts=$(date +"%Y%m%d%H%M%S")
modeldir="~/model/${ts}"
mkdir -p "$workdir"
cp results/config.yaml $modeldir/config.yaml
cp results/lightning_logs/version_0/checkpoints/last.ckpt $modeldir/checkpoints/last.ckpt
```



Report at minimum:
- the exact pretrained model name or local model path used for finetuning, which should usually be `mattergen_base` unless the user requested another base
- the absolute path of the Hydra output directory
- the absolute path of `checkpoints/last.ckpt`
- the absolute path of `metrics.csv`, if available
