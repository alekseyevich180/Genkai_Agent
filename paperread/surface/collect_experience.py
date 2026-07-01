from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SUPPORTED_MODELING_TASKS = {
    "vacancy_landscape",
    "adsorbate_landscape",
    "surface_cluster_builder",
    "single_atom_site",
    "doped_surface",
    "surface_functionalization",
    "slab_generation",
}

KNOWN_SURFACE_TERMS = {
    "surface",
    "slab",
    "support",
    "interface",
    "facet",
    "termination",
    "terminated",
    "o-terminated",
    "metal-terminated",
    "oxygen vacancy",
    "vacancy",
    "defect",
    "dopant",
    "adsorbate",
    "adsorption",
    "adsorption site",
    "coverage",
    "cluster",
    "nanocluster",
    "nanoparticle",
    "single atom",
    "single atoms",
    "single metal atoms",
    "sac",
    "sacs",
    "active site",
    "top site",
    "bridge site",
    "hollow site",
    "monodentate",
    "bidentate",
    "coadsorption",
    "monolayer",
    "hydroxylated",
    "sulfurized",
    "nitrided",
    "reduced",
    "oxidized",
    "reconstructed",
    "metal-support",
    "anchoring",
}

RELATION_FIELDS = [
    "materials",
    "surfaces",
    "surface_terminations",
    "slab_models",
    "facets",
    "dopants",
    "defects",
    "vacancy_models",
    "active_sites",
    "adsorbates",
    "adsorption_sites",
    "coverage",
    "intermediates",
    "products",
    "clusters",
    "single_atoms",
    "modifiers",
    "modeling_keywords",
    "recommended_modeling_tasks",
]

TABLE_FIELDS = [
    "Material",
    "Surface/Support",
    "Facet",
    "Surface Termination",
    "Active Site",
    "Defect",
    "Dopant/Modifier",
    "Adsorbate/Reactant",
    "Adsorption Site",
    "Coverage",
    "Cluster/Single Atom",
    "Modeling Keywords",
]

HIGH_VALUE_FIELDS = {
    "materials",
    "surfaces",
    "facets",
    "defects",
    "vacancy_models",
    "active_sites",
    "adsorbates",
    "adsorption_sites",
    "coverage",
    "clusters",
    "single_atoms",
    "modeling_keywords",
    "recommended_modeling_tasks",
    "Material",
    "Surface/Support",
    "Facet",
    "Defect",
    "Adsorbate/Reactant",
    "Adsorption Site",
    "Coverage",
    "Cluster/Single Atom",
    "Modeling Keywords",
}


@dataclass
class ExperienceItem:
    timestamp: str
    source: str
    field: str
    value: str
    kind: str
    context: str
    action: str


CATEGORY_RULES = {
    "surface_materials": {
        "materials",
        "surfaces",
        "slab_models",
        "Material",
        "Surface/Support",
    },
    "surface_structure": {
        "facets",
        "surface_terminations",
        "Facet",
        "Surface Termination",
    },
    "defects_active_sites": {
        "defects",
        "vacancy_models",
        "active_sites",
        "dopants",
        "Defect",
        "Active Site",
        "Dopant/Modifier",
    },
    "adsorption_reaction": {
        "adsorbates",
        "adsorption_sites",
        "coverage",
        "intermediates",
        "products",
        "Adsorbate/Reactant",
        "Adsorption Site",
        "Coverage",
        "Product",
    },
    "clusters_single_atoms": {
        "clusters",
        "single_atoms",
        "modifiers",
        "Cluster/Single Atom",
    },
    "modeling_tasks": {
        "modeling_keywords",
        "recommended_modeling_tasks",
        "Modeling Keywords",
    },
}

MATERIAL_CLASS_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("single_atom_catalysts", ("single atom", "single atoms", "single metal atoms", "sac", "sacs", "sa/", "sas/")),
    ("supported_catalysts", ("/", "supported", "support", "anchored", "anchoring", "metal-support")),
    ("metals_alloys", ("alloy", "pt", "pd", "ni", "co", "fe", "cu", "ru", "rh", "ir", "au", "ag", "sn", "zn", "nickel", "tin")),
    ("oxides", ("oxide", "o2", "ceo2", "tio2", "zro2", "al2o3", "sio2", "feo", "fe2o3", "co3o4", "mno2", "nio")),
    ("hydroxides_oxyhydroxides", ("hydroxide", "oxyhydroxide", "ldh", "layered double hydroxide", "niooh", "feooh", "coooh")),
    ("sulfides", ("sulfide", "sulfur", "mos2", "cos", "nis", "fes", "ws2")),
    ("selenides_tellurides", ("selenide", "telluride", "mose2", "wse2", "nise", "cose")),
    ("nitrides", ("nitride", "nitrided", "titanium nitride", "ti nitride", "ti-n", "gan", "bn", "vn", "mon")),
    ("carbides_mxenes", ("carbide", "mxene", "tic", "sic", "wc", "mo2c", "ti3c2")),
    ("phosphides_phosphates", ("phosphide", "phosphate", "nip", "cop", "fep", "po4")),
    ("halides", ("halide", "chloride", "fluoride", "bromide", "iodide", "perovskite halide")),
    ("carbon_materials", ("graphene", "carbon", "graphite", "cnt", "nanotube", "carbon nitride", "g-c3n4", "c3n4")),
    ("perovskites_spinels", ("perovskite", "spinel", "abo3", "ab2o4")),
    ("zeolites_silicates", ("zeolite", "silicate", "aluminosilicate", "mfi", "zsm-5", "sapo")),
    ("mofs_coordination_polymers", ("mof", "metal-organic framework", "coordination polymer", "zif")),
    ("borides", ("boride", "boron", "mbene")),
    ("defect_engineered_materials", ("vacancy", "defect", "doped", "dopant", "defect-rich", "vacancy-rich")),
    ("surface_functionalized_materials", ("terminated", "o-terminated", "hydroxylated", "sulfurized", "nitrided", "oxidized", "reduced")),
    ("battery_electrode_materials", ("battery", "anode", "cathode", "sodium metal", "lithium", "na metal")),
]

MATERIAL_CLASSES = [name for name, _ in MATERIAL_CLASS_RULES] + ["other_inorganic_materials"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "N/A", "nan", "None"} else text


def _read_relation_payloads(path: Path) -> Iterable[dict[str, Any]]:
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
    if isinstance(value, dict):
        flattened: list[str] = []
        for key, subvalue in value.items():
            for item in _flatten(subvalue):
                flattened.append(f"{key}: {item}")
        return flattened
    if isinstance(value, list):
        flattened = []
        for item in value:
            flattened.extend(_flatten(item))
        return flattened
    cleaned = _clean(value)
    return [cleaned] if cleaned else []


def _split_cell(value: str) -> list[str]:
    parts = [part.strip() for part in value.replace(";", ",").split(",")]
    return [part for part in parts if part]


def _is_known(value: str) -> bool:
    lower = value.lower()
    if lower in SUPPORTED_MODELING_TASKS:
        return True
    return any(term in lower for term in KNOWN_SURFACE_TERMS)


def _action_for(field: str, value: str, known: bool) -> str:
    if field == "recommended_modeling_tasks" and value not in SUPPORTED_MODELING_TASKS:
        return "Review whether this should become a supported modeling task."
    if known:
        return "Use as candidate input for ptomodel or downstream surface-modeling workflows."
    return "Review as unknown information; consider adding prompt/schema/planner mapping if repeated."


def _kind_for(field: str, value: str) -> str:
    if field == "recommended_modeling_tasks" and value not in SUPPORTED_MODELING_TASKS:
        return "unknown_task"
    if _is_known(value):
        return "known_useful"
    if field in HIGH_VALUE_FIELDS:
        return "unknown_high_value"
    return "unknown_context"


def _normalize_term(value: str) -> str:
    return " ".join(value.casefold().replace("‐", "-").replace("‑", "-").split())


def _category_for(field: str, kind: str) -> str:
    if kind != "known_useful":
        return "unknown_information"
    for category, fields in CATEGORY_RULES.items():
        if field in fields:
            return category
    return "other_useful_information"


def _material_classes_for(value: str, field: str) -> list[str]:
    lower = _normalize_term(value)
    classes = [
        material_class
        for material_class, tokens in MATERIAL_CLASS_RULES
        if any(token in lower for token in tokens)
    ]
    if classes:
        return classes
    if field in {"materials", "surfaces", "slab_models", "Material", "Surface/Support"}:
        return ["other_inorganic_materials"]
    return []


def collect_from_relations(path: str) -> list[ExperienceItem]:
    source = str(path)
    items: list[ExperienceItem] = []
    for payload in _read_relation_payloads(Path(path)):
        extraction = payload.get("extraction", payload)
        if not isinstance(extraction, dict):
            continue
        context = _clean(payload.get("title")) or _clean(payload.get("id"))
        for field in RELATION_FIELDS:
            for value in _flatten(extraction.get(field, [])):
                kind = _kind_for(field, value)
                items.append(
                    ExperienceItem(
                        timestamp=_now(),
                        source=source,
                        field=field,
                        value=value,
                        kind=kind,
                        context=context,
                        action=_action_for(field, value, known=kind == "known_useful"),
                    )
                )
    return _dedupe(items)


def collect_from_table(path: str) -> list[ExperienceItem]:
    source = str(path)
    items: list[ExperienceItem] = []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            context = _clean(row.get("Material")) or _clean(row.get("Reaction Type"))
            for field in TABLE_FIELDS:
                raw = _clean(row.get(field))
                if not raw:
                    continue
                for value in _split_cell(raw):
                    kind = _kind_for(field, value)
                    items.append(
                        ExperienceItem(
                            timestamp=_now(),
                            source=source,
                            field=field,
                            value=value,
                            kind=kind,
                            context=context,
                            action=_action_for(field, value, known=kind == "known_useful"),
                        )
                    )
    return _dedupe(items)


def _dedupe(items: Iterable[ExperienceItem]) -> list[ExperienceItem]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[ExperienceItem] = []
    for item in items:
        key = (item.source, item.field, item.value.lower(), item.kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def aggregate_experience(items: list[ExperienceItem]) -> dict[str, Any]:
    categories: dict[str, dict[str, dict[str, Any]]] = {}
    material_classes: dict[str, dict[str, dict[str, Any]]] = {}
    raw_count = len(items)

    for item in items:
        category = _category_for(item.field, item.kind)
        term_key = _normalize_term(item.value)
        bucket = categories.setdefault(category, {})
        entry = bucket.setdefault(
            term_key,
            {
                "term": item.value,
                "kind": item.kind,
                "fields": [],
                "sources": [],
                "contexts": [],
                "actions": [],
                "count": 0,
            },
        )
        entry["count"] += 1
        for key, value in (
            ("fields", item.field),
            ("sources", item.source),
            ("contexts", item.context),
            ("actions", item.action),
        ):
            if value and value not in entry[key]:
                entry[key].append(value)
        if item.kind != entry["kind"] and item.kind.startswith("unknown"):
            entry["kind"] = item.kind

        for material_class in _material_classes_for(item.value, item.field):
            class_bucket = material_classes.setdefault(material_class, {})
            class_entry = class_bucket.setdefault(
                term_key,
                {
                    "term": item.value,
                    "kind": item.kind,
                    "research_category": category,
                    "fields": [],
                    "sources": [],
                    "contexts": [],
                    "count": 0,
                },
            )
            class_entry["count"] += 1
            for key, value in (
                ("fields", item.field),
                ("sources", item.source),
                ("contexts", item.context),
            ):
                if value and value not in class_entry[key]:
                    class_entry[key].append(value)
            if item.kind != class_entry["kind"] and item.kind.startswith("unknown"):
                class_entry["kind"] = item.kind

    ordered_categories = {}
    for category in sorted(categories):
        ordered_categories[category] = sorted(
            categories[category].values(),
            key=lambda entry: (-entry["count"], entry["term"].casefold()),
        )

    ordered_material_classes = {}
    for material_class in sorted(material_classes):
        ordered_material_classes[material_class] = sorted(
            material_classes[material_class].values(),
            key=lambda entry: (-entry["count"], entry["term"].casefold()),
        )

    useful_count = sum(
        len(entries)
        for category, entries in ordered_categories.items()
        if category != "unknown_information"
    )
    unknown_count = len(ordered_categories.get("unknown_information", []))

    return {
        "schema_version": "1.0",
        "generated_at": _now(),
        "summary": {
            "raw_items": raw_count,
            "aggregated_items": useful_count + unknown_count,
            "known_useful": useful_count,
            "unknown": unknown_count,
            "categories": {category: len(entries) for category, entries in ordered_categories.items()},
            "material_classes": {
                material_class: len(entries)
                for material_class, entries in ordered_material_classes.items()
            },
        },
        "categories": ordered_categories,
        "material_classes": ordered_material_classes,
    }


def _merge_lists(existing: list, incoming: list) -> list:
    merged = list(existing)
    for item in incoming:
        if item and item not in merged:
            merged.append(item)
    return merged


def _merge_class_entries(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {_normalize_term(str(entry.get("term", ""))): dict(entry) for entry in existing}
    for entry in incoming:
        key = _normalize_term(str(entry.get("term", "")))
        if not key:
            continue
        current = by_key.get(key)
        if current is None:
            by_key[key] = dict(entry)
            continue
        current["count"] = int(current.get("count", 0)) + int(entry.get("count", 0))
        if str(entry.get("kind", "")).startswith("unknown"):
            current["kind"] = entry.get("kind", current.get("kind"))
        current["fields"] = _merge_lists(current.get("fields", []), entry.get("fields", []))
        current["sources"] = _merge_lists(current.get("sources", []), entry.get("sources", []))
        current["contexts"] = _merge_lists(current.get("contexts", []), entry.get("contexts", []))
        if not current.get("research_category") and entry.get("research_category"):
            current["research_category"] = entry["research_category"]

    return sorted(
        by_key.values(),
        key=lambda item: (-int(item.get("count", 0)), str(item.get("term", "")).casefold()),
    )


def write_material_class_store(
    aggregate: dict[str, Any],
    output_dir: str,
) -> dict[str, Any]:
    class_dir = Path(output_dir) / "material_classes"
    class_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for material_class, entries in aggregate.get("material_classes", {}).items():
        path = class_dir / f"{material_class}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        else:
            payload = {}

        existing_entries = payload.get("entries", [])
        merged_entries = _merge_class_entries(existing_entries, entries)
        payload = {
            "schema_version": "1.0",
            "material_class": material_class,
            "updated_at": _now(),
            "summary": {
                "terms": len(merged_entries),
                "known_useful": sum(1 for entry in merged_entries if entry.get("kind") == "known_useful"),
                "unknown": sum(1 for entry in merged_entries if entry.get("kind") != "known_useful"),
                "sources": sorted(
                    {
                        source
                        for entry in merged_entries
                        for source in entry.get("sources", [])
                        if source
                    }
                ),
            },
            "entries": merged_entries,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written[material_class] = str(path)

    return written


def init_material_class_store(output_dir: str) -> dict[str, Any]:
    class_dir = Path(output_dir) / "material_classes"
    class_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    existing: list[str] = []

    for material_class in MATERIAL_CLASSES:
        path = class_dir / f"{material_class}.json"
        if path.exists():
            existing.append(str(path))
            continue
        payload = {
            "schema_version": "1.0",
            "material_class": material_class,
            "updated_at": _now(),
            "summary": {
                "terms": 0,
                "known_useful": 0,
                "unknown": 0,
                "sources": [],
            },
            "entries": [],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(str(path))

    return {
        "class_dir": str(class_dir),
        "created": created,
        "existing": existing,
        "count": len(MATERIAL_CLASSES),
    }


def write_experience(
    items: list[ExperienceItem],
    output_dir: str,
    stem: str = "surface_experience",
    write_markdown: bool = False,
    write_class_store: bool = True,
    write_run_file: bool = False,
) -> dict[str, Any]:
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / f"{stem}.json"
    md_path = outdir / f"{stem}.md"

    aggregate = aggregate_experience(items)
    material_class_files = write_material_class_store(aggregate, output_dir) if write_class_store else {}

    json_path_str = ""
    if write_run_file:
        json_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
        json_path_str = str(json_path)

    markdown_path = ""
    if write_markdown and write_run_file:
        lines = ["# Surface Extraction Experience", ""]
        summary = aggregate["summary"]
        lines.extend(
            [
                "## Summary",
                "",
                f"- Raw items: {summary['raw_items']}",
                f"- Aggregated items: {summary['aggregated_items']}",
                f"- Known useful: {summary['known_useful']}",
                f"- Unknown: {summary['unknown']}",
                "",
            ]
        )
        for category, entries in aggregate["categories"].items():
            lines.extend([f"## {category}", ""])
            for entry in entries:
                fields = ", ".join(f"`{field}`" for field in entry["fields"])
                sources = ", ".join(f"`{source}`" for source in entry["sources"])
                lines.append(f"- `{entry['term']}` ({entry['kind']}, n={entry['count']})")
                lines.append(f"  - Fields: {fields}")
                lines.append(f"  - Sources: {sources}")
                if entry["contexts"]:
                    lines.append(f"  - Context: {entry['contexts'][0]}")
                if entry["actions"]:
                    lines.append(f"  - Action: {entry['actions'][0]}")
            lines.append("")
        lines.extend(["## Material Classes", ""])
        for material_class, entries in aggregate["material_classes"].items():
            lines.extend([f"### {material_class}", ""])
            for entry in entries:
                fields = ", ".join(f"`{field}`" for field in entry["fields"])
                lines.append(f"- `{entry['term']}` ({entry['kind']}, n={entry['count']})")
                lines.append(f"  - Research category: `{entry['research_category']}`")
                lines.append(f"  - Fields: {fields}")
            lines.append("")
        md_path.write_text("\n".join(lines), encoding="utf-8")
        markdown_path = str(md_path)

    return {
        "json_path": json_path_str,
        "markdown_path": markdown_path,
        "material_class_files": material_class_files,
        "raw_count": aggregate["summary"]["raw_items"],
        "count": aggregate["summary"]["aggregated_items"],
        "known_useful": aggregate["summary"]["known_useful"],
        "unknown": aggregate["summary"]["unknown"],
    }


def collect_experience(
    relations_jsonl: str | None,
    table_csv: str | None,
    output_dir: str,
    stem: str = "surface_experience",
    write_markdown: bool = False,
    write_class_store: bool = True,
    write_run_file: bool = False,
) -> dict[str, Any]:
    items: list[ExperienceItem] = []
    if relations_jsonl:
        items.extend(collect_from_relations(relations_jsonl))
    if table_csv:
        items.extend(collect_from_table(table_csv))
    return write_experience(
        _dedupe(items),
        output_dir,
        stem=stem,
        write_markdown=write_markdown,
        write_class_store=write_class_store,
        write_run_file=write_run_file,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect useful and unknown experience from paperread surface extraction outputs."
    )
    parser.add_argument(
        "--init-material-classes",
        action="store_true",
        help="Initialize empty experience/material_classes/*.json files and exit.",
    )
    parser.add_argument("--relations", default=None, help="Path to *_surface_relations.jsonl.")
    parser.add_argument("--table", default=None, help="Path to *_table.csv.")
    parser.add_argument(
        "--output-dir",
        default="paperread/surface/experience",
        help="Directory for aggregated experience JSON and optional Markdown outputs.",
    )
    parser.add_argument(
        "--stem",
        default="surface_experience",
        help="Output filename stem. Defaults to surface_experience.",
    )
    parser.add_argument(
        "--write-markdown",
        action="store_true",
        help="Also write a human-readable Markdown review report for this run. Implies --write-run-file.",
    )
    parser.add_argument(
        "--write-run-file",
        action="store_true",
        help="Also write this run's aggregate JSON file. By default only material class files are updated.",
    )
    parser.add_argument(
        "--no-class-store",
        action="store_true",
        help="Do not update experience/material_classes/*.json.",
    )
    args = parser.parse_args(argv)

    if args.init_material_classes:
        result = init_material_class_store(args.output_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if not args.relations and not args.table:
        parser.error("At least one of --relations or --table is required.")

    result = collect_experience(
        args.relations,
        args.table,
        args.output_dir,
        stem=args.stem,
        write_markdown=args.write_markdown,
        write_class_store=not args.no_class_store,
        write_run_file=args.write_run_file or args.write_markdown,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
