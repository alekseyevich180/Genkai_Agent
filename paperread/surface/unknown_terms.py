from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .collect_experience import (
    _build_class_profile,
    _build_keyword_inventory,
    _build_material_descriptors,
    _compact_class_entry,
    _now,
)
from .parameter_registry import DEFAULT_MATERIAL_CLASS_DIR
from .surface_ontology import is_known_surface_experience_term


DEFAULT_SKILL_EXPERIENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "agents/Agent/skills/paperread/experience"
)


def _entry_count(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("count", 0))
    except (TypeError, ValueError):
        return 0


def classify_unknown_term(term: str, fields: list[str] | None = None) -> str:
    fields = fields or []
    stripped = term.strip()
    lower = stripped.casefold()

    if re.search(r"\(\d[\d\s\-]+\)|\(\d+[\u0305\u0304]?\)", stripped):
        return "facet_or_miller_index"
    if re.fullmatch(r"[*]?[A-Z][A-Za-z0-9+\-−δ*/()]*[*]?", stripped):
        return "formula_or_composition"
    if any(token in lower for token in ("reaction", "oxidation", "reduction", "fuel cell", "electrocatal")):
        return "reaction_or_application"
    if any(field in fields for field in {"materials", "Material", "Composition", "Surface/Support"}):
        if any(token in stripped for token in ("/", "-", "–", "(", ")")) or " " in stripped:
            return "composite_material_name"
    if any(token in lower for token in ("nanorod", "nanosphere", "layered", "graphene", "ldh", "oxyhydroxide", "heterostructure")):
        return "structure_or_material_phrase"
    return "other_unknown"


def _load_material_class(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}
    payload.setdefault("material_class", path.stem)
    payload.setdefault("entries", [])
    return payload


def reclassify_material_class_store(
    material_class_dir: Path = DEFAULT_MATERIAL_CLASS_DIR,
) -> dict[str, Any]:
    changed_entries = 0
    changed_files: list[str] = []
    total_entries = 0
    known_useful = 0
    unknown = 0

    for path in sorted(material_class_dir.glob("*.json")):
        payload = _load_material_class(path)
        material_class = str(payload.get("material_class") or path.stem)
        entries = [dict(entry) for entry in payload.get("entries", []) if isinstance(entry, dict)]
        file_changed = False

        for entry in entries:
            total_entries += 1
            term = str(entry.get("term", "")).strip()
            was_kind = str(entry.get("kind", ""))
            if term and is_known_surface_experience_term(term):
                if was_kind != "known_useful":
                    changed_entries += 1
                    file_changed = True
                entry["kind"] = "known_useful"
                if not entry.get("research_category") or entry.get("research_category") == "unknown_information":
                    entry["research_category"] = "other_useful_information"

        known_count = sum(1 for entry in entries if entry.get("kind") == "known_useful")
        unknown_count = len(entries) - known_count
        known_useful += known_count
        unknown += unknown_count

        refreshed_payload = {
            "schema_version": "2.0",
            "material_class": material_class,
            "updated_at": _now(),
            "summary": {
                "terms": len(entries),
                "known_useful": known_count,
                "unknown": unknown_count,
            },
            "keyword_inventory": _build_keyword_inventory(entries),
            "material_descriptors": _build_material_descriptors(entries),
            "class_profile": _build_class_profile(material_class, entries),
            "entries": [_compact_class_entry(entry) for entry in entries],
        }

        if file_changed or refreshed_payload.get("summary") != payload.get("summary"):
            path.write_text(json.dumps(refreshed_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            changed_files.append(str(path))

    return {
        "material_class_dir": str(material_class_dir),
        "changed_entries": changed_entries,
        "changed_files": changed_files,
        "summary": {
            "terms": total_entries,
            "known_useful": known_useful,
            "unknown": unknown,
        },
    }


def build_unknown_term_statistics(
    material_class_dir: Path = DEFAULT_MATERIAL_CLASS_DIR,
) -> dict[str, Any]:
    unknown_entries: list[dict[str, Any]] = []
    class_summaries: dict[str, dict[str, Any]] = {}

    for path in sorted(material_class_dir.glob("*.json")):
        payload = _load_material_class(path)
        material_class = str(payload.get("material_class") or path.stem)
        summary = payload.get("summary", {})
        class_summaries[material_class] = {
            "terms": int(summary.get("terms", 0)),
            "known_useful": int(summary.get("known_useful", 0)),
            "unknown": int(summary.get("unknown", 0)),
        }
        for entry in payload.get("entries", []):
            if not isinstance(entry, dict) or entry.get("kind") == "known_useful":
                continue
            fields = [str(field) for field in entry.get("fields", []) if field]
            category = classify_unknown_term(str(entry.get("term", "")), fields)
            unknown_entries.append(
                {
                    "material_class": material_class,
                    "term": entry.get("term", ""),
                    "count": _entry_count(entry),
                    "fields": fields,
                    "unknown_category": category,
                }
            )

    category_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    field_counts: Counter[str] = Counter()
    term_counts_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    class_counts_by_category: dict[str, Counter[str]] = defaultdict(Counter)

    for entry in unknown_entries:
        category = str(entry["unknown_category"])
        count = int(entry["count"])
        category_counts[category] += count
        class_counts[str(entry["material_class"])] += 1
        for field in entry["fields"]:
            field_counts[field] += 1
        term_counts_by_category[category][str(entry["term"])] += count
        class_counts_by_category[category][str(entry["material_class"])] += 1

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(material_class_dir),
        "summary": {
            "terms": sum(item["terms"] for item in class_summaries.values()),
            "known_useful": sum(item["known_useful"] for item in class_summaries.values()),
            "unknown": sum(item["unknown"] for item in class_summaries.values()),
        },
        "unknown_entry_count": len(unknown_entries),
        "unknown_occurrence_count": sum(int(entry["count"]) for entry in unknown_entries),
        "unknown_categories_by_occurrence": dict(category_counts.most_common()),
        "unknown_classes_by_entry_count": dict(class_counts.most_common()),
        "unknown_fields_by_entry_count": dict(field_counts.most_common()),
        "top_terms_by_unknown_category": {
            category: [{"term": term, "count": count} for term, count in counts.most_common(30)]
            for category, counts in sorted(term_counts_by_category.items())
        },
        "top_classes_by_unknown_category": {
            category: [{"material_class": name, "entries": count} for name, count in counts.most_common(20)]
            for category, counts in sorted(class_counts_by_category.items())
        },
        "class_summaries": class_summaries,
        "notes": {
            "known_filter": "Terms matching ontology known-term rules are not counted as unknown.",
            "other_unknown": "Mixed bucket; review manually before promoting terms into ontology or modeling mappings.",
        },
    }


def render_unknown_term_statistics_markdown(stats: dict[str, Any], title_date: str) -> str:
    lines = [
        f"# Unknown Term Statistics {title_date}",
        "",
        f"- Generated at: {stats['generated_at']}",
        f"- Source: `{stats['source']}`",
        "",
        "## Global Summary",
        "",
        f"- Total material-class terms: {stats['summary']['terms']}",
        f"- Known useful: {stats['summary']['known_useful']}",
        f"- Unknown entries: {stats['summary']['unknown']}",
        f"- Unknown occurrence count: {stats['unknown_occurrence_count']}",
        "",
        "## Unknown Categories",
        "",
    ]
    for category, count in stats["unknown_categories_by_occurrence"].items():
        lines.append(f"- `{category}`: {count}")
    lines.extend(["", "## Top Unknown Classes", ""])
    for material_class, count in list(stats["unknown_classes_by_entry_count"].items())[:15]:
        summary = stats["class_summaries"].get(material_class, {})
        lines.append(f"- `{material_class}`: {count} entries, summary={summary}")
    lines.extend(["", "## Top Fields", ""])
    for field, count in list(stats["unknown_fields_by_entry_count"].items())[:25]:
        lines.append(f"- `{field}`: {count}")
    lines.extend(["", "## Top Terms By Category", ""])
    for category, terms in stats["top_terms_by_unknown_category"].items():
        lines.extend([f"### {category}", ""])
        for item in terms[:20]:
            lines.append(f"- `{item['term']}`: {item['count']}")
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            "- Generic formulae, placeholders, method phrases, and broad reaction/application words are filtered by ontology known-term rules.",
            "- Remaining unknowns should mainly be reviewed for material names, local structures, facets, adsorbates, coverages, and coordination environments.",
            "- Keep high-value modeling cues as unknown until they are mapped into registry, ontology, PToModel, or surface-modeling rules.",
            "",
        ]
    )
    return "\n".join(lines)


def write_unknown_term_statistics(
    material_class_dir: Path = DEFAULT_MATERIAL_CLASS_DIR,
    output_dir: Path = DEFAULT_SKILL_EXPERIENCE_DIR,
    date_slug: str | None = None,
) -> dict[str, Any]:
    if date_slug is None:
        date_slug = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    stats = build_unknown_term_statistics(material_class_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"unknown_term_statistics_{date_slug}.json"
    md_path = output_dir / f"unknown_term_statistics_{date_slug}.md"
    json_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        render_unknown_term_statistics_markdown(stats, date_slug.replace("_", "-")),
        encoding="utf-8",
    )
    return {
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "summary": stats["summary"],
        "unknown_entry_count": stats["unknown_entry_count"],
        "unknown_occurrence_count": stats["unknown_occurrence_count"],
        "unknown_categories_by_occurrence": stats["unknown_categories_by_occurrence"],
    }
