---
name: quests
description: Calculate entropy of atomic structure descriptors and select maximally diverse subsets for active learning using the QUEST method.
metadata:
  tools:
    - run_skill_script
    - run_bash
  tags:
    - active-learning
    - entropy
    - diversity
    - structure-selection
---

## Overview

The QUEST method computes entropy-based descriptors for atomic structures and uses them to select maximally diverse subsets from a candidate pool. This is the primary tool for active-learning data curation — choosing which structures to label with DFT or ML potentials in order to maximally expand configuration space coverage.

**For selecting the most diverse structures from a pool, always use `active_learning.py`** (described first below). It implements an iterative greedy entropy-maximisation algorithm with GPU acceleration that is optimal for structure pool filtering.

The `quests` CLI (available in the `deepmd` conda environment) provides complementary utilities — computing dataset entropy, scoring candidates, exporting descriptors, etc. — but is **not** used for pool-based structure selection. Check its commands with:

```bash
conda run -n deepmd quests --help
# or, if the environment is already active:
quests --help
```

---

## `active_learning.py` — optimal structure pool filtering

Use this script to select the most diverse structures from a candidate pool. It implements an iterative greedy entropy-maximisation algorithm and automatically uses GPU (CUDA via PyTorch) when available, falling back to CPU.

Use the `run_skill_script` tool to execute it:
- `skill_name`: `"quests"`
- `script_name`: `"active_learning.py"`
- `args`: the sub-command and flags as a single string

The script prints a JSON object to stdout and exits **0** on success or **1** on error. Always parse the JSON to retrieve the output file path and confirm `"status": "success"`.

### Command: `filter-by-entropy`

**Arguments**

| Flag | Type | Default | Description |
|---|---|---|---|
| `iter_confs` | paths | required | One or more candidate structure files (positional, space-separated, any ASE-readable format) |
| `--reference` | paths | `[]` | Reference structure files already in the dataset (used to compute baseline entropy; excluded from selection) |
| `--chunk-size` | int | `10` | Structures added per iteration |
| `--k` | int | `32` | Number of nearest neighbours for descriptor |
| `--cutoff` | float | `5.0` | Cutoff radius in Å |
| `--batch-size` | int | `1000` | Batch size for entropy computation |
| `--h` | float | `0.015` | Bandwidth parameter *h* |
| `--max-sel` | int | `50` | Maximum structures to select |

**JSON response fields:** `status`, `message`, `selected_atoms` (path to output extxyz), `entropy` (per-iteration dict with `iter_00`, `iter_01`, … and `num_confs`).

**Examples**

```
# Select up to 50 diverse structures from a pool
run_skill_script(
    skill_name="quests",
    script_name="active_learning.py",
    args="filter-by-entropy candidates.extxyz --max-sel 50"
)

# Select relative to an existing reference/training dataset
run_skill_script(
    skill_name="quests",
    script_name="active_learning.py",
    args="filter-by-entropy new_structures.extxyz --reference training_set.extxyz --max-sel 100"
)

# Multiple candidate files, tighter bandwidth
run_skill_script(
    skill_name="quests",
    script_name="active_learning.py",
    args="filter-by-entropy pool1.extxyz pool2.extxyz --h 0.01 --cutoff 6.0 --max-sel 200"
)
```

---

## `quests` CLI reference

The `quests` CLI (in the `deepmd` conda environment) provides complementary utilities for analysing and scoring datasets. Use `quests <subcommand> --help` for full options.

All commands follow the pattern:
```bash
quests <subcommand> [OPTIONS] <positional args>
```

Use `quests <subcommand> --help` to see full options for any command.

### Available commands

| Command | Purpose |
|---|---|
| `active_learning` | Iterative active-learning loop: sample, score, select new structures |
| `entropy` | Compute the entropy of a structure dataset |
| `dH` | Compute per-frame entropy gain (ΔH) of a test set relative to a reference |
| `approx_dH` | Fast approximate ΔH using graph-based nearest-neighbour index |
| `make_descriptors` | Compute and export per-atom QUEST descriptors |
| `bandwidth` | Estimate a good bandwidth *h* from the mean atomic volume |
| `compress` | Compress a dataset |
| `entropy_sampler` | Sample structures by entropy |
| `learning_curve` | Compute learning curve statistics |
| `mcmc` | Monte Carlo structure generation |
| `overlap` | Compute overlap between two datasets |

---

### `quests entropy` — dataset entropy

Compute the scalar entropy *H* of a structure file.

```
quests entropy [OPTIONS] FILE
```

| Option | Default | Description |
|---|---|---|
| `-c`, `--cutoff` | `5.0` | Neighbour-list cutoff (Å) |
| `-k`, `--nbrs` | `32` | Number of neighbours for descriptor |
| `-b`, `--bandwidth` | `0.015` | Kernel bandwidth *h* |
| `-j`, `--jobs` | all | Parallel jobs |
| `--batch_size` | `20000` | Distance batch size |
| `-o`, `--output` | — | Path to JSON output file |
| `--overwrite` | — | Overwrite existing output |

```bash
quests entropy dataset.extxyz -o entropy.json
```

---

### `quests dH` — entropy gain ΔH

Compute per-frame entropy contribution of `TEST` structures relative to a `REFERENCE` dataset. High ΔH structures are the most novel.

```
quests dH [OPTIONS] TEST REFERENCE
```

| Option | Default | Description |
|---|---|---|
| `-c`, `--cutoff` | `5.0` | Neighbour-list cutoff (Å) |
| `-k`, `--nbrs` | `32` | Number of neighbours for descriptor |
| `-b`, `--bandwidth` | `0.015` | Kernel bandwidth *h* |
| `-j`, `--jobs` | all | Parallel jobs |
| `--batch_size` | `20000` | Distance batch size |
| `-o`, `--output` | — | Path to JSON output file |
| `--overwrite` | — | Overwrite existing output |

```bash
# Score new candidates against the existing training set
quests dH candidates.extxyz training_set.extxyz -o scores.json
```

---

### `quests approx_dH` — fast approximate ΔH

Same as `dH` but uses a graph-based approximate nearest-neighbour index for speed.

```
quests approx_dH [OPTIONS] TEST REFERENCE
```

Additional options vs `dH`:

| Option | Default | Description |
|---|---|---|
| `-n`, `--uq_nbrs` | `3` | Neighbours for UQ descriptor |
| `-g`, `--graph_nbrs` | `10` | Neighbours for the graph index |

```bash
quests approx_dH candidates.extxyz training_set.extxyz -o scores.json
```

---

### `quests active_learning` — iterative selection loop

Run a full active-learning loop: generates new candidate structures via MCMC and selects the most informative ones relative to a reference dataset.

```
quests active_learning [OPTIONS] REFERENCE
```

| Option | Default | Description |
|---|---|---|
| `-s`, `--structures` | — | Number of structures to sample from reference |
| `-n`, `--n_steps` | `1000` | Monte Carlo steps |
| `-t`, `--target` | `30` | Target ΔH for new structure generation |
| `-g`, `--generations` | `10` | Number of active-learning generations |
| `-c`, `--cutoff` | `5.0` | Neighbour-list cutoff (Å) |
| `-k`, `--nbrs` | `32` | Number of neighbours for descriptor |
| `-b`, `--bandwidth` | `0.015` | Kernel bandwidth *h* |
| `-j`, `--jobs` | all | Parallel jobs |
| `--batch_size` | `20000` | Distance batch size |
| `-o`, `--output` | — | Path to JSON output file |
| `--overwrite` | — | Overwrite existing output |
| `--full` | — | Output = union of original + new dataset |

```bash
quests active_learning training_set.extxyz -g 5 -t 20 -o new_structures.json
```

---

### `quests make_descriptors` — export descriptors

Compute and save per-atom QUEST descriptors for a structure file.

```
quests make_descriptors [OPTIONS] FILE
```

| Option | Default | Description |
|---|---|---|
| `-c`, `--cutoff` | `5.0` | Neighbour-list cutoff (Å) |
| `-k`, `--nbrs` | `32` | Number of neighbours |
| `-j`, `--jobs` | all | Parallel jobs |
| `-r`, `--reshape` | — | Reshape to `(n_frames, n_atoms, d)` — requires uniform atom count |
| `-o`, `--output` | — | Output file path |

```bash
quests make_descriptors dataset.extxyz -o descriptors.npy
```

---

### `quests bandwidth` — estimate bandwidth

Estimate a suitable bandwidth *h* from the mean atomic volume of a dataset.

```
quests bandwidth [OPTIONS] ATOMIC_VOLUME
```

| Option | Description |
|---|---|
| `-c`, `--cutoff` | Use cutoff function instead of Gaussian fit |

```bash
quests bandwidth 20.5   # pass mean atomic volume in Å³
```

---

## Key parameters guide

| Parameter | Typical range | Effect |
|---|---|---|
| `--h` / `-b` (bandwidth) | 0.005 – 0.05 | Smaller → finer discrimination; larger → broader diversity measure. Use `quests bandwidth` to estimate. |
| `--cutoff` / `-c` | 4.0 – 8.0 Å | Larger → more environment context, slower |
| `--k` / `-k` (nbrs) | 16 – 64 | More neighbours → richer descriptor, slower |
| `--max-sel` | — | Hard cap on selected structures; set to your labelling budget |
