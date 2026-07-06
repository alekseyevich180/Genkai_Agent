from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from paperread.surface.surface_ontology import (
        KNOWN_MODELING_TOKENS,
        SUPPORTED_MODELING_TASKS,
    )
except ImportError:  # pragma: no cover - direct script execution
    from surface_ontology import KNOWN_MODELING_TOKENS, SUPPORTED_MODELING_TASKS


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_EXPERIENCE_DIR = SKILL_DIR / "experience"

FIELDS_TO_SCAN = {
    "surface_terminations",
    "slab_models",
    "vacancy_models",
    "adsorption_sites",
    "coverage",
    "clusters",
    "single_atoms",
    "modifiers",
    "modeling_keywords",
    "recommended_modeling_tasks",
    "links",
}

TABLE_COLUMNS_TO_SCAN = {
    "Surface Termination",
    "Adsorption Site",
    "Coverage",
    "Cluster/Single Atom",
    "Modeling Keywords",
}


@dataclass
class ExperienceRecord:
    timestamp: str
    source: str
    term: str
    category: str
    context: str
    suggested_action: str
    status: str = "candidate"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "N/A", "nan", "None"} else text


def _iter_json_payloads(path: Path) -> Iterable[dict[str, Any]]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return

    try:
        payload = json.loads(content)
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    yield item
            return
        if isinstance(payload, dict):
            yield payload
            return
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(content):
        while idx < len(content) and content[idx].isspace():
            idx += 1
        if idx >= len(content):
            break
        payload, next_idx = decoder.raw_decode(content, idx)
        if isinstance(payload, dict):
            yield payload
        idx = next_idx


def _flatten(value: object) -> list[str]:
    items: list[str] = []
    if isinstance(value, dict):
        for key, subvalue in value.items():
            if isinstance(subvalue, (dict, list)):
                items.extend(_flatten(subvalue))
            else:
                cleaned = _clean(subvalue)
                if cleaned:
                    items.append(f"{key}: {cleaned}")
    elif isinstance(value, list):
        for item in value:
            items.extend(_flatten(item))
    else:
        cleaned = _clean(value)
        if cleaned:
            items.append(cleaned)
    return items


def _is_known_term(term: str) -> bool:
    lower = term.lower()
    if lower in SUPPORTED_MODELING_TASKS:
        return True
    return any(token in lower for token in KNOWN_MODELING_TOKENS)


def _suggest_action(term: str, category: str) -> str:
    lower = term.lower()
    if category == "recommended_modeling_tasks":
        return "Review whether this should become a supported modeling task or be mapped to an existing workflow."
    if "exsol" in lower:
        return "Review whether this maps to cluster generation or needs an exsolution-specific surface workflow."
    if "strain" in lower:
        return "Review whether slab strain control should be added to the modeling planner."
    if "reconstruction" in lower or "reconstructed" in lower:
        return "Review whether reconstructed-surface templates or relaxation workflows are needed."
    return "Review the term and decide whether to add a prompt keyword, planner mapping, or new surface-modeling workflow."


def _dedupe(records: Iterable[ExperienceRecord]) -> list[ExperienceRecord]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[ExperienceRecord] = []
    for record in records:
        key = (record.term.lower(), record.category.lower(), record.source)
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def collect_from_relations(relations_path: Path) -> list[ExperienceRecord]:
    records: list[ExperienceRecord] = []
    for payload in _iter_json_payloads(relations_path):
        extraction = payload.get("extraction", payload)
        title = _clean(payload.get("title"))
        text = _clean(payload.get("text"))
        source_context = title or text[:160]
        if not isinstance(extraction, dict):
            continue
        for field in FIELDS_TO_SCAN:
            values = _flatten(extraction.get(field, []))
            for value in values:
                term = value
                if field == "links":
                    term = value.replace("relation:", "").strip()
                if not term:
                    continue
                if field == "recommended_modeling_tasks" and term in SUPPORTED_MODELING_TASKS:
                    continue
                if _is_known_term(term):
                    continue
                records.append(
                    ExperienceRecord(
                        timestamp=_utc_now(),
                        source=str(relations_path),
                        term=term,
                        category=field,
                        context=source_context,
                        suggested_action=_suggest_action(term, field),
                    )
                )
    return records


def collect_from_table(table_path: Path) -> list[ExperienceRecord]:
    records: list[ExperienceRecord] = []
    if not table_path.exists():
        return records
    with table_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_context = _clean(row.get("Material")) or _clean(row.get("Reaction Type"))
            for column in TABLE_COLUMNS_TO_SCAN:
                value = _clean(row.get(column))
                if not value:
                    continue
                for term in [part.strip() for part in value.split(",") if part.strip()]:
                    if _is_known_term(term):
                        continue
                    records.append(
                        ExperienceRecord(
                            timestamp=_utc_now(),
                            source=str(table_path),
                            term=term,
                            category=column,
                            context=row_context,
                            suggested_action=_suggest_action(term, column),
                        )
                    )
    return records


def write_records(records: list[ExperienceRecord], output_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "unrecognized_surface_terms.jsonl"
    md_path = output_dir / "unrecognized_surface_terms.md"

    if dry_run:
        return {
            "status": "dry-run",
            "count": len(records),
            "jsonl_path": str(jsonl_path),
            "markdown_path": str(md_path),
            "records": [asdict(record) for record in records],
        }

    existing_keys: set[tuple[str, str, str]] = set()
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing_keys.add((
                str(item.get("term", "")).lower(),
                str(item.get("category", "")).lower(),
                str(item.get("source", "")),
            ))

    new_records = []
    for record in records:
        key = (record.term.lower(), record.category.lower(), record.source)
        if key not in existing_keys:
            new_records.append(record)

    with jsonl_path.open("a", encoding="utf-8") as handle:
        for record in new_records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    if not md_path.exists():
        md_path.write_text("# Unrecognized Surface Terms\n\n", encoding="utf-8")
    with md_path.open("a", encoding="utf-8") as handle:
        for record in new_records:
            handle.write(f"## {record.term}\n\n")
            handle.write(f"- Status: {record.status}\n")
            handle.write(f"- Category: {record.category}\n")
            handle.write(f"- Source: `{record.source}`\n")
            handle.write(f"- Context: {record.context or 'N/A'}\n")
            handle.write(f"- Suggested action: {record.suggested_action}\n\n")

    return {
        "status": "ok",
        "count": len(new_records),
        "skipped_existing": len(records) - len(new_records),
        "jsonl_path": str(jsonl_path),
        "markdown_path": str(md_path),
    }


def cmd_export(args: argparse.Namespace) -> dict[str, Any]:
    records: list[ExperienceRecord] = []
    relations_path = Path(args.relations)
    records.extend(collect_from_relations(relations_path))
    if args.table:
        records.extend(collect_from_table(Path(args.table)))
    records = _dedupe(records)
    return write_records(records, Path(args.output_dir), dry_run=args.dry_run)


def cmd_add_term(args: argparse.Namespace) -> dict[str, Any]:
    record = ExperienceRecord(
        timestamp=_utc_now(),
        source=args.source or "manual",
        term=args.term,
        category=args.category,
        context=args.context or "",
        suggested_action=args.suggested_action
        or _suggest_action(args.term, args.category),
    )
    return write_records([record], Path(args.output_dir), dry_run=args.dry_run)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export unfamiliar surface-research terms from paperread outputs into skill experience notes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="Export terms from paperread relation/table outputs.")
    export_parser.add_argument("--relations", required=True, help="paperread *_surface_relations.jsonl path.")
    export_parser.add_argument("--table", default=None, help="Optional paperread *_table.csv path.")
    export_parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_EXPERIENCE_DIR),
        help="Directory for experience JSONL/Markdown outputs.",
    )
    export_parser.add_argument("--dry-run", action="store_true", help="Print records without writing files.")
    export_parser.set_defaults(func=cmd_export)

    term_parser = subparsers.add_parser("add-term", help="Add one manually observed unfamiliar term.")
    term_parser.add_argument("--term", required=True, help="Unfamiliar term.")
    term_parser.add_argument("--category", default="manual", help="Term category.")
    term_parser.add_argument("--context", default="", help="Short source/context note.")
    term_parser.add_argument("--source", default="manual", help="Source path, DOI, or manual.")
    term_parser.add_argument("--suggested-action", default="", help="Suggested follow-up action.")
    term_parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_EXPERIENCE_DIR),
        help="Directory for experience JSONL/Markdown outputs.",
    )
    term_parser.add_argument("--dry-run", action="store_true", help="Print record without writing files.")
    term_parser.set_defaults(func=cmd_add_term)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
