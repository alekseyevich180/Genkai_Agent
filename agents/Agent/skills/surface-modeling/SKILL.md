---
name: surface-modeling
description: Build realistic oxide-surface candidates: oxygen-vacancy landscapes, adsorbate coverage landscapes, and metal-cluster-on-surface starting structures using ASE, Optuna, and optional UMA/FAIRChem calculators.
metadata:
  tools:
    - run_python_file
  dependent_skills:
    - atomic-structure
    - structure-conversion
    - vasp
  tags:
    - surface
    - oxide
    - adsorption
    - oxygen-vacancy
    - nanocluster
    - MLIP
    - ASE
---

# Surface Modeling Skill

Use this skill when a task is about oxide surface construction, vacancy sampling, adsorption coverage generation, or metal cluster placement on surfaces. The scripts are adapted from the `Oxidesurface_cluster` project and are intended to make this Agent project surface-focused.

## Workflow

1. Obtain or build an oxide surface slab in CIF, VASP/POSCAR, XYZ, or another ASE-readable format.
2. Generate realistic modified surfaces:
   - oxygen vacancies with `scripts/vacancy/vacancy_landscape.py`
   - adsorbate coverage structures with `scripts/adsorbate/adsorbate_landscape.py`
3. Build isolated metal clusters or cluster-on-surface starting structures with `scripts/metal_cluster/surface_cluster_builder.py`.
4. Search surface-cluster adsorption geometries with `scripts/cluster_search/ads_nanocluster.py` when UMA/FAIRChem is available.
5. Use the `vasp` skill for DFT refinement or MLIP training label preparation.

The vacancy and adsorbate scripts support `--calculator none` or `--smoke-test` for fast local workflow validation. Use `--calculator uma` only when `fairchem-core`, PyTorch, and the target UMA model are available.

## Dependencies

Required:

- `ase`
- `numpy`
- `pandas`
- `matplotlib`
- `scipy`
- `optuna`

Optional for real MLIP relaxation:

- `torch`
- `fairchem-core`
- `ase.calculators.dftd3` and a D3 executable when `--include-d3` is used

## Oxygen-Vacancy Landscape

Script:

```bash
python agents/Agent/skills/surface-modeling/scripts/vacancy/vacancy_landscape.py \
  --input "agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif" \
  --vacancy-counts 1,2,3 \
  --samples-per-count 20 \
  --mu-o 0.0 \
  --z-frac-min 0.5 \
  --z-frac-max 1.0 \
  --calculator none \
  --write-all-structures
```

Fast smoke test:

```bash
python agents/Agent/skills/surface-modeling/scripts/vacancy/vacancy_landscape.py \
  --input "agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif" \
  --smoke-test
```

Main outputs:

- `vacancy_energy_landscape.csv`
- `vacancy_energy_landscape.png`
- `clean_relaxed.cif`
- `stable_vacancy_structure.cif`
- `structures/ov_*.cif` when `--write-all-structures` is enabled

Energy descriptor:

```text
E_vac = E_defect - E_clean + m * mu_O
```

For physical runs, set `--calculator uma --uma-model uma-s-1p2 --device cuda` and choose `--mu-o` consistently with the oxygen chemical-potential reference.

## Adsorbate Coverage Landscape

Script:

```bash
python agents/Agent/skills/surface-modeling/scripts/adsorbate/adsorbate_landscape.py \
  --surface "agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif" \
  --molecule "agents/Agent/skills/surface-modeling/examples/H2O.xyz" \
  --site-symbols Ce \
  --site-z-tolerance 1.2 \
  --site-group-size 1 \
  --n-trials-single 60 \
  --coverage-counts 1,2,3,4 \
  --patterns uniform,clustered,stripe,island,random \
  --calculator none
```

Fast smoke test:

```bash
python agents/Agent/skills/surface-modeling/scripts/adsorbate/adsorbate_landscape.py \
  --surface "agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif" \
  --molecule "agents/Agent/skills/surface-modeling/examples/4-acid.vasp" \
  --smoke-test
```

Use `--site-group-size 2` or `--site-group-size 3` when one adsorbate should occupy multiple neighboring surface sites.

Main outputs:

- `adsorption_sites.csv`
- `adsorption_site_groups.csv`
- `single_adsorbate_best.cif`
- `adsorbate_coverage_landscape.csv`
- `adsorbate_coverage_landscape.png`
- `stable_adsorbate_coverage_structure.cif`
- `structures/ads_*.cif`

Energy descriptor:

```text
E_ads = (E_total - E_slab - N * E_mol) / N
```

## Metal Cluster And Surface-Cluster Construction

Script:

```bash
python agents/Agent/skills/surface-modeling/scripts/metal_cluster/surface_cluster_builder.py \
  --surface "agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif" \
  --cluster_element Pt \
  --cluster_structures fcc hcp bcc \
  --cluster_atoms 13 \
  --x_frac 0.5 \
  --y_frac 0.5 \
  --z_height 2.5 \
  --output_dir surface_cluster_output
```

For row-controlled compact clusters:

```bash
python agents/Agent/skills/surface-modeling/scripts/metal_cluster/surface_cluster_builder.py \
  --cluster_element Pt \
  --cluster_structures fcc \
  --fcc_row_profile triangle \
  --fcc_max_row_atoms 4 \
  --fcc_layers 3 \
  --output_dir pt_cluster_output
```

Supported cluster motifs:

- `fcc`: spherical atom-count clusters or row-controlled fcc(111) compact clusters
- `hcp`: spherical atom-count clusters or row-controlled hcp(0001) compact clusters
- `bcc`: spherical atom-count clusters or bcc(110) bridge clusters

## Surface-Cluster MLIP Search

Script:

```bash
python agents/Agent/skills/surface-modeling/scripts/cluster_search/ads_nanocluster.py \
  --surface surface.cif \
  --cluster pt13_cluster.cif \
  --output_dir output_nanocluster \
  --n_trials 100 \
  --placement_mode active \
  --active_symbols Ce \
  --uma_model uma-s-1p2 \
  --device cuda
```

This script relaxes the input surface and isolated cluster, uses Optuna to sample cluster position/orientation, ranks valid non-detached trials, and exports both CIF candidates and VASP-ready structures.

Main outputs:

- `output_nanocluster/mlip_output/initial_surface.cif`
- `output_nanocluster/mlip_output/initial_cluster.cif`
- `output_nanocluster/mlip_output/mlip_best_structure.cif`
- `output_nanocluster/mlip_output/mlip_energy_table.csv`
- `output_nanocluster/mlip_output/XX_trial_YYY.cif`
- `output_nanocluster/vasp/*.vasp`

This is a production MLIP entry point. Unlike the vacancy and adsorbate landscape scripts, it imports `torch` and `fairchem-core` at startup and does not provide a mock-calculator mode.

## Practical Guidance

- Prefer `--smoke-test` before a real UMA run to validate input paths, atom symbols, site selection, output directories, and plotting.
- For oxide surfaces, restrict vacancy sampling to the relevant surface region with `--z-frac-min` and `--z-frac-max`.
- For adsorption, choose `--site-symbols` from exposed surface cations or active atoms and inspect `adsorption_sites.csv`.
- Keep MLIP-ranked structures and DFT-ready VASP inputs in separate directories so downstream labeling remains traceable.
- Use `structure-conversion` when a downstream tool needs a different structure format.
