---
name: vasp-pymatgen
description: VASP DFT skills using pymatgen.io.vasp.sets (MPRelaxSet, MPStaticSet, MPNonSCFSet). INCAR is driven by pymatgen MP defaults; the agent only supplies user_incar_settings overrides.
metadata:
  tools:
    - run_python
    - run_bash
    - load_skill_resource
  dependent_skills:
    - bohrium
  tags:
    - vasp
    - dft
    - relaxation
    - scf
    - band-structure
    - pymatgen
---

# VASP DFT Skill (pymatgen sets)

All input preparation uses `pymatgen.io.vasp.sets` (`MPRelaxSet`, `MPStaticSet`, `MPNonSCFSet`). These classes own the INCAR defaults — the agent only passes `user_incar_settings` to override individual keys. Never write a full INCAR dict from scratch.

> Load the reference file for the specific command you are about to run (see per-command pointers below).

**Prerequisite:** `PMG_VASP_PSP_DIR` must be set to the POTCAR library directory.

---

## Mandatory workflow sequence

1. **Obtain a structure** — generate or load from file.
2. **Prepare inputs** — run the appropriate snippet via `run_python`.
3. **Submit jobs** — pass `calc_dir_list` to the `bohrium` skill.
4. **Read results** — after the job finishes, run `read_results` or `collect_results`.

Run exactly **one property step at a time**. Do not chain relaxation + SCF in a single step.

---

## Commands

### prepare_relaxation
Structural relaxation with `MPRelaxSet`. Key params: `STRUCTURE_FILE`, `FRAMES`, `USER_INCAR`.
```
load_skill_resource(skill_name="vasp-pymatgen", path="references/relaxation.md")
```

### prepare_scf
Static SCF with `MPStaticSet`. Prefer `from_prev_calc(relax_dir)` when a relaxation dir is available; falls back to direct structure input. Add SOC keys to `USER_INCAR` when needed. Always outputs `CHGCAR`.
```
load_skill_resource(skill_name="vasp-pymatgen", path="references/scf.md")
```

### prepare_nscf_kpath
Band-structure NSCF with `MPNonSCFSet(mode="line")`. Uses `from_prev_calc(scf_dir)` — auto-copies `CHGCAR` and sets ICHARG=11. Key params: `SCF_DIRS`, `SOC`, `USER_INCAR`.
```
load_skill_resource(skill_name="vasp-pymatgen", path="references/nscf-kpath.md")
```

### prepare_nscf_uniform
DOS NSCF with `MPNonSCFSet(mode="uniform")`. Same pattern as kpath. Key params: `SCF_DIRS`, `SOC`, `USER_INCAR` (add `NEDOS` here).
```
load_skill_resource(skill_name="vasp-pymatgen", path="references/nscf-uniform.md")
```

### read_results
Parse `vasprun.xml` via `Vasprun`. Returns energy, forces, band gap, efermi, and (for nscf) band structure summary, etc.
```
load_skill_resource(skill_name="vasp-pymatgen", path="references/read-results.md")
```

---

## Submission

### `bohrium` skill (Recommended for Bohrium users)
Submit jobs to Bohrium using the `bohrium` skill, which wraps the `bohr` CLI. This is the recommended submission method for users running on the Bohrium platform.

For the full submission template and environment variables for VASP job on bohrium, see:

```
load_skill_resource(skill_name="vasp-pymatgen", path="references/bohr.md")
```

### `dpdisp` skill (Not recommended for Bohrium users)
Submission is handled by the `dpdisp` skill (DPDispatcher), which supports Both Bohrium and standard Slurm/HPC clusters. See the `dpdisp` skill documentation for full details and schema.
