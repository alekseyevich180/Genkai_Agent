---
name: cgcnn-predictor
description: Predict material properties of crystal structures with CGCNN models.
metadata:
  tools: []
  dependent_skills: []
---
# CGCNN Predictor Skill

Use this skill to predict crystal properties with a local CGCNN setup, including regression targets such as formation energy, band gap, Fermi energy, or elastic properties, as well as classification tasks such as metal versus semiconductor.



If the help command runs without import errors, the environment is ready.

## Dataset Format

Prepare the dataset directory as:

```text
dataset_dir/
├── id_prop.csv
├── atom_init.json
├── id0.cif
├── id1.cif
├── ...
```

Requirements:
- `id_prop.csv` must have two columns: crystal ID and target value
- For prediction, the second column can be a placeholder number, but it must exist
- Each crystal ID must match a CIF filename without the `.cif` suffix
- `atom_init.json` should usually be copied from `data/sample-regression/atom_init.json` under `CGCNN_ROOT`

This dataset layout is required by the upstream CGCNN prediction workflow.

## Common Pre-trained Models

Common checkpoints in `pre-trained/` include:
- `formation-energy-per-atom.pth.tar`: formation energy, unit `eV/atom`
- `final-energy-per-atom.pth.tar`: absolute energy, unit `eV/atom`
- `band-gap.pth.tar`: band gap, unit `eV`
- `efermi.pth.tar`: Fermi energy, unit `eV/atom`
- `bulk-moduli.pth.tar`: bulk modulus, unit `log(GPa)`
- `shear-moduli.pth.tar`: shear modulus, unit `log(GPa)`
- `poisson-ratio.pth.tar`: Poisson ratio, dimensionless
- `semi-metal-classification.pth.tar`: classification model for metal vs semiconductor, no physical unit

## Prediction Command

Run prediction from cgcnn dir:

```bash
python predict.py <model_path> <dataset_dir>
```

Examples:

```bash
source "${cgcnn_env}/bin/activate"
cd "${CGCNN_ROOT}"
python predict.py pre-trained/formation-energy-per-atom.pth.tar dataset_dir
```

The upstream CGCNN run writes `test_results.csv` under `${CGCNN_ROOT}`. After prediction, always copy that file into the dataset_dir. For classification tasks, predicted values are probabilities between 0 and 1.

If the predicted property is bulk modulus or shear modulus, convert the prediction to the standard unit `GPa` after inference.

## What to Report

- The absolute path of the dataset directory
- The exact model or checkpoint used
- The absolute path of the generated `test_results.csv`
