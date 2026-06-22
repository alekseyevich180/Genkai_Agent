# Know-Do Graph Migration Guide

MatCreator now uses the unified Know-Do Graph data model. Durable knowledge and
working memory are stored together in:

```text
agents/MatCreator/.adk/know_do_graph.db
```

Working memories are normal `EntryType.memory` rows in the shared `entries`
table. Memory relationships, skill links, and promotion links are normal rows
in the shared `edges` table. New memory is not stored as JSON.

Run all commands in this guide from the MatCreator project root.

## What Is Migrated

| Previous source | New representation |
|---|---|
| `.adk/know_do_graph.db` | Entries and edges stored in the unified default database |
| `.adk/skill_graph.db` | Skills become capability entries; dependency edges are preserved |
| `.adk/memory_graph.db` | Memories become native `EntryType.memory` nodes |
| `.adk/memory/*.json` | Imported once as native memory nodes |
| `MEMORY.md` | Each usable line becomes a native memory node |

Legacy files are read-only migration sources. MatCreator does not delete them.
Migration is idempotent, so running it again does not duplicate previously
imported records.

## 1. Update Dependencies

The unified memory implementation requires the updated Know-Do Graph release:

```bash
uv sync
```

For a development checkout, install the current Know-Do Graph source into the
MatCreator environment:

```bash
uv pip install --python .venv/bin/python \
  -e /path/to/know-do-graph
```

Confirm that `KnowDoGraph.memory()` uses database-backed memory:

```bash
.venv/bin/python -c \
  "import know_do_graph; print(know_do_graph.__version__, know_do_graph.__file__)"
```

## 2. Stop Running Services

Stop the MatCreator agent, API server, and any process writing to the old graph.
This prevents writes during backup and migration.

## 3. Back Up Existing Data

Create a timestamped backup before migrating:

```bash
backup_dir="backup/knowledge-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir/legacy-adk" "$backup_dir/current-data"

cp -a agents/MatCreator/.adk/skill_graph.db "$backup_dir/legacy-adk/" 2>/dev/null || true
cp -a agents/MatCreator/.adk/memory_graph.db "$backup_dir/legacy-adk/" 2>/dev/null || true
cp -a agents/MatCreator/.adk/know_do_graph.db "$backup_dir/legacy-adk/" 2>/dev/null || true
cp -a agents/MatCreator/.adk/memory "$backup_dir/legacy-adk/" 2>/dev/null || true
cp -a agents/MatCreator/.adk/know_do_graph.db "$backup_dir/current-data/" 2>/dev/null || true
```

Back up a workspace `MEMORY.md` separately if one exists.

## 4. Run Migration

Migrate all detected legacy databases:

```bash
matcreator knowledge migrate
```

To also import a specific `MEMORY.md`:

```bash
matcreator knowledge migrate --memory-md /absolute/path/to/MEMORY.md
```

Migration also runs automatically the first time MatCreator opens the unified
graph. The explicit command is recommended because it prints the number of
durable entries, memory nodes, and edges imported.

After migration, seed the current skills and guides:

```bash
matcreator knowledge seed
```

Seeding is also idempotent. Existing usage counts and relationships are
preserved.

## 5. Verify The Result

Check MatCreator's combined statistics:

```bash
matcreator knowledge stats
```

Check the same database through the Know-Do Graph CLI:

```bash
know-do-graph graph stats
```

Both commands should use the same `KDG_DB_PATH`. By default MatCreator points
that at `agents/MatCreator/.adk/know_do_graph.db`, so the CLI and agent share
the same database.

Inspect native SQLite counts:

```bash
sqlite3 agents/MatCreator/.adk/know_do_graph.db \
  "SELECT entry_type, COUNT(*) FROM entries GROUP BY entry_type ORDER BY entry_type;"

sqlite3 agents/MatCreator/.adk/know_do_graph.db \
  "SELECT relation, COUNT(*) FROM edges GROUP BY relation ORDER BY relation;"
```

Memory nodes should appear under `entry_type = memory`. To inspect a known
session:

```bash
know-do-graph mem list --session SESSION_ID
```

Verify that no new JSON file is created after a fresh agent run. Existing JSON
files may remain as migration backups, but new writes must increase the
`memory` row count in SQLite.

## 6. Distill Working Memory

Agent observations remain memory nodes until repeated evidence is promoted:

```bash
matcreator knowledge distill --min-evidence 3
```

Distillation:

1. Finds similar, unpromoted memory nodes.
2. Requires repeated successful or cross-session evidence.
3. Creates or updates a durable heuristic entry.
4. Adds `related_memory`, `memory_of`, `heuristic_for`, and `refinement_of`
   edges where applicable.
5. Marks source memory nodes as promoted without deleting them.

Use a different threshold when needed:

```bash
matcreator knowledge distill --min-evidence 5 --stale-days 60
```

## Rollback

Stop all graph writers before rollback.

Restore the backed-up unified database:

```bash
cp backup/knowledge-TIMESTAMP/current-data/know_do_graph.db \
  agents/MatCreator/.adk/know_do_graph.db
```

If no unified database existed before migration, move the new database aside:

```bash
mv agents/MatCreator/.adk/know_do_graph.db \
  agents/MatCreator/.adk/know_do_graph.db.migrated
```

The original `.adk/skill_graph.db`, `.adk/memory_graph.db`, `.adk/memory/`,
and `MEMORY.md` sources remain untouched and can be used to repeat migration.

## Troubleshooting

### `know-do-graph graph stats` reports zero nodes

Run the command with the same `KDG_DB_PATH` MatCreator uses. By default that is
the database in the MatCreator ADK directory:

```bash
pwd
echo "$KDG_DB_PATH"
ls -l agents/MatCreator/.adk/know_do_graph.db
know-do-graph graph stats
```

### Agent memory appears in JSON

The environment is using an older Know-Do Graph package. Check:

```bash
.venv/bin/python -c \
  "import know_do_graph; print(know_do_graph.__version__, know_do_graph.__file__)"
```

Update the dependency, restart the agent, and rerun migration. In the unified
implementation, `graph.get(memory_id).entry_type` is `memory`, and no new
session JSON file is written.

### Counts increase after rerunning migration

Ensure all commands use the same project root and database. Then inspect tags
such as `legacy-id:*`, `legacy-kdg-id:*`, and `migrated-memory-id:*`, which are
used as idempotency markers.

## Runtime Behavior

- Skills are durable capability entries.
- Guides are durable procedure entries.
- Agent saves are native memory nodes.
- Extracted memory-to-memory relationships use `related_memory`.
- Memory linked to a durable skill uses `memory_of`.
- Promoted memory links to refined knowledge with `refinement_of`.
- Retrieval searches durable entries and unpromoted memory in the same graph.
