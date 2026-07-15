# s41563-025-02134-9 workflow test

This directory is the compact output of the paper-to-modeling workflow for:

> Ultrafine metal nanoparticles isolated on oxide nano-islands as exceptional
> sintering-resistant catalysts (Nature Materials, 2025)

## Contents

- `article.json`: compact paper extraction result.
- `modeling/plan.json`: automatically generated PToModel task and parameter plan.
- `modeling/checklist.json`: unresolved inputs and provenance checks.
- `modeling/structures/cluster_bulk_from_materials_project.cif`: Ru bulk reference
  downloaded from Materials Project (`mp-33`, `P6_3/mmc`) using `MP_API_KEY`
  loaded from `agents/Agent/.env`.
- `modeling/structures/Ru_hcp_r7.cif`: hcp Ru cluster generated with a 7 A radius
  from the Materials Project bulk reference.
- `modeling/structures/Ru_hcp_r7.xyz`: non-periodic Cartesian representation of
  the same 135-atom cluster for direct inspection.
- `modeling/structures/modeling_manifest.json`: generated structure provenance;
  no API key is persisted.

## Interpretation limits

The paper reports Ru nanoparticles with a mean diameter of 1.4 nm, so the test
uses a 7 A cluster radius. The paper describes LaOx nano-islands as amorphous and
does not provide an unambiguous SiO2 surface facet or an atomistic LaOx/SiO2
interface. Therefore, this test does not fabricate a full Ru/LaOx-SiO2 interface.

The automatic plan currently mistakes `LaOx clusters` for an elemental La metal
cluster in the `surface_cluster_builder` arguments. The Materials Project
structure generated in this test deliberately uses Ru, which is the metal
nanoparticle explicitly reported by the paper.

## Validation

- Materials Project download: successful.
- Selected Ru entry: `mp-33`, `P6_3/mmc` (hcp).
- Generated cluster: 135 Ru atoms; maximum construction radius 6.999 A.
- API-key scan of the output directory: no key found.
- Regression tests: 31 passed (`tests.test_surface_mp_workflow` and
  `tests.test_paperread_surface`).
