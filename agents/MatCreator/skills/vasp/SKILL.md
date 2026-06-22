---
name: vasp
description: Skills for VASP DFT calculations — input preparation, remote submission to Bohrium, and result collection.
metadata:
  tools:
    - run_bash
    - run_skill_script
    - load_skill_resource
  dependent_skills:
    - bohrium
    - dpdisp
  tags:
    - vasp
    - dft
    - relaxation
    - scf
    - band-structure
    - dos
    - bohrium
---

# VASP DFT Skill


One script handles VASP-specific work; job submission is now delegated to the `dpdisp-submit` skill (DPDispatcher), which supports both Bohrium and standard Slurm/HPC clusters:

| Script | Role |
|---|---|
| `vasp_tools.py` | Prepare input files; collect / read results 

Use the `run_skill_script` tool to execute it:
- `skill_name`: `"vasp"`
- `script_name`: `"vasp_prepare.py"`
- `args`: the sub-command and flags as a single string

Every command prints JSON to stdout and exits 0 on success, 1 on error.

---
## Mandatory workflow sequence

1. **Obtain a structure** — if the user has not supplied one, generate it first.
2. **Prepare inputs** — run the appropriate `vasp_tools.py prepare_*` command.
3. **Submit jobs** — pass the returned `calc_dir_list` to the `dpdisp-submit` skill by generating a `submission.json`.
4. **Collect / read results** — after the job finishes, run `collect_results` or `read_results`.

Run exactly **one property step at a time**. Do not chain relaxation + SCF in a single step.

---

### prepare_relaxation

Prepare structural relaxation (IBRION=2, ISIF=3, NSW=200).

```
run_skill_script(skill_name="vasp", script_name="vasp_tools.py", args="prepare_relaxation \
    --structure <path.extxyz|path.vasp> \
    [--frames 0 1 2] \
    [--kpoints NX NY NZ] \
    [--incar_tags '{\"ENCUT\": 600}'] \
    [--potcar_map '{\"Bi\": \"Bi_d\"}']")
```

- `--structure`: structure file to read. Supported formats:
  - `*.extxyz` — may contain multiple frames; all frames are processed by default.
  - `*.vasp` (POSCAR format) — always contains exactly one frame.
- `--frames`: integer indices to process (extxyz only); default is all frames.
- `--kpoints`: explicit Gamma-centred mesh. Default: auto KPPRA density 40.

---

### prepare_scf

Prepare a self-consistent field calculation (NSW=0, IBRION=-1).

```
run_skill_script(skill_name="vasp", script_name="vasp_tools.py", args="prepare_scf \
    --structure <path.extxyz|path.vasp> \
    [--frames 0 1 2] \
    [--kpoints NX NY NZ] \
    [--soc] \
    [--incar_tags '{\"ENCUT\": 600}']")
```

- `--structure`: structure file to read. Supported formats:
  - `*.extxyz` — may contain multiple frames; all frames are processed by default.
  - `*.vasp` (POSCAR format) — always contains exactly one frame.
- `--frames`: integer indices to process (extxyz only); default is all frames.
- `--soc`: use `scf_soc` INCAR preset (ISPIN=2, LSORBIT=.TRUE.); default: `scf_nsoc`.
- Default k-mesh: auto KPPRA density 40.
- SCF outputs CHGCAR and WAVECAR when `LCHARG=true` / `LWAVE=true` (SOC preset only by default).

---

### prepare_nscf_kpath

Prepare a non-self-consistent band-structure calculation along a k-path.
Requires completed SCF directories that contain `CONTCAR` and `CHGCAR`.

```
run_skill_script(skill_name="vasp", script_name="vasp_tools.py", args="prepare_nscf_kpath \
    --scf_dirs <scf_dir1> [<scf_dir2> ...] \
    [--kpath GMKG] \
    [--n_kpoints 16] \
    [--soc] \
    [--incar_tags '{\"NBANDS\": 48}']")
```

- `--kpath`: explicit path string (e.g. `GMKG`). Default: auto from pymatgen `HighSymmKpath`.
- `--n_kpoints`: points per segment (default 16).
- Copies `CHGCAR` (and `WAVECAR` if present) from the SCF directory.

---

### prepare_nscf_uniform

Prepare a non-self-consistent uniform-mesh calculation (for DOS).
Requires completed SCF directories.

```
run_skill_script(skill_name="vasp", script_name="vasp_tools.py", args="prepare_nscf_uniform \
    --scf_dirs <scf_dir1> [<scf_dir2> ...] \
    [--kpoints NX NY NZ] \
    [--soc] \
    [--incar_tags '{\"NEDOS\": 2000}']")
```

- Default k-mesh: auto KPPRA density 100.
- Copies `CHGCAR` (and `WAVECAR` if present) from the SCF directory.

---

### collect_results

Parse `OUTCAR` files and write all frames into a single extxyz (via dpdata).

```
run_skill_script(skill_name="vasp", script_name="vasp_tools.py", args="collect_results \
    --dirs <calc_dir1> [<calc_dir2> ...]")
```

Returns:
```json
{ "status": "success", "scf_result": "<abs_path_to_scf_result.extxyz>" }
```

---

### read_results

Read `vasprun.xml` / `OUTCAR` and return key scalar results as JSON.

```
run_skill_script(skill_name="vasp", script_name="vasp_tools.py", args="read_results \
    --calc_type <relaxation|scf|nscf> \
    --calc_dir  <calc_dir>")
```

| calc_type | Returned fields |
|---|---|
| `relaxation` | `structure`, `total_energy`, `max_force`, `stress`, `ionic_steps` |
| `scf` | `structure`, `total_energy`, `efermi`, `band_gap`, `is_metal` |
| `nscf` | `structure`, `efermi`, `is_metal`, `band_gap`, `cbm`, `vbm` |

---


## Submission 
### `bohrium` skill (Recommended for Bohrium users)
Submit jobs to Bohrium using the `bohrium` skill, which wraps the `bohr` CLI. This is the recommended submission method for users running on the Bohrium platform.

### `dpdisp` skill (Not recommended for Bohrium users)
Submission is handled by the `dpdisp` skill (DPDispatcher), which supports Both Bohrium and standard Slurm/HPC clusters. See the `dpdisp` skill documentation for full details and schema.

For VASP job submission on Bohrium platform using DPDispatcher, see:
```
load_skill_resource(skill_name="vasp", path="references/bohrium-submission.md")
```

---

## Configuration file (config.yaml)

`config.yaml` lives in the Skill references directory. It controls:

- `work_dir` — where all calculation subdirectories are created (default `"vasp"`, resolved relative to the session directory).

- `VASP_default_INCAR` — one sub-key per preset (`relaxation`, `scf_nsoc`, `scf_soc`, `nscf_nsoc`, `nscf_soc`).

You can check the default INCAR settings by reading `config.yaml` with `load_skill_resource`:
```
load_skill_resource(skill_name="vasp", path="references/config.yaml")
```

To override individual tags for a single run without editing the file, use `--incar_tags` when running `prepare_*` sub-commands of the `vasp_tools.py` script. 

```bash
--incar_tags '{"ENCUT": 600, "EDIFF": 1e-6}'
```

