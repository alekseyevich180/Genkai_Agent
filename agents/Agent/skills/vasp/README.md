# VASP Skill — Setup Guide

## 1. Configure the POTCAR directory (pymatgen)

`vasp_tools.py` uses **pymatgen** to generate POTCAR files automatically.
pymatgen needs to know where your pseudopotential library (`potpaw_PBE` or similar) lives.

### Expected directory layout

```
/path/to/potpaw_PBE/
    Cu/POTCAR
    Al/POTCAR
    Fe/POTCAR
    ...
```

The variable `PMG_VASP_PSP_DIR` must point to the **parent** of the functional-family
folder (i.e. the directory that *contains* `potpaw_PBE/`, not `potpaw_PBE/` itself).

### Option A — pymatgen config file (recommended, persistent)

```bash
pmg config --add PMG_VASP_PSP_DIR /path/to/potpaw_PBE
```

This writes the setting to `~/.config/pymatgen/config.yaml` and is picked up
automatically on every run.

### Option B — environment variable (session / `.env`)

Add the line to your shell or to the `.env` file next to the scripts:

```dotenv
PMG_VASP_PSP_DIR=/path/to/potpaw_PBE
```

> **Example:** if your POTCAR for copper is at
> `/home/user/pbe/potpaw_PBE/Cu/POTCAR`, set
> `PMG_VASP_PSP_DIR=/home/user/pbe/potpaw_PBE`.

---

## 2. VASP-related variables in `.env`

Create or edit the `.env` file in the same directory as `vasp_tools.py` and
`bohrium_submit.py`. The table below lists every relevant variable.

| Variable | Required | Example | Description |
|---|---|---|---|
| `PMG_VASP_PSP_DIR` | Yes | `/home/user/pbe/potpaw_PBE` | Path to the pymatgen POTCAR library (see §1) |
| `BOHRIUM_USERNAME` | Yes | `you@example.com` | Bohrium account e-mail |
| `BOHRIUM_PASSWORD` | Yes | `yourpassword` | Bohrium account password |
| `BOHRIUM_PROJECT_ID` | Yes | `29496` | Bohrium project ID (integer) |
| `BOHRIUM_VASP_IMAGE` | Yes | `registry.dp.tech/dptech/prod-15454/vasp:5.4.4` | Container image used to run VASP on Bohrium |
| `BOHRIUM_VASP_MACHINE` | Yes | `c16_m32_cpu` | Bohrium machine type (CPU cores × memory) |
| `BOHRIUM_VASP_COMMAND` | No | `source /opt/intel/oneapi/setvars.sh && mpirun -n 16 vasp_std` | Shell command executed inside the container; overrides the built-in default |

### Minimal `.env` example

```dotenv
# Pseudopotential library
PMG_VASP_PSP_DIR=/home/user/pbe/potpaw_PBE

# Bohrium credentials & job settings
BOHRIUM_USERNAME=you@example.com
BOHRIUM_PASSWORD=yourpassword
BOHRIUM_PROJECT_ID=12345
BOHRIUM_VASP_IMAGE=registry.dp.tech/dptech/prod-15454/vasp:5.4.4
BOHRIUM_VASP_MACHINE=c16_m32_cpu
```

### Notes

- `BOHRIUM_VASP_MACHINE` controls how many CPU cores are available.
  Common choices: `c16_m32_cpu`, `c32_m64_cpu`, `c64_m256_cpu`.
  Match the core count to the `-n` argument in `BOHRIUM_VASP_COMMAND`.
- `BOHRIUM_VASP_IMAGE` must be a VASP-licensed image you have access to on the
  Bohrium platform.
- LLM variables (`LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL`) are agent-level
  settings and are **not** required by the VASP scripts themselves.
