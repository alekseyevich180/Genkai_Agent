# LAMMPS Bohrium Submission Reference

## Required environment variables

| Variable | Description |
|---|---|
| `BOHRIUM_EMAIL` | Bohrium account e-mail |
| `BOHRIUM_PASSWORD` | Bohrium account password |
| `BOHRIUM_PROJECT_ID` | Bohrium project ID (integer) |
| `BOHRIUM_DEEPMD_MACHINE` | Machine/scass type, e.g. `c32_m128_cpu` |
| `BOHRIUM_DEEPMD_IMAGE` | Container image URI — includes LAMMPS, default: `registry.dp.tech/dptech/deepmd-kit:3.1.3` |
| `DEEPMD_MODEL_PATH` | Default pretrained DPA3 model path |

> The Bohrium DeepMD image (`registry.dp.tech/dptech/deepmd-kit`) already includes LAMMPS — no separate installation is needed.

## Example submission.template.json

```json
{
  "work_base": "<job_dir>",
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
        "scass_type": "${BOHRIUM_DEEPMD_MACHINE}",
        "platform": "ali",
        "image_name": "${BOHRIUM_DEEPMD_IMAGE}"
      }
    }
  },
  "resources": { "group_size": 1 },
  "task_list": [
    {
      "command": "lmp -in in.lammps",
      "task_work_path": ".",
      "forward_files": ["in.lammps", "conf.lmp", "frozen_model.pth"],
      "backward_files": ["log.lammps", "traj.dump", "job_config.json", "log", "err"]
    }
  ]
}
```

## Submission flow

1. Generate `submission.template.json` as above, using `${VARNAME}` for environment variables.
2. Substitute variables:
   ```bash
   envsubst '${BOHRIUM_EMAIL} ${BOHRIUM_PASSWORD} ${BOHRIUM_PROJECT_ID} ${BOHRIUM_DEEPMD_MACHINE} ${BOHRIUM_DEEPMD_IMAGE}' \
       < submission.template.json > submission.json
   ```
3. Validate and submit:
   ```bash
   uv run -m json.tool submission.json >/dev/null
   uvx --with dpdispatcher dargs check -f dpdispatcher.entrypoints.submit.submission_args submission.json
   uvx --from dpdispatcher --with oss2 dpdisp submit submission.json
   ```

> **Note:** Always use `--with oss2` for Bohrium jobs. `oss2` (Aliyun OSS SDK) is required by `BohriumContext` but is not bundled with dpdispatcher in uvx isolated environments.

For long-running MD jobs, wrap in `tmux`:

```bash
tmux new-session -d -s lammps_md \
    "uvx --from dpdispatcher --with oss2 dpdisp submit submission.json"
tmux ls
```

## Multi-job submission (all frames)

When `--frame -1` produces multiple job directories, submit each independently with `work_base` set to the individual `job_dir`, or list each as a separate task in `task_list`.
