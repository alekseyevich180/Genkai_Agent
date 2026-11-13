# Paper-to-model workflow test

This directory extends the PDF extraction/PToModel output into executable starting
structures. It is a pathway test, not a stability, adsorption-energy, or catalytic
activity calculation.

## Evidence from the paper

- Catalyst: CeO2-supported Ni(0) nanoparticles (`Ni/CeO2-NaNaph`)
- Model substrate: 4-methylcyclohexanone
- Mechanistic cue: simultaneous/multiple Ni active sites (metal ensembles)
- Main reaction conditions: DMA, Ar (1 atm), 180 °C, 24 h
- Ni content: 1.38 wt%; about 76% of Ni species were assigned as zero-valent

## Explicit demonstration assumptions

- `CeO2(111)` is selected as a conventional stable ceria surface; the paper does
  not report a facet.
- `Ni13` and the fcc motif are test choices; the paper reports highly dispersed or
  ultrasmall Ni nanospecies but no atom count or resolved particle structure.
- A two-Ni site group is used as an operational representation of a metal ensemble.
- Placement coordinates, vertical gap, sampling counts, and coverage patterns are
  workflow defaults, not paper-derived parameters.
- The adsorbate landscape uses `calculator=none`; its simulated energies are only
  for testing data flow and must not be interpreted physically.

## Path exercised

```text
PDF -> text/section routing -> conditions + relations -> summary/experience
-> PToModel -> CeO2(111) artifact resolution -> fcc-Ni13 placement
-> 4-methylcyclohexanone structure -> two-Ni-site coverage enumeration
```

The source surface artifact is
`agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif`.
