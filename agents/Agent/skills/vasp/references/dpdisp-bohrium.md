# VASP Bohrium Submission Reference

## Required environment variables

| Variable | Description |
|---|---|
| `BOHRIUM_EMAIL` | Bohrium account e-mail |
| `BOHRIUM_PASSWORD` | Bohrium account password |
| `BOHRIUM_PROJECT_ID` | Bohrium project ID (integer) |
| `BOHRIUM_VASP_MACHINE` | Machine/scass type, e.g. `c32_m128_cpu` |
| `BOHRIUM_VASP_IMAGE` | Container image URI for VASP |

## Example submission.json

Bohrium uses `remote_profile` with an `input_data` sub-object. The `scass_type`, `image_name`, `platform`, and `job_type` fields go inside `input_data`.

```json
{
    "work_base": ".",
    "machine": {
        "batch_type": "Bohrium",
        "context_type": "BohriumContext",
        "local_root": ".",
        "remote_profile": {
            "email": "${BOHRIUM_EMAIL}",
            "password": "${BOHRIUM_PASSWORD}",
            "program_id": ${BOHRIUM_PROJECT_ID},
            "input_data": {
                "job_type": "container",
                "log_file": "log",
                "scass_type": "${BOHRIUM_VASP_MACHINE}",
                "platform": "ali",
                "image_name": "${BOHRIUM_VASP_IMAGE}"
            }
        }
    },
    "resources": {
        "group_size": 4
    },
    "task_list": [
        {
            "command": "source /opt/intel/oneapi/setvars.sh && mpirun -n 32 vasp_std",
            "task_work_path": "<calc_dir>",
            "forward_files": ["POSCAR", "INCAR", "POTCAR", "KPOINTS"],
            "backward_files": ["OSZICAR", "CONTCAR", "OUTCAR", "vasprun.xml", "log", "err"]
        }
    ]
}
```

For SCF/NSCF, add `CHGCAR` (and `WAVECAR` for SOC) to `forward_files`/`backward_files` as needed.

For Slurm, set `batch_type` to `Slurm`, `context_type` to `SSHContext`, and fill in SSH and resource fields (see `dpdisp-submit` skill docs).

## Submission flow

1. Generate `submission.template.json` as above, using `${VARNAME}` for any environment variables.
2. Substitute variables:
   ```bash
   envsubst '${BOHRIUM_EMAIL} ${BOHRIUM_PASSWORD} ${BOHRIUM_PROJECT_ID} ${BOHRIUM_VASP_MACHINE} ${BOHRIUM_VASP_IMAGE}' < submission.template.json > submission.json
   ```
3. Validate and submit:
   ```bash
   uv run -m json.tool submission.json >/dev/null
   uvx --with dpdispatcher dargs check -f dpdispatcher.entrypoints.submit.submission_args submission.json
   uvx --from dpdispatcher --with oss2 dpdisp submit submission.json
   ```

> **Note:** Always use `--with oss2` for Bohrium jobs. `oss2` (Aliyun OSS SDK) is required by `BohriumContext` but is not bundled with dpdispatcher in uvx isolated environments. Omitting it causes `NameError: name 'oss2' is not defined`.
