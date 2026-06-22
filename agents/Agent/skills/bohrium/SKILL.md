---
name: bohrium
description: Submit and manage computational jobs on Bohrium (bohrium.com) cloud platform using bohr CLI. Recommended for submission methods on Bohrium.
metadata:
  tools:
    - run_bash
  tags: [bohrium, hpc, job-submission, cloud-computing]
---

# Bohrium Cloud Job Management

Submit and manage computational jobs on [Bohrium](https://bohrium.com) cloud platform via `bohr` CLI.

## Prerequisites

### 1. Install bohr CLI

- **Windows**: Download from https://bohrium.com/download, place in PATH
- **Linux/macOS**: `curl -fsSL https://bohrium.com/download/bohr | sh`

Verify: `bohr version`

### 2. Login

```bash
bohr login
# Enter email and password interactively
# Token saved to ~/.bohrium/credentials.yaml
```

### 3. Get your project ID

```bash
bohr project list --json
# Note the project ID you want to use
```

## Machine Types (Reference)

Bohrium offers CPU and GPU machines. **Always check current availability with `bohr node list`** — pricing and inventory change.

### CPU Machines

Format: `c{cores}_m{mem}_cpu` (some have `_H` suffix for high-performance)

| Range | Examples | Price (CNY/h) |
|-------|----------|---------------|
| 2C | c2_m2_cpu ~ c2_m16_cpu | 0.16-0.20 |
| 4C | c4_m4_cpu ~ c4_m32_cpu | 0.32-0.40 |
| 8C | c8_m8_cpu ~ c8_m64_cpu | 0.64-0.80 |
| 12C | c12_m12_cpu ~ c12_m96_cpu | 0.96-1.20 |
| 16C | c16_m16_cpu ~ c16_m128_cpu | 1.28-1.60 |
| 24C | c24_m24_cpu ~ c24_m192_cpu | 1.92-2.40 |
| 32C | c32_m32_cpu ~ c32_m256_cpu | 2.56-3.20 |
| 48C | c48_m176_cpu ~ c48_m384_cpu | 3.84-4.80 |
| 52C | c52_m96_cpu ~ c52_m384_cpu | 4.16 |
| 56C | c56_m160_cpu ~ c56_m224_cpu | 4.48 |
| 64C | c64_m64_cpu ~ c64_m512_cpu | 5.12-7.68 |
| 72C | c72_m288_cpu | 7.20 |
| 96C | c96_m192_cpu ~ c96_m384_cpu | 9.60-11.52 |
| 128C | c128_m512_cpu | 12.80 |

Check current machines:
```bash
bohr node list
```

### GPU Machines

Format: `c{cores}_m{mem}_{count} * {GPU_MODEL}` or `{count} * {GPU_MODEL}_{vram}g` (GPU-only)

Available GPU types:

| GPU | VRAM | Price Range (CNY/h) | Configs |
|-----|------|---------------------|---------|
| NVIDIA T4 | 16GB | 2.5-12.0 | 10 |
| NVIDIA V100 | 16/32GB | 4.5-36.0 | 18 |
| NVIDIA A100 | 40/80GB | 10.0-80.0 | 4 |
| NVIDIA 3090 | 24GB | 4.5-36.0 | 4 |
| NVIDIA 4090 | 24GB | 5.5-44.0 | 5 |
| NVIDIA 5090 | 32GB | 1.9 | 1 |
| NVIDIA L4 | 24GB | 5.0-20.0 | 3 |
| NVIDIA L20 | 48GB | 8.0-64.0 | 4 |
| NVIDIA P100 | 16GB | 4.0-32.0 | 4 |
| DCU | 16GB | 1.2-6.0 | 8 |
| FPGA | - | 8.0 | 2 |

**GPU-only vs CPU+GPU**: Entries like `1 * NVIDIA V100_32g` are GPU-only (no CPU/RAM). Entries like `c12_m64_1 * NVIDIA L4` bundle CPU+RAM+GPU. Choose based on your workload's CPU needs.

## Job Submission

### Core command

```bash
bohr job submit \
  --project_id "YOUR_PROJECT_ID" \
  --job_name "job-name" \
  --machine_type "c8_m32_cpu" \
  --image_address "registry.dp.tech/dptech/lammps:2023.08.02" \
  --input_directory "./" \
  --backward_files "output.txt,results.log" \
  --command "your command here"
```

### Key parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--project_id` | Your Bohrium project ID | `"12345"` |
| `--job_name` | Job display name | `"Cu-EOS-test"` |
| `--machine_type` | Machine SKU | `"c8_m32_cpu"` |
| `--image_address` | Docker image URI | `"registry.dp.tech/dptech/lammps:2023.08.02"` |
| `--input_directory` | Local dir to upload as job input | `"./"` |
| `--backward_files` | Comma-separated output files to retrieve | `"OUTCAR,vasprun.xml"` |
| `--job_group_id` | Job group ID for batch tracking | `"67890"` |
| `--command` | Command to run | `"mpirun -np 8 lmp -in in.lammps"` |
| `--log_file` | Log file path inside the job | `"run.log"` |
| `--max_run_time` | Max runtime in minutes | `120` |
| `--nnode` | Number of nodes (default 1) | `1` |
| `--max_reschedule_times` | Auto-retry count on failure | `3` |

### Common Docker images

| Image | Use Case |
|-------|----------|
| `registry.dp.tech/dptech/lammps:2023.08.02` | LAMMPS MD simulations |
| `registry.dp.tech/dptech/deepmd-kit:3.1.3` | LAMMPS + DeePMD-kit |
| `registry.dp.tech/dptech/vasp:5.4.4` | VASP DFT calculations |
| `registry.dp.tech/dptech/gromacs:2023` | GROMACS MD |
| `registry.dp.tech/dptech/python:3.10` | General Python |
| `ubuntu:22.04` | Base OS, install your own |

Find more: https://bohrium.com/docs/images


## Batch Submission

For multiple related jobs, create a job group first, then submit all jobs under it. This enables bulk result download and centralized management.

1. Create a job group:
```bash
bohr job_group create -n "my-batch" -p "$PROJECT_ID"
```
2. Submit multiple jobs under the group

```bash
for CALC_DIR in <calc_dir_1> <calc_dir_2> ...; do
  bohr job submit \
    --project_id "$PROJECT_ID" \
    --job_name "$(basename $CALC_DIR)"   \
    --machine_type "c32_m128_cpu" \
    --image_address "$IMAGE" \
    --input_directory "$CALC_DIR/" \
    --job_group_id <group_id> \
    --command "your command here"
done
```
3. Download all results at once
```bash
bohr job_group download -j <group_id> -o ./output/
```

## Input/Output Files

Input files are uploaded at submission time via `--input_directory`. Output files listed in `--backward_files` are automatically retrieved when the job finishes.

### Download results manually

```bash
bohr job download -j <jobId> -o ./output/
```

Results are downloaded as a zip to the specified output directory.

### Download logs

```bash
bohr job log -j <jobId> -o ./logs/
```

Job logs include application output (e.g. `log.lammps`) and shell stdout/stderr (`STDOUTERR`).

## Job Management

```bash
# List jobs in a job group (active jobs only by default — completed jobs NOT shown)
bohr job list -j <jobGroupId>
bohr job list -j <jobGroupId> --json     # JSON output
bohr job list -j <jobGroupId> -i         # Finished only  ← use this to detect completion
bohr job list -j <jobGroupId> -r         # Running only
bohr job list -j <jobGroupId> -f         # Failed only
bohr job list -j <jobGroupId> -p         # Pending only

# Job group management
bohr job_group list --json
bohr job_group download -j <groupId> -o ./output/
bohr job_group terminate <groupId>
bohr job_group delete <groupId>

# Kill a single job
bohr job kill -j <jobId>

# List available images
bohr image list
```

## Tracking Long-Running Jobs

Jobs that take hours require explicit state persistence — the agent's context may be compressed or reset before the job finishes.

### Step 1: Persist the job ID to disk immediately after submission

```bash
JOB_GROUP_ID=$(bohr job_group create -n "my-batch" -p "$PROJECT_ID" | grep -oP '\d+')
echo "$JOB_GROUP_ID" > .bohrium_job_group_id
```

### Step 2: Poll for completion

`bohr job list -j <GROUP_ID> --json` returns a JSON array — one object per job — each with a `status` field. Poll until all jobs reach a terminal state.

Terminal statuses: `Finished`, `Failed`, `Cancelled`, `Terminated`.

```bash
GROUP_ID=$(cat .bohrium_job_group_id)
while true; do
  OUTPUT=$(timeout 90 bohr job list -j "$GROUP_ID" --json 2>/dev/null)
  TOTAL=$(echo "$OUTPUT" | jq 'length')
  DONE=$(echo "$OUTPUT" | jq '[.[] | select(.status == "Finished" or .status == "Failed" or .status == "Cancelled" or .status == "Terminated")] | length')
  FAILED=$(echo "$OUTPUT" | jq '[.[] | select(.status == "Failed" or .status == "Cancelled" or .status == "Terminated")] | length')
  echo "[$(date '+%H:%M:%S')] $DONE/$TOTAL jobs done, $FAILED failed"
  if [ "$DONE" -eq "$TOTAL" ] && [ "$TOTAL" -gt 0 ]; then
    [ "$FAILED" -gt 0 ] && echo "$FAILED job(s) failed!" && break
    echo "All $TOTAL jobs finished successfully!" && break
  fi
  sleep 60
done
```

### Step 3: Download results

```bash
bohr job_group download -j "$GROUP_ID" -o ./output/
```


## Tips & Pitfalls

- **Always check machine availability** before submitting — popular GPU configs may be out of stock
- **Use `--backward_files` to specify outputs** — comma-separated, not an array
- **Set meaningful job names** — makes tracking easier with many jobs
- **Download results promptly** — completed jobs are retained for a limited time
- **Wrap complex commands in a shell script** — more reliable than long inline `--command` strings
- **GPU jobs need GPU-enabled images** — not all images have CUDA/cuDNN
- **MPI jobs** — use `mpirun -np N` where N matches your machine's CPU cores
- **Memory-intensive jobs** — pick machines with higher memory ratio (e.g., c8_m64 vs c8_m8)
- **`bohr` commands can be slow** — use `timeout 60-120` wrapper for scripted access
- **`bohr project list` without `--json`** opens interactive TUI that hangs in non-terminal — always use `--json`

- **Use `--help` to explore more options** — e.g., `bohr job submit --help` for all submission parameters

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Login fails | `bohr login` again, check credentials |
| Machine not available | Try a different SKU or wait |
| Job stuck in pending | Check quota, try smaller machine |
| No output files | Check logs for errors, verify command ran |
| Out of memory | Use machine with more RAM |

## References
- [references/bohrium-cli-ref.md](references/bohrium-cli-ref.md) — CLI command reference
- Full docs: https://bohrium.com/docs/cli
