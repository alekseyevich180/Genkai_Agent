---
name: dpdisp
description: Run Shell commands as computational jobs, on local machines or HPC clusters, through Shell, Slurm, PBS, LSF, Bohrium, etc. USE WHEN the user needs to submit batch jobs to a cluster, run commands on a remote server, execute tasks via job schedulers (Slurm, PBS, LSF), or safely run long-term/background shell commands that require state tracking and auto-recovery.
metadata:
  tools:
    - run_bash
  tags:
    - dpdispatcher
    - bohrium
    - hpc
    - slurm
---

# dpdisp-submit

This skill uses the DPDispatcher tool to run Shell commands as computational jobs, on local machines or HPC clusters, through Shell, Slurm, PBS, LSF, Bohrium, etc.

## Agent responsibilities

1. Collect enough information from the user in plain language.
1. **Determine a meaningful job name** based on the task content and attributes (see "Task and Job Naming Convention" below).
1. Generate the submission JSON file based on collected user input, **with descriptive names applied to `task_work_path`, `work_base`, and job names**.
1. Validate `submission.json` before submission.
1. Submit with `uvx --from dpdispatcher dpdisp submit submission.json`.
1. **Submit the job** via `dpdisp submit`, then **monitor every 10 minutes** until completion — report job status at each check. Never declare the step complete at submission time; the step is only complete when ALL output files have been downloaded locally.
1. Automatically manage job interruptions and retries by relying on built-in state tracking (see the "Resuming Jobs" section for details).
1. **CRITICAL SECURITY CONSTRAINT: DO NOT attempt direct SSH connections.** Never attempt to connect to the remote HPC directly using `ssh`, write custom Paramiko/Fabric Python scripts, or manually execute remote commands. Just generate the `submission.json` and use the `dpdisp submit` tool. DPDispatcher will handle all remote connections, file transfers, and job management safely.

## CRITICAL: Path Handling for Remote Jobs

**This is the #1 cause of remote job failures. Read carefully.**

When a job runs on a **remote machine** (Bohrium container, Slurm node, SSH host, etc.), dpdispatcher generates a shell script that does:

```bash
cd $REMOTE_ROOT          # e.g., /home/input_lbg-11505-22729659/
cd {task_work_path}      # ← MUST be a relative path!
... execute command ...
```

### THE RULE: Every path in `submission.json` MUST be relative

| Field | Must be relative? | Example (CORRECT) | Example (WRONG — will fail!) |
|-------|-------------------|-------------------|------------------------------|
| `work_base` | ✅ YES | `"LiFePO4_relax"` | `"/home/kidd/PFD_Agent/.../vasp"` |
| `task_work_path` | ✅ YES | `"relax_01"`, `"."` | `"/home/kidd/.../20260523124231_601685"` |
| `forward_files` | ✅ YES | `["run.sh", "INCAR", "POSCAR"]` | `["/home/kidd/.../run.sh"]` |
| `backward_files` | ✅ YES | `["OUTCAR", "log", "err"]` | `["/home/kidd/.../OUTCAR"]` |
| `command` paths | ✅ YES | `"bash run.sh"`, `"mpirun vasp"` | `"cd /home/kidd/... && mpirun vasp"` |
| `local_root` | Can be absolute | `"."` or `"/tmp/project"` | — |
| `remote_root` | Can be absolute | `"${HPC_WORKDIR}/jobs"` | — |
| `outlog` / `errlog` | ✅ YES (filenames only) | `"log"`, `"err"` | `"/home/kidd/.../log"` |

### Why absolute local paths fail

The remote machine (Bohrium container, HPC node) has **its own filesystem**. It has NO access to your local machine's filesystem at `/home/kidd/...`. When dpdispatcher generates `cd /home/kidd/PFD_Agent/...`, the remote shell can't find that directory and the job fails immediately with:

```
.sub.run: line 3: cd: /home/kidd/PFD_Agent/...: No such file or directory
```

### How file staging works (you don't need absolute paths)

dpdispatcher handles file transfer automatically:
1. Files listed in `forward_files` are uploaded from `local_root/work_base/task_work_path/` to the remote
2. The command runs inside `$REMOTE_ROOT/work_base/task_work_path/` on the remote
3. Files listed in `backward_files` are downloaded back after completion

**The command only needs to reference files by their relative names** — dpdispatcher ensures they are present in the working directory on the remote.

### Self-check before submitting (MANDATORY for remote jobs)

Before generating the final `submission.json`, verify:
1. ✅ `work_base` contains NO slashes at the start (not absolute)
2. ✅ `task_work_path` contains NO slashes at the start (not absolute)  
3. ✅ `command` contains NO absolute paths (no `/home/`, `/tmp/`, etc.)
4. ✅ All `forward_files` and `backward_files` are relative filenames
5. ✅ `outlog` and `errlog` are simple filenames (e.g., `"log"`, `"err"`)

## Task and Job Naming Convention

**Every task and job MUST have a human-readable, context-aware name** that reflects what the job actually does. Never use generic names like `task_000`, `task_001`, `dpdisp_job`, or hash-only identifiers without a descriptive prefix.

### Naming Rules

1. **Derive names from task attributes**: material, method, temperature, pressure, composition, calculation type, etc.
   - Good: `relax_LiFePO4`, `md_300K_1bar`, `scf_NaCl_bcc`, `train_DPA2_AlMgSi`
   - Bad: `task_000`, `job1`, `run`, `test`

2. **`work_base`**: A short project-level identifier (e.g., `LiFePO4_phonon`, `Cu_surface_adsorption`). This becomes the top-level working directory on the remote side and is visible in most batch system UIs.

3. **`task_work_path`**: A descriptive per-task directory name (e.g., `relax_POSCAR_001`, `md_NVT_300K`, `scf_mag_Fe`). For multi-task submissions, use a systematic naming scheme with a shared prefix.

4. **Job name (batch-system visible)**: Set explicitly via backend-specific mechanisms:
   - **Slurm**: Use `resources.custom_flags` to inject `#SBATCH --job-name=<name>`
   - **PBS/SGE**: Use `resources.kwargs.job_name` (already supported natively)
   - **Bohrium**: Pass `job_name` in `remote_profile.input_data`
   - **Shell/Local**: Job name is less visible, but `task_work_path` still serves as the identifier

### Naming format

```
<action>_<material>[optional:_<condition>]
```

Examples by task type:
| Task Type | `work_base` | `task_work_path` | Slurm `job_name` |
|-----------|-------------|------------------|------------------|
| VASP relax | `LiFePO4_bulk` | `relax_POSCAR_01` | `relax-LiFePO4-01` |
| VASP SCF | `Fe_magnetic` | `scf_bcc_Fe` | `scf-bcc-Fe` |
| MD NVT | `H2O_256mol` | `md_NVT_300K` | `md-NVT-300K` |
| DeepMD train | `AlMgSi_DPA2` | `train_run01` | `train-AlMgSi-01` |
| Phonon calc | `NaCl_phonon` | `phonon_2x2x2` | `phonon-NaCl-222` |

> **Important**: Keep names under 30 characters to avoid issues with batch system limits (Slurm's `--job-name` max is typically 15 chars for some versions, so prefer shorter names when in doubt — strip to core: e.g. `relax-LiFePO4`).

## Autonomous Information Gathering & User Prompts

Before this step, always execute `uvx --with dpdispatcher dargs doc dpdispatcher.entrypoints.submit.submission_args` to learn what information needs to be filled.

If information is missing, ask questions users can understand, for example:

- Where should this run: your local machine or a remote HPC cluster?
- Are there any existing configuration files?
- Is any sensitive information in the environment variables?
- What shell command should be executed?
- How many CPUs/GPUs/nodes do you need?
- Which queue/partition/account should we use (if applicable)?
- Which input files should be uploaded, and which output files should be collected?
- **What is a good descriptive name for this task?** (material, method, conditions)

## Generate `submission.json` from user input

According the result of `uvx --with dpdispatcher dargs doc dpdispatcher.entrypoints.submit.submission_args`, translate user answers into:

- `machine` (where/how to run),
- `resources` (compute resources, **including `custom_flags` for job naming**),
- `task_list` (which shell commands/files to run, with **descriptive `task_work_path`**).

**Always apply the naming convention**: set `work_base` to a project-level name, `task_work_path` to a per-task descriptive name, and inject the job name via the backend-specific mechanism.

**ALWAYS apply the path rules**: every path in `submission.json` (except `local_root` and `remote_root`) must be relative. See "CRITICAL: Path Handling for Remote Jobs" above.

### Job Naming per Backend

#### Slurm
```json
"resources": {
  "custom_flags": ["#SBATCH --job-name=relax-LiFePO4"],
  ...
}
```

#### PBS / SGE
```json
"resources": {
  "kwargs": {"job_name": "relax-LiFePO4"},
  ...
}
```

#### Bohrium
```json
"remote_profile": {
  "input_data": {
    "job_name": "relax-LiFePO4",
    ...
  }
}
```

#### Shell / LazyLocal
No batch-system job name; rely on descriptive `task_work_path` and `work_base`.

If the user indicates that a specific value (like a username, token, or remote path) should be read from a local environment variable, format that value in the JSON template as `${ENV_VAR_NAME}`.
*Example:* `"remote_root": "${USER_HPC_WORKSPACE}"`

### Handling Environment Variables

If the user specifies values that must be loaded from local environment variables (e.g., sensitive tokens, dynamic paths), do **not** write them directly into the final JSON. Instead:

1. Generate a `submission.template.json` file using the `${VAR_NAME}` syntax **only for the variables you intend to substitute**.
1. Use `envsubst` with an explicit variable list to inject only those variables and create the final file:
   `envsubst '${USER_HPC_WORKSPACE}' < submission.template.json > submission.json`
1. **CRITICAL SECURITY CONSTRAINT: DO NOT read or print the contents of the newly generated `submission.json` file.** Once `envsubst` replaces the variables, the file contains raw sensitive data.

If multiple environment variables are needed, list them all explicitly:
`envsubst '${USER_HPC_WORKSPACE} ${USER_OTHER_VAR}' < submission.template.json > submission.json`
If no environment variables are needed, simply generate `submission.json` directly.

### Simple local shell tasks

When the user asks for a simple local shell task, prefer these defaults to avoid common failures:

- `machine.context_type = "LazyLocalContext"`
- `machine.batch_type = "Shell"`
- `task_list[0].task_work_path = "."` (avoid non-existing subdirectory failures)
- `resources.group_size = 1`
- Still apply a descriptive `work_base` (e.g., `"local_test"`, `"preprocess_data"`)

## Required commands

### Core Flow

```bash
# 1) Print full submission schema
uvx --with dpdispatcher dargs doc dpdispatcher.entrypoints.submit.submission_args

# 2) [Optional] Substitute environment variables if a template was generated
envsubst '${USER_VAR} ${USER_OTHER_VAR}' < submission.template.json > submission.json

# 3) Syntax check JSON
uv run -m json.tool submission.json >/dev/null

# 4) Validate generated submission.json
uvx --with dpdispatcher dargs check -f dpdispatcher.entrypoints.submit.submission_args submission.json

# 5) Submit (wrap in tmux for long-running jobs)
tmux new-session -d -s dpdisp_job "uvx --from dpdispatcher dpdisp submit submission.json"

# If using Bohrium/DP Cloud (context_type: BohriumContext), add --with oss2:
tmux new-session -d -s dpdisp_job "uvx --from dpdispatcher --with oss2 dpdisp submit submission.json"
```

### Monitoring Remote Jobs (MANDATORY)

After submitting a remote job via tmux, you **MUST** monitor it at **10-minute intervals** until completion. At each check, report the current status to the user.

```bash
# Poll every 600 s (10 min); report status at each check
CHECK=0
while tmux has-session -t dpdisp_job 2>/dev/null; do
  CHECK=$((CHECK + 1))
  echo "[Check #${CHECK}] Job still running... $(date)"
  # Optionally check remote job status if the backend provides a CLI:
  # (e.g., for Bohrium: check via API; for Slurm: ssh squeue -j <job_id>)
  sleep 600
done
echo "[$(date)] tmux session ended — job finished on remote side"

# Read captured output to check for errors
tmux capture-pane -t dpdisp_job -p 2>/dev/null || true

# Verify expected backward_files exist locally (adjust paths as needed)
ls -lh <task_work_path>/log <task_work_path>/err 2>/dev/null && echo "Outputs present" || echo "WARNING: outputs missing"
```

**At each 10-minute check, report to the user:**
- How long the job has been running
- Current status (still running / finished / error)
- Any visible progress indicators (log tail, iteration count, etc. if available)

Only after the session has exited **and** the expected output files exist is the job truly complete. If outputs are missing after the session ends, re-run `dpdisp submit` to resume (see "Resuming Jobs").

### More Useful Flags

- **`--dry-run`**: Parses the configuration and validates the schema without submitting. Useful for a final safety check.
- **`--allow-ref`**: Required when `submission.json` uses `{"$ref": "other.json"}` for reusable config snippets. Pass it to **all** related commands (`dargs check` and `dpdisp submit`).

## Completion criteria

A job is **fully completed** only when **both** of the following are true:

- The backend tasks have finished successfully.
- All required output files (e.g., `log`, `err`, result files) have been retrieved to the local `task_work_path`.

Submitting a job is **not** completing it. Never call `submit_step_result` with `status=success` until outputs are present locally.

## Resuming Jobs (Failure Handling & Recovery)

DPDispatcher is inherently idempotent and features built-in state tracking. It will automatically resume unfinished tasks without duplicating completed ones.

**When to trigger recovery:**

- A job fails, times out, or gets unexpectedly interrupted.
- The user explicitly asks to "resume", "retry", or "recover" a previously interrupted or failed job.
- The Agent's SSH or network connection drops during job monitoring.

**Action:** Do **NOT** modify `submission.json` or attempt to clean up the remote directories. Simply re-execute the exact same submission command in the same directory. The tool will safely skip successful tasks and only resubmit or resume the pending/failed ones.

## What to report back to the user

**At submission time:**
- A short summary of what the user asked for (where to run, command, resources).
- The descriptive job name and task work path used.
- Confirmation that the job has been submitted and monitoring has begun.

**At each 10-minute monitoring check:**
- How long the job has been running.
- Current status (still running / finished / error).
- Any visible progress from recent log output.

**At completion:**
- Final status (success / failure).
- Output locations (for example `log` and `err` when `task_work_path` is `.`).
- If the job encounters an interruption or partial failure, provide the user with detailed information and offer to re-run the command to resume the unfinished tasks.


## Examples

For full worked examples with complete JSON templates and commands, load the reference files:

- **Slurm + SSHContext:** `load_skill_resource(skill_name="dpdisp", path="references/slurm-example.md")`
- **Bohrium (DP Cloud):** `load_skill_resource(skill_name="dpdisp", path="references/bohrium-example.md")`

- A short summary of what the user asked for (where to run, command, resources).
- The descriptive job name and task work path used.
- Submission status (started/running/finished/failed).
- Output locations (for example `log` and `err` when `task_work_path` is `.`).
- If the job encounters an interruption or partial failure, provide the user with detailed information and offer to re-run the command to resume the unfinished tasks.
