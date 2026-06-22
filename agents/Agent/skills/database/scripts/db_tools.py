#!/usr/bin/env python3
"""
Database CLI tools — direct replacements for the database MCP server tools.

All commands print a JSON object to stdout and exit 0 on success, 1 on error.

Usage:
  python db_tools.py <command> [options]

Commands:
  save-extxyz      Save an extxyz file into an ASE db and register it in the info db.
  validate-sql     Validate a SELECT SQL statement (no DB access).
  query-info       Run a SELECT on the SQLite information database.
  read-structure   Parse structure file(s) and extract chemical compositions.
  query-compounds  Query an ASE database with flexible selection criteria.
  export-entries   Export entries from an ASE database in various formats.

Environment variables (fallbacks for --info-db / --db-path):
  INFO_DB_PATH     Path to the SQLite information database.
  ASE_DB_PATH      Path to an ASE database file.
"""

import argparse
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from ase.db import connect
from ase.io import read, write

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_work_path(create: bool = True) -> str:
    calling_function = traceback.extract_stack(limit=2)[-2].name
    current_time = time.strftime("%Y%m%d%H%M%S")
    random_string = str(uuid.uuid4())[:8]
    work_path = f"{current_time}.{calling_function}.{random_string}"
    if create:
        os.makedirs(work_path, exist_ok=True)
    return work_path


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            node_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL UNIQUE,
            description  TEXT,
            functional   TEXT,
            code         TEXT,
            cutoff_eV    REAL,
            pseudopot    TEXT,
            kspacing     REAL,
            spin_pol     INTEGER DEFAULT 0,
            vdw          TEXT,
            extra_params TEXT,
            created_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS datasets (
            dataset_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id      INTEGER NOT NULL REFERENCES nodes(node_id),
            elements     TEXT NOT NULL,
            n_elements   INTEGER,
            system_type  TEXT,
            field        TEXT,
            entries      INTEGER,
            source       TEXT,
            path         TEXT,
            has_forces   INTEGER DEFAULT 0,
            has_stress   INTEGER DEFAULT 0,
            has_energy   INTEGER DEFAULT 0,
            energy_min   REAL,
            energy_max   REAL,
            created_at   TEXT
        );
        CREATE TABLE IF NOT EXISTS dataset_elements (
            dataset_id  INTEGER NOT NULL REFERENCES datasets(dataset_id),
            element     TEXT NOT NULL,
            PRIMARY KEY (dataset_id, element)
        );
        CREATE INDEX IF NOT EXISTS idx_de_element  ON dataset_elements(element);
        CREATE INDEX IF NOT EXISTS idx_ds_elements ON datasets(elements);
        CREATE INDEX IF NOT EXISTS idx_ds_node     ON datasets(node_id);
    """)


def _get_or_create_user_node(conn: sqlite3.Connection, now: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT node_id FROM nodes WHERE name = 'User Upload'")
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO nodes (name, description, created_at) VALUES (?, ?, ?)",
        ("User Upload", "Frames uploaded by the user; DFT settings unknown.", now),
    )
    return cur.lastrowid


SQL_FORBIDDEN = re.compile(
    r"\b(UPDATE|INSERT|DELETE|DROP|ALTER|CREATE|ATTACH|DETACH|REPLACE|VACUUM|PRAGMA)\b",
    re.IGNORECASE,
)


def _validate_sql(sql_code: str) -> str:
    if not sql_code:
        raise ValueError("Empty SQL code")
    statements = [s.strip() for s in sql_code.strip().split(";") if s.strip()]
    if len(statements) != 1:
        raise ValueError("Only a single SQL statement is allowed")
    stmt = statements[0]
    if not re.match(r"^\s*SELECT\b", stmt, re.IGNORECASE):
        raise ValueError("Only SELECT statements are permitted")
    if SQL_FORBIDDEN.search(stmt):
        raise ValueError("Destructive or schema-altering keywords detected")
    return stmt


def _parse_selection(raw: str) -> Any:
    """Parse a selection value from a CLI string.

    If the string looks like a JSON array or object, decode it.
    If it looks like a plain integer, return int.
    Otherwise return the raw string (ASE expression).
    """
    stripped = raw.strip()
    if stripped.startswith(("[", "{")):
        return json.loads(stripped)
    try:
        return int(stripped)
    except ValueError:
        return stripped


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_save_extxyz(args: argparse.Namespace) -> Dict[str, Any]:
    """Save an extxyz file into an ASE db and register it in the info database."""
    info_db_path = Path(args.info_db)
    extxyz_path = args.extxyz_path

    root_dir = info_db_path.parent
    user_data_dir = root_dir / "user_data"
    user_data_dir.mkdir(exist_ok=True)

    db_name = f"{time.strftime('%Y%m%d%H%M%S')}.db"
    db_file_path = user_data_dir / db_name
    db_path_info = "user_data/" + db_name

    ase_db = connect(str(db_file_path))
    images = read(extxyz_path, format="extxyz", index=":")

    elements_set: set = set()
    has_forces = has_stress = has_energy = False
    energy_vals: List[float] = []

    for item in images:
        elements_set.update(item.get_chemical_symbols())
        ase_db.write(item)
        if item.calc is not None:
            results = item.calc.results
            if "forces" in results:
                has_forces = True
            if "stress" in results:
                has_stress = True
            if "energy" in results:
                has_energy = True
                energy_vals.append(results["energy"])

    elements_list = sorted(elements_set)
    elements_str = "-".join(elements_list)
    now = datetime.now().isoformat()

    with sqlite3.connect(str(info_db_path)) as conn:
        _ensure_schema(conn)
        node_id = _get_or_create_user_node(conn, now)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO datasets
                (node_id, elements, n_elements, system_type, field,
                 entries, source, path,
                 has_forces, has_stress, has_energy,
                 energy_min, energy_max, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node_id, elements_str, len(elements_list),
                "Bulk", "User Upload",
                len(images), "User Calculation", db_path_info,
                int(has_forces), int(has_stress), int(has_energy),
                min(energy_vals) if energy_vals else None,
                max(energy_vals) if energy_vals else None,
                now,
            ),
        )
        dataset_id = cur.lastrowid
        for element in elements_list:
            cur.execute(
                "INSERT OR IGNORE INTO dataset_elements (dataset_id, element) VALUES (?, ?)",
                (dataset_id, element),
            )
        conn.commit()

    return {
        "status": "ok",
        "ase_db_path": str(db_file_path),
        "dataset_id": dataset_id,
        "entries": len(images),
        "elements": elements_list,
    }


def cmd_validate_sql(args: argparse.Namespace) -> Dict[str, Any]:
    """Validate a SELECT SQL statement."""
    try:
        normalized = _validate_sql(args.sql)
        return {"valid": True, "sql": normalized, "error": None}
    except ValueError as exc:
        return {"valid": False, "sql": "", "error": str(exc)}


def cmd_query_info(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute a SELECT on the SQLite information database."""
    sql_code = args.sql
    db_path = Path(args.info_db)
    parent_path = db_path.parent

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sql_code)
        records = cursor.fetchall()
        results = []
        for record in records:
            item = {key: record[key] for key in record.keys()}
            path_key = next((k for k in item if k.lower() == "path"), None)
            if path_key and item[path_key]:
                item[path_key] = str(parent_path / item[path_key])
            results.append(item)

    return {
        "query": sql_code.strip(),
        "count": len(results),
        "datasets": results,
    }


def cmd_read_structure(args: argparse.Namespace) -> Dict[str, Any]:
    """Parse structure file(s) and extract chemical compositions."""
    structure_paths = [Path(p) for p in args.structures]
    atoms_ls = []
    for path in structure_paths:
        atoms = read(str(path), index=":")
        if isinstance(atoms, list):
            atoms_ls.extend(atoms)
        else:
            atoms_ls.append(atoms)

    formulas = []
    formulas_full = []
    for atoms in atoms_ls:
        formula = atoms.get_chemical_formula(empirical=True)
        formula_full = atoms.get_chemical_formula()
        if formula_full:
            formulas_full.append(formula_full)
        if formula:
            formulas.append(formula)

    output_path = Path(args.output) if args.output else Path("query_atoms.extxyz")
    write(str(output_path), atoms_ls, format="extxyz")

    return {
        "formulas": formulas,
        "formulas_full": formulas_full,
        "query_atoms_path": str(output_path.resolve()),
        "total_frames": len(atoms_ls),
    }


def cmd_query_compounds(args: argparse.Namespace) -> Dict[str, Any]:
    """Query an ASE database with flexible selection criteria."""
    selection = _parse_selection(args.selection)
    limit = args.limit
    custom_args = json.loads(args.custom_args) if args.custom_args else {}
    db_path = args.db_path

    seen_ids: List[int] = []
    formulas: set = set()

    with connect(db_path) as db:
        for row in db.select(selection, limit=limit, **custom_args):
            seen_ids.append(row.id)
            formula = row.get("formula")
            if formula:
                formulas.add(formula)

    return {
        "query": str(selection),
        "count": len(seen_ids),
        "unique_formulas": sorted(formulas),
        "sample_ids": seen_ids[:10],
    }


def cmd_export_entries(args: argparse.Namespace) -> Dict[str, Any]:
    """Export entries from an ASE database."""
    mode = args.mode
    db_path = args.db_path
    fmt = args.fmt
    ids = args.ids  # list[int] or None
    sample_size = args.sample_size
    random_seed = args.random_seed
    limit = args.limit
    selection = _parse_selection(args.selection) if args.selection else None
    custom_args = json.loads(args.custom_args) if args.custom_args else {}
    output_dir = Path(args.output_dir) if args.output_dir else Path(_generate_work_path())
    output_dir.mkdir(parents=True, exist_ok=True)

    atoms_collection = []
    formulas: set = set()
    metadata_path = output_dir / "exported_metadata.json"
    combined_path = output_dir / f"exported_structures.{fmt}"
    total_exported = 0

    with metadata_path.open("w", encoding="utf-8") as meta_fp:
        with connect(db_path) as db:
            target_ids: Optional[List[int]] = None

            if mode == "ids":
                if not ids:
                    raise ValueError("Provide --ids when mode=ids")
                target_ids = ids
            elif mode == "random":
                if sample_size is None or sample_size <= 0:
                    raise ValueError("Provide --sample-size > 0 when mode=random")
                available_ids = [row.id for row in db.select()]
                sample_n = min(sample_size, len(available_ids))
                rng = random.Random(random_seed)
                target_ids = rng.sample(available_ids, sample_n)

            if mode == "all":
                row_iter = db.select()
            elif mode == "selection":
                if selection is None:
                    raise ValueError("Provide --selection when mode=selection")
                row_iter = db.select(selection, limit=limit, **custom_args)
            else:
                row_iter = (db.get(id=eid) for eid in (target_ids or []))

            for row in row_iter:
                if row is None:
                    continue
                atoms = row.toatoms()
                atoms_collection.append(atoms)
                formula = row.get("formula") or atoms.get_chemical_formula(empirical=True)
                if formula:
                    formulas.add(formula)
                record = {
                    "id": row.id,
                    "name": row.get("name"),
                    "formula": row.get("formula"),
                    "tags": row.get("tags"),
                }
                meta_fp.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                total_exported += 1

    if total_exported == 0:
        metadata_path.unlink(missing_ok=True)
        return {
            "output_file": "",
            "metadata_file": "",
            "counts": {"total_exported": 0, "unique_formulas": 0},
        }

    payload = atoms_collection[0] if len(atoms_collection) == 1 else atoms_collection
    write(str(combined_path), payload, format=fmt)

    return {
        "output_file": str(combined_path),
        "metadata_file": str(metadata_path),
        "counts": {
            "total_exported": total_exported,
            "unique_formulas": len(formulas),
        },
    }


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="db_tools.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- save-extxyz ----
    p_save = sub.add_parser("save-extxyz", help="Save extxyz file into ASE db and register in info db")
    p_save.add_argument("--extxyz-path", required=True, help="Path to the extxyz file")
    p_save.add_argument(
        "--info-db",
        default=os.environ.get("INFO_DB_PATH", ""),
        help="Path to the SQLite information database (or set INFO_DB_PATH env var)",
    )

    # ---- validate-sql ----
    p_val = sub.add_parser("validate-sql", help="Validate a SELECT SQL statement")
    p_val.add_argument("--sql", required=True, help="SQL SELECT statement to validate")

    # ---- query-info ----
    p_qi = sub.add_parser("query-info", help="Run a SELECT on the SQLite information database")
    p_qi.add_argument("--sql", required=True, help="Validated SELECT statement")
    p_qi.add_argument(
        "--info-db",
        default=os.environ.get("INFO_DB_PATH", ""),
        help="Path to the SQLite information database (or set INFO_DB_PATH env var)",
    )

    # ---- read-structure ----
    p_rs = sub.add_parser("read-structure", help="Parse structure file(s) and extract compositions")
    p_rs.add_argument("--structures", nargs="+", required=True, help="One or more structure files")
    p_rs.add_argument("--output", default=None, help="Output extxyz path (default: query_atoms.extxyz)")

    # ---- query-compounds ----
    p_qc = sub.add_parser("query-compounds", help="Query an ASE database with flexible selectors")
    p_qc.add_argument(
        "--selection", required=True,
        help=(
            "ASE selection: plain string (e.g. 'Si,O' or 'formula=Si32'), "
            "integer id, or JSON list/dict"
        ),
    )
    p_qc.add_argument(
        "--db-path",
        default=os.environ.get("ASE_DB_PATH", ""),
        help="Path to the ASE database (or set ASE_DB_PATH env var)",
    )
    p_qc.add_argument("--limit", type=int, default=None, help="Max rows to return")
    p_qc.add_argument(
        "--custom-args", default="",
        help="JSON object of extra kwargs forwarded to ase.db.select()",
    )

    # ---- export-entries ----
    p_ex = sub.add_parser("export-entries", help="Export entries from an ASE database")
    p_ex.add_argument(
        "--db-path",
        default=os.environ.get("ASE_DB_PATH", ""),
        help="Path to the ASE database (or set ASE_DB_PATH env var)",
    )
    p_ex.add_argument(
        "--mode", choices=["ids", "all", "random", "selection"], default="ids",
        help="Selection strategy (default: ids)",
    )
    p_ex.add_argument("--fmt", choices=["extxyz", "cif", "traj"], default="extxyz")
    p_ex.add_argument("--ids", nargs="+", type=int, default=None, help="Row ids (mode=ids)")
    p_ex.add_argument("--sample-size", type=int, default=None, help="Sample count (mode=random)")
    p_ex.add_argument("--random-seed", type=int, default=None, help="RNG seed (mode=random)")
    p_ex.add_argument(
        "--selection", default=None,
        help="ASE selection string / JSON (mode=selection)",
    )
    p_ex.add_argument("--limit", type=int, default=None, help="Max rows (mode=selection)")
    p_ex.add_argument(
        "--custom-args", default="",
        help="JSON object of extra kwargs forwarded to ase.db.select()",
    )
    p_ex.add_argument(
        "--output-dir", default=None,
        help="Directory for exported files (default: auto-generated timestamped dir)",
    )

    return parser


COMMANDS = {
    "save-extxyz": cmd_save_extxyz,
    "validate-sql": cmd_validate_sql,
    "query-info": cmd_query_info,
    "read-structure": cmd_read_structure,
    "query-compounds": cmd_query_compounds,
    "export-entries": cmd_export_entries,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = COMMANDS[args.command](args)
        print(json.dumps(result, indent=2, default=str))
    except Exception as exc:
        error = {"error": str(exc), "command": args.command}
        print(json.dumps(error, indent=2), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

