---
name: surface-modeling
description: "Use when a reviewed modeling plan requires oxide-surface, vacancy, adsorbate, SAM-functionalized, ALD amorphous-overlayer, or supported-cluster structure candidates; do not use for DFT labeling or MLIP training."
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
    - scripts/sam/sam_builder.py
    - scripts/ald/ald_overlayer.py
    - scripts/amorphous/amorphous_slab.py
    - scripts/amorphous/amorphous_bulk.py
    - scripts/sam/sam_search.py
    - scripts/amorphous/amorphous_screen.py
  tags:
    - surface
    - slab
    - pymatgen
    - oxide
    - adsorption
    - oxygen-vacancy
    - nanocluster
    - self-assembled-monolayer
    - ALD
    - amorphous
    - MLIP
    - ASE
---

# Surface Modeling Skill

Use this skill when a task is about oxide surface construction, vacancy sampling, adsorption coverage generation, or metal cluster placement on surfaces. The scripts are adapted from the `Oxidesurface_cluster` project and are intended to make this Agent project surface-focused.

Stable algorithm ownership is under `src/genkai/modeling/surface/` (builders in
`builders/`, energy searches in `screening/`, calculators and samplers in `mlip/`, the
`genkai-surface` entry in `app/`); the script paths documented below are thin
compatibility entrypoints for Skill callers.

## Workflow

1. Build the surface slab from a bulk crystal with `scripts/surface/slab_generation.py` (pymatgen; see below), or supply an existing slab in CIF, VASP/POSCAR, XYZ, or another ASE-readable format.
2. Generate realistic modified surfaces:
   - oxygen vacancies with `scripts/vacancy/vacancy_landscape.py`
   - adsorbate coverage structures with `scripts/adsorbate/adsorbate_landscape.py`
   - SAM-functionalized surfaces with `scripts/sam/sam_builder.py`
   - ALD-modified surfaces (amorphous film or island) with `scripts/ald/ald_overlayer.py`
   - pure amorphous surfaces with `scripts/amorphous/amorphous_slab.py`; when only a crystal is
     available, first make the amorphous bulk by melt-quench MD with
     `scripts/amorphous/amorphous_bulk.py` (needs an MLIP)
   - energy-based (MLIP) screening: SAM placements and coverage with
     `scripts/sam/sam_search.py`, amorphous surfaces and amorphous/crystal
     interfaces with `scripts/amorphous/amorphous_screen.py`, islands with
     `scripts/cluster_search/ads_nanocluster.py`
3. Build isolated metal clusters or cluster-on-surface starting structures with `scripts/metal_cluster/surface_cluster_builder.py`.
4. Search surface-cluster adsorption geometries with `scripts/cluster_search/ads_nanocluster.py` when UMA/FAIRChem is available.
5. Use the `vasp` skill for DFT refinement or MLIP training label preparation.

`python scripts/run_modeling_smoke.py` (repository root) runs every method above on
structures shipped in the repository and checks the generated structures; see
`--list` for the cases. Note that `--smoke-test` of the adsorbate and vacancy
scripts replaces `--output-dir` with a fixed folder in the current directory;
the smoke script passes `--calculator none --max-steps 0` explicitly instead.

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

Script (thin entry over `genkai.modeling.surface.builders.slab`):

```bash
python agents/Agent/skills/surface-modeling/scripts/surface/slab_generation.py \
  --bulk my_bulk.cif --facet "(110)" \
  --output-dir modeling/slab
```

The bulk can also come from Materials Project with `--formula CeO2` or
`--material-id mp-20194` (requires `MP_API_KEY`). A slab passed as `--bulk` is
rejected.

What the generator does:

1. Interprets `--facet` in the right cell (`--miller-basis`, default `auto`):
   the input cell as given, so an index typed for a non-standard setting (e.g.
   monoclinic WO3 in P2_1/n) keeps its meaning; a primitive cell of a centered
   lattice is converted to the conventional standard cell, as papers use it
   (`(1,0,0)` of an fcc primitive basis is a conventional `{111}` plane).
   Registry, surface-energy and Materials Project facets always use the
   conventional standard cell. The choice and reason are printed and stored in
   `slab_manifest.json` (`facet.miller_basis`).
2. Resolves the facet: `--facet` (paper or user) -> surface-energy ranking when
   `--calculator emt|uma` (Wulff area fraction over facets up to
   `--max-index`) -> reviewed stable-facet registry -> stop for manual review.
3. Enumerates all terminations with pymatgen `SlabGenerator` and prefers
   non-polar, stoichiometric, symmetric ones. Polarity is evaluated with guessed
   oxidation states.
4. Makes `c` orthogonal to the surface, wraps atoms into the cell in-plane,
   tiles laterally to `--min-lateral-size` (default 8 A perpendicular width),
   fixes layers below `--fixed-fraction` (default 0.5) or the bottom
   `--fixed-layers`, and tags atoms (0 = fixed subsurface, 1 = free surface
   region).
5. Places the slab at the bottom of the cell, `--bottom-margin` (default 0.5 A)
   above it, with all vacuum above the top surface; `--slab-position center`
   splits the vacuum instead.
6. Validates vacuum, interatomic distances, lateral size, polarity and
   stoichiometry; the script exits with code 2 when validation fails.

Rank facets by surface energy with UMA (or `--calculator emt` for EMT metals):

```bash
python agents/Agent/skills/surface-modeling/scripts/surface/slab_generation.py \
  --bulk Pt_bulk.cif --calculator uma --uma-model uma-s-1p2 --task-name omat \
  --device cuda --max-index 2 --relax-steps 100 --output-dir modeling/slab
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

The `--z-frac-min/--z-frac-max` window is a fraction of the cell height, so it
depends on where the slab sits. Slabs from `slab_generation` sit at the bottom
of the cell: select top-surface oxygen with
`z_frac_min = (z_top_O - 1.0 A) / c`, using the top oxygen height of the slab,
not the 0.5-1.0 window of the centered example above.

`--task-name` is the UMA task head passed to `FAIRChemCalculator` (default `omat`; the cluster search below uses `--task_name`, also default `omat`). Choose it deliberately for the system and check that the selected model exposes it. Every script writes `run_config.json` to its output directory with the calculator, model, task head and device actually used.

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

## Shared Substrate And File Conventions (SAM and ALD builders)

Both builders take the substrate from `--surface SLAB` (a reviewed slab) or
`--bulk BULK` (cut by `genkai.modeling.surface.builders.slab`). Without `--facet` the
most stable facet is used: surface-energy ranking with `--calculator emt|uma`
(EMT suits some metals only; UMA needs explicit authorization), otherwise the
reviewed stable-facet registry. The selection source is recorded as
`substrate.facet_source` in the manifest.

- Inputs default to CIF; any ASE-readable format works and `--*-format` forces
  one (an extension-less POSCAR falls back to the VASP reader).
- Slab files without constraints (every CIF) get the bottom fixed again with
  the slab-generator rule (by height when the slab has no discrete layers,
  e.g. amorphous slabs); the manifest records `constraints_source`.
- Slabs whose c is not normal to the surface (older MP routes) are rotated so
  a, b lie in the xy plane and c is replaced by its normal component; bonded
  distances are unchanged and the manifest records `cell_normalized`.
- Molecule CIFs are unwrapped, so molecules split across cell faces are whole.
- Outputs: one extxyz with all frames (frame 0 = clean slab), a JSON manifest,
  and `exports/` (CIF by default, `--export cif,vasp`; POSCAR is unsorted so
  indices match the extxyz). Tags: 0 fixed slab, 1 free slab, 2 added atoms.
- Every structure is unrelaxed (`evidence_level: heuristic`); no energy model
  runs. Exit code 2 means blocked or partially failed; read the manifest.

## SAM-Functionalized Surface

Script (thin entry over `genkai.modeling.surface.builders.sam`):

```bash
python agents/Agent/skills/surface-modeling/scripts/sam/sam_builder.py \
  --bulk SnO2.cif --molecule PAC12IMI.cif \
  --anchor-kind phosphonic --binding-mode bidentate --counts 1,2 \
  --output-dir sam_sno2

python agents/Agent/skills/surface-modeling/scripts/sam/sam_builder.py \
  --bulk Au.cif --facet 111 --molecule dodecanethiol.cif \
  --binding-mode fcc --counts 1,3 --tilt 30 --output-dir sam_au
```

- Anchor groups are detected from bonding: phosphonic acid (P with three
  terminal O and one C), carboxylic acid, thiol. A molecule with several groups
  (e.g. PAC10CA) is blocked until `--anchor-kind` chooses one; `--anchor-atoms`
  (0-based indices) overrides detection.
- Binding modes are user choices: phosphonic `monodentate|bidentate|tridentate`,
  carboxylic `monodentate|bidentate`, thiol `top|bridge|hollow|fcc|hcp`.
  Bonding O atoms are taken H-bearing first; a thiol S bonds to every atom of
  its site.
- Sites are exposed, undercoordinated surface atoms found by coordination
  (e.g. Sn5c on rutile (110), every top atom of Au(111)); `--site-symbols`
  restricts them. Modes the surface cannot host are blocked, e.g. tridentate on
  rutile (110) has no three Sn5c within reach.
- Acidic H (`--acidic-h auto`): moved to an exposed surface O as OH (bridging O
  first) on O-containing surfaces, removed on metals (thiolate); `keep` leaves
  it on the molecule.
- Coverage: `--counts 1,2,4` (one frame each) or `--density X` molecules/nm^2
  (rounded; the achieved density is recorded). Molecules use disjoint site
  groups; requests above the geometric capacity are reported as failed counts.
- Placement is a rigid-body fit of anchor-site bond lengths (covalent radii sum
  or `--bond-length`), tilt/azimuth and contact avoidance. The manifest lists
  every bond distance, tilt, H action and `min_nonbonded_contact_ratio`.
- Paper graft densities are not model coverages: on SnO2(110) the Sn5c density
  is about 4.7 nm^-2 and a bidentate SAM holds at most half of that.

## ALD-Modified Surface (Amorphous Overlayer)

Script (thin entry over `genkai.modeling.surface.builders.amorphous_overlayer`):

```bash
# Full coverage: continuous amorphous film
python agents/Agent/skills/surface-modeling/scripts/ald/ald_overlayer.py \
  --bulk SnO2.cif --amorphous a-Al2O3.cif --coverage full --thickness 6 \
  --output-dir ald_full

# Partial coverage: amorphous island on one facet (default: most stable facet)
python agents/Agent/skills/surface-modeling/scripts/ald/ald_overlayer.py \
  --bulk SnO2.cif --facet 101 --amorphous a-Al2O3.cif --coverage partial \
  --island-atoms 40 --samples 3 --output-dir ald_island_101
```

- `--amorphous` must be a periodic amorphous bulk cell (generated elsewhere,
  e.g. by melt-quench); slabs or clusters are rejected.
- Full coverage, `--film-fit auto` (default): first try `strain` - match the
  in-plane cells with pymatgen ZSL and strain the amorphous supercell affinely
  onto the slab supercell (`--max-strain`, `--max-area`; no mirror images), so
  the film is periodic without seams. If no match exists (e.g. hexagonal
  CeO2(111) or Ru(0001) against a square amorphous cell) use `cut`: a randomly
  rotated tiling of the amorphous cell is cut to the slab cell and atoms closer
  than 0.85 x the shortest same-pair distance of the amorphous bulk across the
  cell boundaries are removed (`seam_atoms_removed`). `--film-fit strain`
  refuses instead of cutting. Either way a `--thickness` window is placed
  `--interface-gap` above the slab.
- Partial coverage cuts a connected hemisphere-like island (`--island-atoms` or
  `--island-radius`) and enlarges the slab until the island is at least
  `--island-separation` from its periodic images. Run once per facet that
  carries islands; the manifest reports footprint fraction and image gap.
- `--samples N` gives N different cuts. Cut films and islands are usually
  off-stoichiometric; `composition` reports the anion/cation ratio against the
  amorphous bulk and is never corrected silently. Isolated atoms left by the
  cut are removed and counted.
- No relaxation or annealing: interfaces are starting points for an authorized
  MLIP/DFT relaxation or melt-quench.

## Pure Amorphous Surface

Script (thin entry over `genkai.modeling.surface.builders.amorphous_slab`):

```bash
python agents/Agent/skills/surface-modeling/scripts/amorphous/amorphous_slab.py \
  --amorphous a-SnO2.cif --thickness 8 --samples 3 --output-dir a_sno2_surface

# use one cut as the substrate of another builder
python agents/Agent/skills/surface-modeling/scripts/sam/sam_builder.py \
  --surface a_sno2_surface/amorphous_slab_000.extxyz --molecule acid.cif \
  --binding-mode bidentate --counts 1,2 --output-dir sam_on_a_sno2
```

- The in-plane cell is an integer supercell of the amorphous cell itself
  (`--min-lateral-size` or `--repeat-xy`), so the slab is exactly periodic
  without strain or seams; a tilted amorphous c is handled in Cartesian space.
- `--samples N` cuts N different windows along the normal, i.e. N different
  amorphous surfaces. Isolated atoms left by the cut are removed and counted.
- The bottom `--fixed-fraction` of the thickness is fixed (tags 0/1); vacuum
  `--vacuum` is added above. Each sample is written as
  `amorphous_slab_NNN.extxyz` (ready for `--surface`) plus a combined file.
- The manifest reports composition against the bulk (cut slabs are usually
  off-stoichiometric; not corrected), density of the cut window and the number
  of exposed undercoordinated cations. Nothing is relaxed.

## Amorphous Bulk From A Crystal (Melt-Quench MD)

Script (thin entry over `genkai.modeling.surface.builders.amorphous_bulk`):

```bash
# prepare only: supercell, density scaling and the planned schedule, no MD
python agents/Agent/skills/surface-modeling/scripts/amorphous/amorphous_bulk.py   --crystal SnO2.cif --density 6.4 --dry-run --output-dir a_sno2_bulk
# melt-quench with UMA (authorized GPU server only), then cut surfaces from the result
python agents/Agent/skills/surface-modeling/scripts/amorphous/amorphous_bulk.py   --crystal SnO2.cif --density 6.4 --samples 2   --calculator uma --uma-model uma-s-1p1 --task-name omat --device cuda --output-dir a_sno2_bulk
python agents/Agent/skills/surface-modeling/scripts/amorphous/amorphous_slab.py   --amorphous a_sno2_bulk/amorphous_bulk_000.extxyz --thickness 10 --output-dir a_sno2_surface
```

- Supercell: `--supercell a,b,c`, or the smallest near-cubic repeat with at least
  `--min-atoms` (default 150) atoms. `--density` (g/cm^3) scales the cell isotropically;
  without it the crystal density is kept (amorphous oxides are usually 5-10 % lighter).
- Schedule (NVT Langevin, fixed cell): melt at `--melt-temperature` (default 3000 K) for
  `--melt-ps` (10), cool linearly at `--quench-rate` (50 K/ps) to `--final-temperature`
  (300 K), anneal `--anneal-ps` (10); timestep `--timestep` 1 fs, friction `--friction`
  0.01/fs. Then positions and cell are relaxed (`--no-cell-relax` keeps the MD cell).
  Default: about 74 000 MD steps. `--samples N` runs N melt-quenches with different velocities.
- Needs forces: `uma` or `mace` (`emt` only for its metals and tests). `--calculator none`
  is refused (exit 2); `--dry-run` writes only `amorphous_bulk_initial.extxyz` and the schedule.
- Outputs: `amorphous_bulk_NNN.extxyz` (periodic bulk, no vacuum, no fixed atoms; pass as
  `--amorphous` to amorphous_slab, ald or amorphous_screen), the combined
  `amorphous_bulk_structures.extxyz`, `md/md_NNN.log` (temperature and energy every 100 steps),
  `md/md_NNN.extxyz` snapshots (`--trajectory-interval`), `amorphous_bulk_rdf.json` and
  `amorphous_bulk_manifest.json`.
- Diagnostics in the manifest: RMS displacement per element during the melt (a warning below
  1.5 A: perfect crystals superheat in MD, so raise the melt temperature or time),
  coordination-number distributions and RDF first peaks against the crystal supercell, and
  the energy relative to the relaxed crystal (`--no-crystal-reference` skips it). The
  structure depends on the potential, the temperature program and the quench rate; compare
  with experiment or DFT before use. Evidence: `mlip_predicted` (uma/mace) or
  `empirical_potential` (emt).

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
`genkai.modeling.surface.builders.slab` generator (conventional cell, termination checks, fixed
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

This is a production MLIP entry point (`--calculator uma`, default). Since
2026-11-16 it also has:

- `--calculator none`: mock contact score with zero forces, for local workflow
  tests only (energies have no physical meaning).
- `--task_name` defaults to `omat` and is checked against the installed fairchem
  before the model is loaded. The head must still be validated for the target system.
- `--fixed_fraction 0.5`: slabs without FixAtoms (CIF) get the bottom fixed
  before the relaxations; 0 disables.
- `--max_tilt DEG`: also samples a tilt (and its direction) of the cluster, so
  the face that points down is searched (irregular or amorphous clusters).
- `--placement_shape input`: place the cluster as supplied (e.g. an amorphous
  island) while the reference energy still comes from the relaxed isolated
  cluster.
- `--min_vacuum 10`: c is lengthened before the slab relaxation so the highest
  possible cluster keeps this vacuum to the next slab image.
- `--seed`: reproducible Optuna sampling.

## MLIP Screening Layer (SAM, Amorphous Surfaces, Interfaces, Islands)

End users configure existing environments once with `./install.sh` and `genkai.yaml`,
then use `./genkai check/run tasks/<method>.yaml`. Job files select a profile with
`mlip: default` or its name; they do not repeat backend paths or edit scripts.
The installer never installs MLIPs, PyTorch, CUDA or models. YAML methods now include
`sam_search`, `amorphous_surfaces`, `amorphous_interface` and `cluster_search`;
`slab`, `vacancy`, `adsorbate` opt into energies by selecting a profile.
See [the user configuration guide](../../../../docs/mlip-interfaces.md).

Energy model choice is shared (`genkai.modeling.surface.mlip.calculators`):
`none` (mock, local tests), `emt` (a few metals with H/C/N/O), `mace` or `uma` (real
MLIP; needs authorization). Compare only energies from the same model, task
head and settings, including the references; MLIP values are screening
estimates, not DFT evidence. The vacancy and adsorbate scripts also accept
`--fixed-fraction` (default 0.5) so CIF slabs do not relax as a whole.

All energy entry points now support MACE with `--mace-model` (or `MACE_MODEL`)
and `--mace-dtype float32|float64`. SAM and interface searches select it with
`--search-calculator mace`; other energy entry points use `--calculator mace`.
The checkpoint is local and no UMA task head is needed for MACE. Server launchers,
Python APIs and examples are documented in [MACE / UMA interfaces](../../../../docs/mlip-interfaces.md).

SAM energy search (`scripts/sam/sam_search.py`, `genkai.modeling.surface.screening.sam_search`):

```bash
python agents/Agent/skills/surface-modeling/scripts/sam/sam_search.py \
  --bulk SnO2.cif --molecule acid.cif --binding-mode bidentate \
  --search-calculator uma --task-name <head> --device cuda \
  --n-trials 40 --top-k 3 --coverage-counts 1,2,3 --output-dir sam_search
```

- References: E_slab (bottom fixed), E_mol (isolated, in a box), E_H2.
  E_ads(n) = E_total - E_slab - n E_mol (+ 1/2 E_H2 per removed acidic H).
- Stage 1: Optuna over the anchored parameters (site group, tilt, azimuth) of
  the chosen binding mode; each trial = geometric placement + `--screen-steps`
  relaxation; trials whose designed anchor/OH bonds break are penalized.
- Stage 2: `--top-k` distinct trials are fully relaxed and ranked.
- Coverage: the best relaxed molecule (with its transferred H) is copied by
  translation onto translation-equivalent site groups (sites and 4.5 A
  surroundings must match), then the whole layer is relaxed. Amorphous or
  low-symmetry surfaces have no equivalent sites and are refused.

Amorphous screening (`scripts/amorphous/amorphous_screen.py`, `genkai.modeling.surface.screening.amorphous_screen`):

```bash
# case 1: pure amorphous surfaces ranked by surface energy
python agents/Agent/skills/surface-modeling/scripts/amorphous/amorphous_screen.py surfaces \
  --amorphous a-SnO2.cif --periods 2 --samples 6 --calculator uma --task-name <head> --output-dir a_surfaces
# case 2: full amorphous film on a crystal, ranked by adhesion
python agents/Agent/skills/surface-modeling/scripts/amorphous/amorphous_screen.py interface \
  --bulk SnO2.cif --amorphous a-TiO2.cif --thickness 6 --n-matches 3 --n-trials 20 \
  --search-calculator uma --task-name <head> --output-dir a_interface
```

- `surfaces`: the amorphous bulk is relaxed (positions + cell) to get
  eps_bulk; windows of whole periods are scanned and only cuts that delete no
  isolated atom are kept (stoichiometric); each slab is (optionally annealed
  and) relaxed. gamma = (E - N eps_bulk)/2A with both faces free (default),
  or the fixed-bottom formula with `--fix-bottom`. Non-stoichiometric cuts get
  no gamma.
- `interface`: candidates are the best lattice matches (strained, seamless) or
  random rotations of a cut film when no match exists; per candidate Optuna
  searches the in-plane shift and the gap with short relaxations; the best is
  (optionally annealed, `--anneal-steps`) and fully relaxed. Candidates differ
  in atom count, so they are ranked by W_adh = (E_substrate + E_film -
  E_interface)/A.

Case 3, amorphous island on a crystal: `ald_overlayer.py --coverage partial`
writes `islands/island_NNN.extxyz` and `substrate_slab.extxyz`; then

```bash
python agents/Agent/skills/surface-modeling/scripts/cluster_search/ads_nanocluster.py \
  --surface ald/substrate_slab.extxyz --cluster ald/islands/island_000.extxyz \
  --placement_shape input --max_tilt 60 --calculator uma --task_name <head> --output_dir island_search
```

## Job Files For Other Users (`genkai-surface`)

People who do not work on the code use one command and a YAML job file instead of the
per-method CLIs above. The owner is `genkai.modeling.surface.app.jobs` (console script
`genkai-surface`, same as `python -m genkai.modeling.surface.app.jobs`); the user guide is
`docs/surface-modeling-user-guide.md` and runnable examples are in `examples/surface_jobs/`.

```bash
genkai-surface methods                    # open methods; `methods sam` lists every key
genkai-surface template sam -o job.yaml   # commented template
genkai-surface check job.yaml             # validate only
genkai-surface run job.yaml               # run, check structures, write manifest.json
```

- Structure generation: `slab`, `vacancy`, `adsorbate`, `cluster`, `sam`, `ald`, `amorphous_slab`.
  Without `mlip` the runner appends `--calculator=none` (and `--max-steps=0` or
  `--relax-steps=0` where they exist). Methods that need an MLIP profile from `genkai.yaml`:
  `sam_search`, `amorphous_surfaces`, `amorphous_interface`, `cluster_search` and
  `amorphous_bulk` (melt-quench; chain it with `amorphous_slab` in one `jobs:` file, see
  `examples/mlip_jobs/05_crystal_to_amorphous_slab.yaml`). Materials Project keys are rejected.
- Each job file key maps to one CLI flag through the option table in `jobs.py`; defaults
  and choices come from the method's own `_build_parser()`. When a method CLI changes,
  update the table; `tests/modeling/test_surface_jobs.py` fails on unknown flags.
- Every run writes `manifest.json` (`RunManifest`, one `StructureSetArtifact` per structure
  file, evidence `heuristic`), `job_resolved.yaml` and `run.log` into the job's output.

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
    "calculator": { "type": "enum", "required": false, "choices": ["none", "emt", "uma", "mace"] },
    "mace_model": { "type": "path", "required": false },
    "mace_dtype": { "type": "enum", "required": false, "choices": ["float32", "float64"] },
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
    "calculator in ['emt', 'uma', 'mace'] ranks facets up to max_index by surface energy",
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
    "calculator": { "type": "enum", "required": false, "choices": ["uma", "mace", "none"] },
    "mace_model": { "type": "path", "required": false },
    "mace_dtype": { "type": "enum", "required": false, "choices": ["float32", "float64"] },
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
    "calculator in ['uma', 'mace', 'none']",
    "calculator='uma' 使用 uma_model 和 device；calculator='mace' 使用本地 mace_model 或 MACE_MODEL"
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
    "calculator": { "type": "enum", "required": false, "choices": ["uma", "mace", "none"] },
    "mace_model": { "type": "path", "required": false },
    "mace_dtype": { "type": "enum", "required": false, "choices": ["float32", "float64"] },
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
    "calculator in ['uma', 'mace', 'none']"
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
    "calculator": { "type": "enum", "required": false, "choices": ["uma", "mace", "none"] },
    "mace_model": { "type": "path", "required": false },
    "mace_dtype": { "type": "enum", "required": false, "choices": ["float32", "float64"] },
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
    "真实计算需要所选的 MACE 或 UMA 环境及模型；calculator='none' 仅用于流程测试"
  ]
}
```
