# Slurm + SSHContext Example

**User request:** Run `run_simulation.sh` on a Slurm cluster for LiFePO4 relaxation. Load username from `$HPC_USER` and workspace path from `$HPC_WORKDIR`. Reuse `resource_defaults.json` for base compute settings; add the `debug` queue.

## `submission.template.json`

> ⚠️ **ALL paths (except `remote_root`) MUST be relative.** The remote Slurm node has NO access to your local `/home/kidd/...` paths.

```json
{
  "work_base": "LiFePO4_relax",
  "machine": {
    "batch_type": "Slurm",
    "context_type": "SSHContext",
    "remote_profile": {
      "hostname": "login.cluster.edu",
      "username": "${HPC_USER}",
      "port": 22
    },
    "remote_root": "${HPC_WORKDIR}/dpdisp_run"
  },
  "resources": {
    "$ref": "resource_defaults.json",
    "queue_name": "debug",
    "group_size": 1,
    "custom_flags": ["#SBATCH --job-name=relax-LiFePO4"]
  },
  "task_list": [
    {
      "command": "bash run_simulation.sh",
      "task_work_path": "relax_POSCAR_01",
      "forward_files": ["run_simulation.sh", "input.dat"],
      "backward_files": ["result.out", "log", "err"]
    }
  ]
}
```

## Commands

```bash
envsubst '${HPC_USER} ${HPC_WORKDIR}' < submission.template.json > submission.json
uv run -m json.tool submission.json >/dev/null
uvx --with dpdispatcher dargs check --allow-ref -f dpdispatcher.entrypoints.submit.submission_args submission.json
tmux new-session -d -s dpdisp_job "uvx --from dpdispatcher dpdisp submit --allow-ref submission.json"
tmux ls
```

Then poll until the tmux session exits and `relax_POSCAR_01/result.out`, `relax_POSCAR_01/log`, and `relax_POSCAR_01/err` exist locally (see "Monitoring a tmux Job" in SKILL.md).

### Key Points

| Aspect | Value | Why |
|--------|-------|-----|
| `work_base` | `"LiFePO4_relax"` | Relative! Project-level identifier |
| `task_work_path` | `"relax_POSCAR_01"` | Relative! NOT `/home/kidd/.../relax_POSCAR_01` |
| `command` | `"bash run_simulation.sh"` | No absolute paths! |
| `forward_files` | `["run_simulation.sh", "input.dat"]` | Just filenames, not full paths |
| `custom_flags` | `["#SBATCH --job-name=relax-LiFePO4"]` | Sets Slurm job name |
