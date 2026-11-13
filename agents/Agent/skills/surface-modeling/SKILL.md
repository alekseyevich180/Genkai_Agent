---
name: surface-modeling
description: "Use when a reviewed modeling plan requires oxide-surface, vacancy, adsorbate, or supported-cluster structure candidates; do not use for DFT labeling or MLIP training."
metadata:
  maturity: stable
  domain: modeling
  tools:
    - run_python_file
  dependent_skills:
    - atomic-structure
    - structure-conversion
    - vasp
  consumes:
    - modeling-plan@1
  produces:
    - structure-set@1
  entrypoints:
    - scripts/surface/slab_generation.py
    - scripts/vacancy/vacancy_landscape.py
    - scripts/adsorbate/adsorbate_landscape.py
    - scripts/metal_cluster/surface_cluster_builder.py
  tags:
    - surface
    - slab
    - pymatgen
    - oxide
    - adsorption
    - oxygen-vacancy
    - nanocluster
    - MLIP
    - ASE
---

# Surface Modeling Skill

Use this skill when a task is about oxide surface construction, vacancy sampling, adsorption coverage generation, or metal cluster placement on surfaces. The scripts are adapted from the `Oxidesurface_cluster` project and are intended to make this Agent project surface-focused.

Stable algorithm ownership is under `src/genkai/modeling/surface/`; the script
paths documented below are thin compatibility entrypoints for Skill callers.

## Workflow

1. Build the surface slab from a bulk crystal with `scripts/surface/slab_generation.py` (pymatgen; see below), or supply an existing slab in CIF, VASP/POSCAR, XYZ, or another ASE-readable format.
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

## Slab Generation From Bulk (pymatgen)

Script (thin entry over `genkai.modeling.surface.slab`):

```bash
python agents/Agent/skills/surface-modeling/scripts/surface/slab_generation.py   --bulk CeO2_bulk.cif   --output-dir modeling/slab
```

The bulk can also come from Materials Project with `--formula CeO2` or
`--material-id mp-20194` (requires `MP_API_KEY`). A slab passed as `--bulk` is
rejected.

What the generator does:

1. Converts the bulk to the conventional standard cell, so Miller indices mean
   what papers mean. Materials Project often returns primitive cells, where
   `(1,0,0)` of an fcc primitive basis is a conventional `{111}` plane.
2. Resolves the facet: `--facet` (paper or user) -> surface-energy ranking when
   `--calculator emt|uma` (Wulff area fraction over facets up to
   `--max-index`) -> reviewed stable-facet registry -> stop for manual review.
3. Enumerates all terminations with pymatgen `SlabGenerator` and prefers
   non-polar, stoichiometric, symmetric ones. Polarity is evaluated with guessed
   oxidation states.
4. Makes `c` orthogonal to the surface, tiles laterally to `--min-lateral-size`
   (default 8 A perpendicular width), fixes layers below `--fixed-fraction`
   (default 0.5) or the bottom `--fixed-layers`, and tags atoms
   (0 = fixed subsurface, 1 = free surface region).
5. Validates vacuum, interatomic distances, lateral size, polarity and
   stoichiometry; the script exits with code 2 when validation fails.

Rank facets by surface energy with UMA (or `--calculator emt` for EMT metals):

```bash
python agents/Agent/skills/surface-modeling/scripts/surface/slab_generation.py   --bulk Pt_bulk.cif --calculator uma --uma-model uma-s-1p2 --task-name omat   --device cuda --max-index 2 --relax-steps 100 --output-dir modeling/slab
```

Surface energies use `gamma = (E_slab - N * e_bulk) / (2A)` and are defined only
for stoichiometric terminations; non-stoichiometric terminations need chemical
potentials and are not ranked. MLIP surface energies are screening values, not
DFT evidence.

Main outputs:

- `slab.vasp`: POSCAR with selective dynamics for fixed atoms
- `slab.extxyz`: same structure with tags and constraints
- `bulk_conventional.cif`
- `slab_manifest.json`: facet source, all terminations, screening table,
  geometry, settings and validation report
- `run_config.json`

## Executing A Modeling Plan (structure-only)

Use this after a run has a PToModel plan, e.g. from a saved extraction:

```bash
genkai-workflow init runs/sno2 --relations saved_surface_relations.jsonl
genkai-workflow surface execute --run-root runs/sno2      # lists what is still missing
genkai-workflow surface execute --run-root runs/sno2 \
  --bulk SnO2_bulk.cif --surface-facet "(110)" \
  --molecule-name NO2 --coverage-counts 1,2 --site-symbols Sn
```

The executor (`genkai.modeling.surface.executor.execute_surface_plan`) builds
the slab, runs the registered tasks (currently `adsorbate_landscape`) with
`calculator="none"` and `max_steps=0`, and registers one
`stages/03_surface_structures*/structures.extxyz` as the run's latest
`StructureSetArtifact` (frame 0 is the clean slab; fixed atoms and tags are
kept). Rules:

- It never guesses: a slab or bulk source, a confirmed exposed facet, the gas
  molecule and integer coverages must be supplied; otherwise it exits with code
  2 and lists each missing input without touching the manifest. XRD/HRTEM
  lattice planes are not accepted as exposed facets; `--use-facet-registry`
  explicitly accepts the reviewed registry facet.
- Slab sources: `--surface` (reviewed slab) > `--bulk` (local bulk crystal) >
  the plan formula from Materials Project, only with `--allow-materials-project`.
- Built-in gases (ASE G2 geometries): H2, O2, O3, H2O, CO, CO2, NO, NO2, NH3,
  H2S, SO2, CH4, CH3OH, C2H5OH (ethanol), HCHO (formaldehyde), CH3CHO, CH3COCH3
  (acetone), C6H6; other adsorbates need `--molecule FILE`.
- Plan site symbols absent from the slab are dropped and reported; exact
  duplicates are removed; candidates with overlapping atoms are excluded and
  mark the set `needs_review`.
- Output structures are unrelaxed geometric candidates (evidence `heuristic`);
  mock placement energies stay in `adsorbate_landscape/runner.log` and are not
  results. Tasks without a structure-only runner (vacancy, clusters,
  SAM/functionalization, doping) are reported as skipped.

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

`--task-name` is the UMA task head passed to `FAIRChemCalculator` (default `omat`; the cluster search below uses `--task_name`, default `oc22`). Choose it deliberately for the system and check that the selected model exposes it. Every script writes `run_config.json` to its output directory with the calculator, model, task head and device actually used.

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

### Materials Project bulk-to-stable-surface route

Set the API key only through the environment. The key is never written to a
manifest or structure file.

```bash
export MP_API_KEY="..."
python agents/Agent/skills/surface-modeling/scripts/metal_cluster/surface_cluster_builder.py \
  --surface-formula CeO2 \
  --cluster-element Ni \
  --cluster-from-mp \
  --cluster-atoms 13 \
  --output_dir modeling/structures
```

This route downloads stable bulk references, resolves the surface facet in the
order paper/user explicit facet -> reviewed stable-facet registry -> stop for
manual review, constructs a vacuum-containing slab with the same
`genkai.modeling.surface.slab` generator (conventional cell, termination checks, fixed
bottom half), and only then places the cluster. The default `--slab-repeat-xy`
stays `2,2`; check `slab.lateral_widths_A` in the surface manifest before placing
large clusters.
Direct use of a bulk unit cell as `--surface` is rejected. The output includes
`modeling_manifest.json` with MP identifiers, facet provenance, structure files,
assumptions, and slab checks.

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

## Knowledge Loop Policy

This skill consumes paper-derived parameters and should feed successful
modeling choices back into the Agent knowledge loop.

The intended loop is:

```text
paperread / ptomodel evidence
-> surface-modeling task schema
-> generated candidate structures
-> validation or calculation result
-> reusable parameter choice / warning
-> paperread experience registry and durable graph knowledge
```

Before running a modeling script:

- Prefer a `*_ptomodel.json` task argument template when the task comes from a
  paper.
- Check `src/genkai/modeling/schema/task_parameter_schema.json`
  for required arguments and constraints.
- Check `agents/Agent/skills/paperread/experience/surface_parameter_registry.json`
  for known material class, facet, active-site, adsorbate, dopant, coverage,
  cluster, and reaction keywords.
- Run `--smoke-test` or `--calculator none` first when a workflow supports it.

During modeling, preserve evidence that can be reused:

- Input structure path, material formula, material class, facet, termination,
  and surface region selection.
- Vacancy count, vacancy concentration, dopant identity, active-site symbols,
  adsorbate identity, coverage count, cluster element, cluster atom count, and
  placement mode.
- Calculator choice, model name, device, convergence limits, and selection
  criteria.
- Output directories, ranked CSV files, best structures, failed trials, and
  any warning that affects later reuse.

After modeling:

- Feed successful parameter choices and recurring failures back to the
  `paperread` experience store as candidate experience.
- If a paper-derived task cannot be represented by the current schema, record
  the missing task or parameter rather than forcing it into the closest script.
- Use `agent knowledge distill --min-evidence 3` when the same modeling
  parameter choice or failure pattern appears repeatedly.
- Use `agent knowledge seed` after updating this skill or the task parameter
  schema so the graph can retrieve the new capability.

## Parameter Experience JSON

Use the following JSON-style parameter schemas when another agent needs to map
`ptomodel` outputs to script arguments without re-reading Python sources.
These records are intentionally value-free: they define parameter names,
expected types, required-ness, grouping, and constraints.

The machine-readable copy used by `ptomodel` is stored at:

- `src/genkai/modeling/schema/task_parameter_schema.json`

### Slab Generation

```json
{
  "script": "agents/Agent/skills/surface-modeling/scripts/surface/slab_generation.py",
  "task_key": "slab_generation",
  "ptomodel_mapping_role": "bulk-to-slab surface construction input",
  "parameters": {
    "bulk": { "type": "path", "required": false },
    "formula": { "type": "string", "required": false },
    "material_id": { "type": "string", "required": false },
    "facet": { "type": "string", "required": false },
    "max_index": { "type": "int", "required": false },
    "calculator": { "type": "enum", "required": false, "choices": ["none", "emt", "uma"] },
    "uma_model": { "type": "string", "required": false },
    "task_name": { "type": "string", "required": false },
    "device": { "type": "enum", "required": false, "choices": ["cuda", "cpu"] },
    "relax_steps": { "type": "int", "required": false },
    "fmax": { "type": "float", "required": false },
    "min_slab_size": { "type": "float", "required": false },
    "min_vacuum_size": { "type": "float", "required": false },
    "min_lateral_size": { "type": "float", "required": false },
    "repeat_xy": { "type": "string", "required": false },
    "fixed_fraction": { "type": "float", "required": false },
    "fixed_layers": { "type": "int", "required": false },
    "output_dir": { "type": "path", "required": false },
    "prefix": { "type": "string", "required": false }
  },
  "constraints": [
    "exactly one of bulk, formula, material_id must be provided",
    "without facet, calculator='none' uses the reviewed stable-facet registry and stops when no entry exists",
    "calculator in ['emt', 'uma'] ranks facets up to max_index by surface energy",
    "0 <= fixed_fraction < 1"
  ]
}
```

### Oxygen-Vacancy Landscape

```json
{
  "script": "agents/Agent/skills/surface-modeling/scripts/vacancy/vacancy_landscape.py",
  "task_key": "vacancy_landscape",
  "ptomodel_mapping_role": "oxide surface vacancy modeling input",
  "parameters": {
    "input": { "type": "path", "required": true },
    "output_dir": { "type": "path", "required": false },
    "structure_prefix": { "type": "string", "required": false },
    "vacancy_counts": { "type": "comma_separated_ints", "required": false },
    "samples_per_count": { "type": "int", "required": false },
    "mu_o": { "type": "float", "required": false },
    "z_frac_min": { "type": "float", "required": false },
    "z_frac_max": { "type": "float", "required": false },
    "calculator": { "type": "enum", "required": false, "choices": ["uma", "none"] },
    "smoke_test": { "type": "bool", "required": false },
    "uma_model": { "type": "string", "required": false },
    "device": { "type": "enum", "required": false, "choices": ["cuda", "cpu"] },
    "task_name": { "type": "string", "required": false, "description": "FAIRChem UMA task head such as omat or oc20; not the PToModel task key" },
    "include_d3": { "type": "bool", "required": false },
    "fmax": { "type": "float", "required": false },
    "max_steps": { "type": "int", "required": false },
    "seed": { "type": "int", "required": false },
    "write_all_structures": { "type": "bool", "required": false }
  },
  "constraints": [
    "samples_per_count >= 1",
    "0 <= z_frac_min <= z_frac_max <= 1",
    "calculator in ['uma', 'none']",
    "calculator='uma' 时才真正需要 uma_model 和 device"
  ]
}
```

### Adsorbate Coverage Landscape

```json
{
  "script": "agents/Agent/skills/surface-modeling/scripts/adsorbate/adsorbate_landscape.py",
  "task_key": "adsorbate_landscape",
  "ptomodel_mapping_role": "surface adsorbate coverage modeling input",
  "parameters": {
    "surface": { "type": "path", "required": true },
    "molecule": { "type": "path", "required": true },
    "output_dir": { "type": "path", "required": false },
    "structure_prefix": { "type": "string", "required": false },
    "site_symbols": { "type": "string", "required": false },
    "site_z_tolerance": { "type": "float", "required": false },
    "max_sites": { "type": "int", "required": false },
    "site_group_size": { "type": "int", "required": false },
    "n_trials_single": { "type": "int", "required": false },
    "site_radius": { "type": "float", "required": false },
    "z_gap_min": { "type": "float", "required": false },
    "z_gap_max": { "type": "float", "required": false },
    "coverage_counts": { "type": "comma_separated_ints", "required": false },
    "patterns": { "type": "comma_separated_strings", "required": false },
    "random_repeats": { "type": "int", "required": false },
    "seed": { "type": "int", "required": false },
    "calculator": { "type": "enum", "required": false, "choices": ["uma", "none"] },
    "uma_model": { "type": "string", "required": false },
    "device": { "type": "enum", "required": false, "choices": ["cuda", "cpu"] },
    "task_name": { "type": "string", "required": false, "description": "FAIRChem UMA task head such as omat or oc20; not the PToModel task key" },
    "include_d3": { "type": "bool", "required": false },
    "fmax": { "type": "float", "required": false },
    "max_steps": { "type": "int", "required": false },
    "smoke_test": { "type": "bool", "required": false }
  },
  "constraints": [
    "site_group_size >= 1",
    "coverage_counts 中每个值必须在 1 到 max_adsorbates 之间",
    "patterns 由 uniform, clustered, stripe, island, random 组成",
    "calculator in ['uma', 'none']"
  ]
}
```

### Metal Cluster Or Cluster-On-Surface Builder

```json
{
  "script": "agents/Agent/skills/surface-modeling/scripts/metal_cluster/surface_cluster_builder.py",
  "task_key": "surface_cluster_builder",
  "ptomodel_mapping_role": "supported cluster species or loaded nanoparticle modeling input",
  "parameters": {
    "surface": { "type": "path", "required": false },
    "cluster_element": { "type": "string", "required": false },
    "cluster_bulk_file": { "type": "path", "required": false },
    "cluster_structures": {
      "type": "string_list",
      "required": false,
      "choices": ["fcc", "hcp", "bcc"]
    },
    "cluster_atoms": { "type": "int", "required": false },
    "cluster_layers": { "type": "int", "required": false },
    "cluster_radius": { "type": "float", "required": false },
    "stack_layers": { "type": "int", "required": false },
    "bcc_rows": { "type": "int", "required": false },
    "bcc_max_row_atoms": { "type": "int", "required": false },
    "cluster_a": { "type": "float", "required": false },
    "cluster_c": { "type": "float", "required": false },
    "fcc_rows": { "type": "comma_separated_ints", "required": false },
    "fcc_row_profile": {
      "type": "enum",
      "required": false,
      "choices": ["auto", "custom", "triangle", "hexagon", "trapezoid", "rectangle"]
    },
    "fcc_max_row_atoms": { "type": "int", "required": false },
    "fcc_row_count": { "type": "int", "required": false },
    "fcc_stacking_mode": { "type": "enum", "required": false, "choices": ["ABC", "AB"] },
    "fcc_layers": { "type": "int", "required": false },
    "hcp_rows": { "type": "comma_separated_ints", "required": false },
    "hcp_layers": { "type": "int", "required": false },
    "x_frac": { "type": "float", "required": false },
    "y_frac": { "type": "float", "required": false },
    "z_height": { "type": "float", "required": false },
    "phi": { "type": "float", "required": false },
    "theta": { "type": "float", "required": false },
    "psi": { "type": "float", "required": false },
    "output_dir": { "type": "path", "required": false }
  },
  "constraints": [
    "cluster_element 和 cluster_bulk_file 至少应能解析出一种金属元素来源",
    "普通模式下 cluster_atoms / cluster_layers / cluster_radius 三选一",
    "bcc bridge 模式需要同时提供 bcc_rows, bcc_max_row_atoms, stack_layers",
    "fcc row 模式需要 fcc_layers，并提供 fcc_rows 或可推导 row_profile 参数",
    "hcp row 模式需要 hcp_rows"
  ]
}
```

### Surface-Cluster MLIP Search

```json
{
  "script": "agents/Agent/skills/surface-modeling/scripts/cluster_search/ads_nanocluster.py",
  "task_key": "surface_cluster_mlip_search",
  "ptomodel_mapping_role": "surface-plus-prebuilt-cluster adsorption search input",
  "parameters": {
    "surface": { "type": "path", "required": true },
    "cluster": { "type": "path", "required": true },
    "output_dir": { "type": "path", "required": false },
    "n_trials": { "type": "int", "required": false },
    "fmax": { "type": "float", "required": false },
    "uma_model": { "type": "string", "required": false },
    "task_name": { "type": "string", "required": false, "description": "FAIRChem UMA task head such as omat or oc20; not the PToModel task key" },
    "checkpoint": { "type": "path_or_null", "required": false },
    "device": { "type": "enum", "required": false, "choices": ["cuda", "cpu"] },
    "placement_mode": { "type": "enum", "required": false, "choices": ["cell", "active"] },
    "active_symbols": { "type": "string_list", "required": false },
    "site_radius": { "type": "float", "required": false },
    "z_min": { "type": "float", "required": false },
    "z_max": { "type": "float", "required": false },
    "detach_cutoff": { "type": "float", "required": false },
    "penalty_energy": { "type": "float", "required": false },
    "max_steps": { "type": "int", "required": false },
    "include_d3": { "type": "bool", "required": false },
    "candidate_pool_size": { "type": "int", "required": false },
    "selection_count": { "type": "int", "required": false },
    "top_pool_size": { "type": "int", "required": false },
    "top_pick_count": { "type": "int", "required": false },
    "tail_bin_size": { "type": "int", "required": false },
    "tail_pick_per_bin": { "type": "int", "required": false },
    "selection_random_seed": { "type": "int", "required": false }
  },
  "constraints": [
    "placement_mode in ['cell', 'active']",
    "placement_mode='active' 时必须提供 active_symbols",
    "该脚本默认依赖 fairchem-core, torch 和 UMA 模型，不提供 calculator='none' 的假跑模式"
  ]
}
```
