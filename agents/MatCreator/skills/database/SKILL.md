---
name: database
description: Skills for materials dataset operations using CLI tools. Query and manage ASE databases and a normalized SQLite information database (nodes/datasets/dataset_elements schema). Includes SQL composition guidance for query-info.
metadata:
  tools:
    - run_skill_script
  tags:
    - general
    - sequential
    - simple
---

# Database CLI Tools

Script: `db_tools.py` (in the skill's `scripts/` directory).

Use the `run_skill_script` tool to execute it:
- `skill_name`: `"database"`
- `script_name`: `"db_tools.py"`
- `args`: the sub-command and flags as a single string

Every command prints a **JSON object** to stdout and exits 0 on success, 1 on error.

Check `INFO_DB_PATH` (env var) for SQLite info database path, or pass `--info-db` explicitly. 
---

## Commands

### `validate-sql` — Validate a SELECT statement (no DB access)

```
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args='validate-sql --sql "SELECT * FROM nodes"'
)
```

Returns `{"valid": true, "sql": "<normalized>", "error": null}` or `{"valid": false, ...}`.  
**Always run this before `query-info`.**

---

### `query-info` — Query the SQLite information database

```
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args='query-info --info-db /path/to/info.db --sql "SELECT d.dataset_id, d.elements, d.path FROM datasets d JOIN nodes n ON d.node_id=n.node_id WHERE n.name=\'PBE\'"'
)
```

Returns `{"query": "...", "count": N, "datasets": [...]}`.  
The `path` field is automatically resolved to an absolute path.

**Schema reference:** (see [SQL Composition Guide](#sql-composition-guide-for-query-info) below for full details and examples)
- `nodes(node_id, name, description, functional, code, cutoff_eV, pseudopot, kspacing, spin_pol, vdw, extra_params, created_at)`
- `datasets(dataset_id, node_id, elements, n_elements, system_type, field, entries, source, path, has_forces, has_stress, has_energy, energy_min, energy_max, created_at)`
- `dataset_elements(dataset_id, element)`

---

### `read-structure` — Extract compositions from structure file(s)

```
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="read-structure --structures /path/to/structure.cif /path/to/other.extxyz --output query_atoms.extxyz"
)
```

Supported formats: `.cif`, `.xyz`, `.extxyz`, `POSCAR`, and any format ASE can read.  
Returns `{"formulas": [...], "formulas_full": [...], "query_atoms_path": "...", "total_frames": N}`.  
Use the returned `formulas` to build a `query-compounds` selector.

---

### `query-compounds` — Query an ASE database

```
# By element presence
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="query-compounds --db-path /path/to/dataset.db --selection Si,O"
)

# By formula
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="query-compounds --db-path /path/to/dataset.db --selection formula=Si32"
)

# With energy filter and limit
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="query-compounds --db-path /path/to/dataset.db --selection Si,energy<-1.0 --limit 100"
)

# JSON list of conditions
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args='query-compounds --db-path /path/to/dataset.db --selection \'[["energy","<",-1.0],["pbc","=",true]]\''
)

# Extra ASE select kwargs
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args='query-compounds --db-path /path/to/dataset.db --selection Si --custom-args \'{"sort": "-energy"}\''
)
```

Returns `{"query": "...", "count": N, "unique_formulas": [...], "sample_ids": [first 10 ids]}`.

---

### `export-entries` — Export entries from an ASE database

```
# By explicit ids
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="export-entries --db-path /path/to/dataset.db --mode ids --ids 1 2 3 --fmt extxyz"
)

# Entire database
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="export-entries --db-path /path/to/dataset.db --mode all --fmt extxyz"
)

# Random sample
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="export-entries --db-path /path/to/dataset.db --mode random --sample-size 500 --random-seed 42 --fmt extxyz"
)

# By selection criteria
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="export-entries --db-path /path/to/dataset.db --mode selection --selection Si,O,energy<-2.0 --limit 1000 --fmt extxyz"
)

# Custom output directory
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="export-entries --db-path /path/to/dataset.db --mode all --output-dir /tmp/my_export"
)
```

Returns `{"output_file": "...", "metadata_file": "...", "counts": {"total_exported": N, "unique_formulas": M}}`.  
For ML force-field training, always use `--fmt extxyz`.

---

### `save-extxyz` — Register a user extxyz file in the database

```
run_skill_script(
    skill_name="database",
    script_name="db_tools.py",
    args="save-extxyz --extxyz-path /path/to/data.extxyz --info-db /path/to/info.db"
)
```

Creates a new ASE `.db` file under `<info-db-dir>/user_data/` and registers it in the info database under the "User Upload" node.  
Returns `{"status": "ok", "ase_db_path": "...", "dataset_id": N, "entries": N, "elements": [...]}`.

---

## Typical workflow for dataset search

Use this flow for dataset search:

1. **Explore available nodes/datasets** — first compose and validate a SELECT, then run it:
   ```
   run_skill_script(skill_name="database", script_name="db_tools.py",
       args='validate-sql --sql "SELECT node_id, name, functional FROM nodes"')
   run_skill_script(skill_name="database", script_name="db_tools.py",
       args='query-info --info-db $INFO_DB_PATH --sql "SELECT node_id, name, functional FROM nodes"')
   ```

2. **Find datasets matching target elements** — query `dataset_elements` to locate domain datasets (e.g. `domain_SemiCond`):

   ```
   run_skill_script(skill_name="database", script_name="db_tools.py",
       args='query-info --info-db $INFO_DB_PATH --sql "SELECT d.dataset_id, d.elements, d.entries, d.path FROM datasets d JOIN dataset_elements de ON d.dataset_id=de.dataset_id WHERE de.element=\'Si\'"')
   ```

3. **Query structures within a dataset** — use `query-compounds` with the `path` returned in step 2:

   ```
   run_skill_script(skill_name="database", script_name="db_tools.py",
       args="query-compounds --db-path <path from step 2> --selection Si,O --limit 50")
   ```

4. **Export for training** — always use `--fmt extxyz` when preparing datasets for ML force fields:

   ```
   run_skill_script(skill_name="database", script_name="db_tools.py",
       args="export-entries --db-path <path> --mode selection --selection Si,O --fmt extxyz")
   ```

---

## SQL Composition Guide for `query-info`

Compose SELECT statements yourself and pass them to `query-info`. Follow the rules and examples below.

### Full Schema

**`nodes`** — one row per DFT computation node (settings)

| Column | Type | Description |
|---|---|---|
| `node_id` | INTEGER PK | Unique identifier |
| `name` | TEXT | Node label (e.g. `PBE`, `PBEsol_Bulk`) |
| `description` | TEXT | Human-readable description |
| `functional` | TEXT | DFT functional: `PBE`, `PBEsol`, `LDA`, `SCAN`, `HSE06` … |
| `code` | TEXT | DFT code: `VASP`, `ABACUS`, `QE`, `CP2K` … |
| `cutoff_eV` | REAL | Plane-wave energy cutoff |
| `pseudopot` | TEXT | Pseudopotential / PAW label |
| `kspacing` | REAL | k-point spacing |
| `spin_pol` | INTEGER | Spin-polarised calculation (0/1) |
| `vdw` | TEXT | van der Waals correction |
| `extra_params` | TEXT | JSON blob with additional settings |
| `created_at` | TEXT | ISO timestamp |

**`datasets`** — one row per ASE `.db` file

| Column | Type | Description |
|---|---|---|
| `dataset_id` | INTEGER PK | Unique identifier |
| `node_id` | INTEGER FK | Links to `nodes` |
| `elements` | TEXT | Comma-separated element list |
| `n_elements` | INTEGER | Number of distinct elements |
| `system_type` | TEXT | `Bulk`, `Cluster`, `Surface`, `Interface` … |
| `field` | TEXT | Application field (e.g. `Catalysis`, `Semiconductor`) |
| `entries` | INTEGER | Frame count |
| `source` | TEXT | URL / DOI / provenance |
| `path` | TEXT | Relative path to the ASE `.db` file (resolved by `query-info`) |
| `has_forces` | INTEGER | Forces available (0/1) |
| `has_stress` | INTEGER | Stress available (0/1) |
| `has_energy` | INTEGER | Energy available (0/1) |
| `energy_min` | REAL | Minimum per-atom energy |
| `energy_max` | REAL | Maximum per-atom energy |
| `created_at` | TEXT | ISO timestamp |

**`dataset_elements`** — many-to-many element membership

| Column | Type | Description |
|---|---|---|
| `dataset_id` | INTEGER FK | Links to `datasets` |
| `element` | TEXT | Element symbol (e.g. `Si`, `O`) |

---

### SQL Rules

1. Write only `SELECT` statements — no `UPDATE`, `INSERT`, `DELETE`, `DROP`, `ALTER`, `PRAGMA`, or `ATTACH`.
2. Always `SELECT` the `path` column from `datasets` so the caller can open the `.db` file.
3. Use `LIKE` for fuzzy text matching on `name`, `system_type`, `field`, `source`, `description`.
4. Use `LIMIT` only when the user specifies a cap (infer 20 for "a few" / "top N").
5. Parenthesise `OR` groups; use explicit `AND` / `OR`.
6. Validate every SELECT with `validate-sql` before running `query-info`.

---

### SQL Examples

**List all available nodes:**
```sql
SELECT node_id, name, functional, code FROM nodes ORDER BY name
```

**Find datasets by field:**
```sql
SELECT d.dataset_id, d.elements, d.entries, d.path
FROM datasets d
JOIN nodes n ON d.node_id = n.node_id
WHERE d.field = 'Catalysis'
```

**Find datasets computed with a specific functional:**
```sql
SELECT d.dataset_id, d.elements, d.system_type, d.entries, d.path
FROM datasets d
JOIN nodes n ON d.node_id = n.node_id
WHERE n.functional = 'PBE'
```

**Find datasets containing a specific element:**
```sql
SELECT d.dataset_id, d.elements, d.entries, d.path
FROM datasets d
JOIN dataset_elements de ON d.dataset_id = de.dataset_id
WHERE de.element = 'Si'
```

**Find bulk datasets with forces, computed with VASP:**
```sql
SELECT d.dataset_id, d.elements, d.entries, d.path
FROM datasets d
JOIN nodes n ON d.node_id = n.node_id
WHERE d.system_type LIKE '%Bulk%'
  AND d.has_forces = 1
  AND n.code = 'VASP'
```

**Find datasets containing both Si and O:**
```sql
SELECT d.dataset_id, d.elements, d.entries, d.path
FROM datasets d
JOIN dataset_elements de1 ON d.dataset_id = de1.dataset_id
JOIN dataset_elements de2 ON d.dataset_id = de2.dataset_id
WHERE de1.element = 'Si' AND de2.element = 'O'
```

**A few surface datasets (top 20):**
```sql
SELECT d.dataset_id, d.elements, d.field, d.entries, d.path
FROM datasets d
WHERE d.system_type LIKE '%Surface%'
LIMIT 20
```
