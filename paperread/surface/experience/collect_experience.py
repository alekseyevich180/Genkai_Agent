from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
from typing import Any, Iterable

try:
    from ..core.crystal_structures import match_crystal_structure_term
    from .parameter_registry import build_surface_parameter_registry
    from .parameter_registry import DEFAULT_MATERIAL_CLASS_DIR
    from ..core.surface_ontology import (
        CATEGORY_RULES,
        GENERIC_REACTION_TYPES,
        HIGH_VALUE_FIELDS,
        MATERIAL_CLASS_RULES,
        MATERIAL_CLASSES,
        MATERIAL_KIND_TOKENS,
        PERIODIC_SYMBOLS,
        RELATION_FIELDS,
        SUPPORTED_MODELING_TASKS,
        TABLE_FIELDS,
        TRANSITION_OR_SUPPORT_TOKENS,
        KEYWORD_BUCKET_RULES,
        is_known_surface_term,
    )
    from ..core.surface_indices import canonicalize_surface_index
except ImportError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from paperread.surface.core.crystal_structures import match_crystal_structure_term
    from paperread.surface.experience.parameter_registry import build_surface_parameter_registry
    from paperread.surface.experience.parameter_registry import DEFAULT_MATERIAL_CLASS_DIR
    from paperread.surface.core.surface_ontology import (
        CATEGORY_RULES,
        GENERIC_REACTION_TYPES,
        HIGH_VALUE_FIELDS,
        MATERIAL_CLASS_RULES,
        MATERIAL_CLASSES,
        MATERIAL_KIND_TOKENS,
        PERIODIC_SYMBOLS,
        RELATION_FIELDS,
        SUPPORTED_MODELING_TASKS,
        TABLE_FIELDS,
        TRANSITION_OR_SUPPORT_TOKENS,
        KEYWORD_BUCKET_RULES,
        is_known_surface_term,
    )
    from paperread.surface.core.surface_indices import canonicalize_surface_index


@dataclass
class ExperienceItem:
    timestamp: str
    source: str
    field: str
    value: str
    kind: str
    context: str
    action: str
    anchor_material: str = ""


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


def _iter_formula_like_tokens(text: str) -> list[str]:
    tokens = re.findall(r"\b(?:[A-Z][a-z]?\d*){1,8}\b", text)
    cleaned: list[str] = []
    for token in tokens:
        if token in PERIODIC_SYMBOLS:
            cleaned.append(token)
            continue
        parts = re.findall(r"[A-Z][a-z]?", token)
        if parts and all(part in PERIODIC_SYMBOLS for part in parts):
            cleaned.append(token)
    return cleaned


def _extract_elements(text: str) -> list[str]:
    elements: list[str] = []
    for symbol in re.findall(r"\b[A-Z][a-z]?\b", text):
        if symbol in PERIODIC_SYMBOLS and symbol not in elements:
            elements.append(symbol)
    for token in _iter_formula_like_tokens(text):
        for symbol in re.findall(r"[A-Z][a-z]?", token):
            if symbol in PERIODIC_SYMBOLS and symbol not in elements:
                elements.append(symbol)
    return elements


def _extract_element_set(text: str) -> list[str]:
    return sorted(_extract_elements(text))


def _infer_material_kinds(text: str, field: str) -> list[str]:
    lowered = _normalize_term(text)
    kinds: list[str] = []
    for kind, tokens in MATERIAL_KIND_TOKENS.items():
        if any(token in lowered for token in tokens):
            kinds.append(kind)
    if field in {"surfaces", "Surface/Support", "slab_models"} and "surface" not in kinds:
        kinds.append("surface")
    return kinds


def _extract_loadings(text: str) -> list[str]:
    patterns = [
        r"\b\d+(?:\.\d+)?\s*(?:wt%|wt\.%|at%|at\.%|mol%|mol\.%|mass%|mass\.%)\s*[A-Za-z0-9+\-]*",
        r"\b\d+(?:\.\d+)?\s*(?:wt%|wt\.%|at%|at\.%|mol%|mol\.%|mass%|mass\.%)\b",
        r"\b\d+(?:\.\d+)?\s*(?:mg|g)\s*(?:cm-2|cm\^-2|g-1|wt-1)?\b",
    ]
    matches: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            cleaned = " ".join(match.split())
            if cleaned and cleaned not in matches:
                matches.append(cleaned)
    return matches


def _extract_component_compounds(text: str) -> list[str]:
    components: list[str] = []
    for token in re.split(r"[/@]| on |\+| with ", text):
        cleaned = token.strip(" ,;:()[]")
        if not cleaned:
            continue
        if cleaned not in components and (
            _extract_elements(cleaned)
            or any(kind in _normalize_term(cleaned) for kind in ("surface", "graphene", "carbon", "oxide", "ldh", "mos2"))
        ):
            components.append(cleaned)
    return components


def _split_supported_components(text: str) -> tuple[list[str], list[str]]:
    pieces = [part.strip(" ,;:()[]") for part in re.split(r"[/@]", text) if part.strip(" ,;:()[]")]
    if len(pieces) < 2:
        return [], []
    support_like = []
    loaded_like = []
    for idx, piece in enumerate(pieces):
        lowered = piece.lower()
        if idx == len(pieces) - 1 and any(token in lowered for token in ("o2", "oxide", "ldh", "carbon", "graphene", "mos2", "al2o3", "sio2", "support")):
            support_like.append(piece)
        else:
            loaded_like.append(piece)
    return support_like, loaded_like


def _split_cell(value: str) -> list[str]:
    parts = [part.strip() for part in value.replace(";", ",").split(",")]
    return [part for part in parts if part]


def _is_known(value: str) -> bool:
    return is_known_surface_term(value)


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


def _material_classes_for(value: str, field: str, anchor_material: str = "") -> list[str]:
    anchor_preferred_fields = {
        "applications", "Reaction Type", "adsorbates", "Adsorbate/Reactant",
        "active_sites", "Active Site", "clusters", "single_atoms",
        "Cluster/Single Atom", "dopants", "Dopant/Modifier", "facets", "Facet",
        "material_parameters", "Composition", "Loading",
    }
    if anchor_material and field in anchor_preferred_fields:
        anchor_lower = _normalize_term(anchor_material)
        anchor_classes = [
            material_class
            for material_class, tokens in MATERIAL_CLASS_RULES
            if any(token in anchor_lower for token in tokens)
        ]
        if anchor_classes:
            return anchor_classes

    lower = _normalize_term(value)
    classes = [
        material_class
        for material_class, tokens in MATERIAL_CLASS_RULES
        if any(token in lower for token in tokens)
    ]
    if not classes and anchor_material:
        anchor_lower = _normalize_term(anchor_material)
        classes = [
            material_class
            for material_class, tokens in MATERIAL_CLASS_RULES
            if any(token in anchor_lower for token in tokens)
        ]
    if classes:
        return classes
    if field in {
        "materials", "surfaces", "slab_models", "Material", "Surface/Support",
        "material_parameters", "Composition", "Loading", "applications",
        "Reaction Type", "adsorbates", "Adsorbate/Reactant", "active_sites",
        "Active Site", "clusters", "single_atoms", "Cluster/Single Atom",
        "dopants", "Dopant/Modifier", "facets", "Facet",
    } and anchor_material:
        return ["other_inorganic_materials"]
    if field in {"materials", "surfaces", "slab_models", "Material", "Surface/Support", "material_parameters", "Composition", "Loading"}:
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
        anchor_material = ""
        materials = extraction.get("materials", [])
        flattened_materials = _flatten(materials)
        if flattened_materials:
            anchor_material = flattened_materials[0]
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
                        anchor_material=anchor_material,
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
            anchor_material = _clean(row.get("Material"))
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
                            anchor_material=anchor_material,
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

        item_material_classes = _material_classes_for(item.value, item.field, item.anchor_material)
        for material_class in item_material_classes:
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


def _compact_class_entry(entry: dict[str, Any]) -> dict[str, Any]:
    compacted = {
        "term": entry.get("term", ""),
        "kind": entry.get("kind", ""),
        "research_category": entry.get("research_category", ""),
        "fields": list(entry.get("fields", [])),
        "count": int(entry.get("count", 0)),
    }
    contexts = [item for item in entry.get("contexts", []) if item]
    if contexts:
        compacted["example_contexts"] = contexts[:3]
    return compacted


def _build_keyword_inventory(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    inventory: dict[str, dict[str, dict[str, Any]]] = {}

    for entry in entries:
        fields = entry.get("fields", [])
        if not isinstance(fields, list):
            continue
        for bucket_name, bucket_fields in KEYWORD_BUCKET_RULES.items():
            if not any(field in bucket_fields for field in fields):
                continue
            normalized_term = _normalize_term(str(entry.get("term", "")))
            if not normalized_term:
                continue
            bucket = inventory.setdefault(bucket_name, {})
            item = bucket.setdefault(
                normalized_term,
                {
                    "term": entry.get("term", ""),
                    "count": 0,
                    "kind": entry.get("kind", ""),
                    "research_category": entry.get("research_category", ""),
                },
            )
            item["count"] += int(entry.get("count", 0))
            if str(entry.get("kind", "")).startswith("unknown"):
                item["kind"] = entry.get("kind", item["kind"])
            if not item.get("research_category") and entry.get("research_category"):
                item["research_category"] = entry["research_category"]

    return {
        bucket_name: sorted(
            bucket.values(),
            key=lambda item: (-int(item["count"]), str(item["term"]).casefold()),
        )
        for bucket_name, bucket in sorted(inventory.items())
    }


def _build_material_descriptors(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    descriptor_buckets: dict[str, dict[str, dict[str, Any]]] = {
        "elements": {},
        "material_kinds": {},
        "component_compounds": {},
        "element_sets": {},
        "approx_loadings": {},
    }

    def add(bucket_name: str, key: str, label: str, count: int) -> None:
        if not key:
            return
        bucket = descriptor_buckets[bucket_name]
        item = bucket.setdefault(key, {"term": label, "count": 0})
        item["count"] += count

    for entry in entries:
        term = str(entry.get("term", ""))
        count = int(entry.get("count", 0))
        fields = entry.get("fields", [])
        if not term or count <= 0:
            continue

        for symbol in _extract_elements(term):
            add("elements", symbol, symbol, count)

        kinds = _infer_material_kinds(term, fields[0] if isinstance(fields, list) and fields else "")
        for kind in kinds:
            add("material_kinds", kind, kind, count)

        components = _extract_component_compounds(term)
        for component in components:
            add("component_compounds", _normalize_term(component), component, count)

        element_set = _extract_element_set(term)
        if element_set:
            label = "{" + ", ".join(element_set) + "}"
            add("element_sets", "|".join(element_set), label, count)

        for loading in _extract_loadings(term):
            add("approx_loadings", _normalize_term(loading), loading, count)

    return {
        bucket_name: sorted(
            bucket.values(),
            key=lambda item: (-int(item["count"]), str(item["term"]).casefold()),
        )
        for bucket_name, bucket in descriptor_buckets.items()
        if bucket
    }


def _entries_for_fields(entries: list[dict[str, Any]], field_names: set[str]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for entry in entries:
        fields = entry.get("fields", [])
        if isinstance(fields, list) and any(field in field_names for field in fields):
            matched.append(entry)
    return matched


def _top_terms(entries: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    return [
        {"term": entry.get("term", ""), "count": int(entry.get("count", 0))}
        for entry in sorted(entries, key=lambda item: (-int(item.get("count", 0)), str(item.get("term", "")).casefold()))[:limit]
        if entry.get("term")
    ]


def _detect_coordination_patterns(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns: dict[str, int] = {}
    regexes = {
        "N-coordinated": r"\bN[- ]?coordin",
        "O-coordinated": r"\bO[- ]?coordin",
        "S-coordinated": r"\bS[- ]?coordin",
        "C-coordinated": r"\bC[- ]?coordin",
        "M-Nx": r"\bN\d\b|\bMN\d\b|\bM-N\d\b",
        "M-Ox": r"\bO\d\b|\bM-O\d\b",
        "M-Sx": r"\bS\d\b|\bM-S\d\b",
    }
    for entry in entries:
        term = str(entry.get("term", ""))
        count = int(entry.get("count", 0))
        for label, pattern in regexes.items():
            if re.search(pattern, term, flags=re.IGNORECASE):
                patterns[label] = patterns.get(label, 0) + count
    return [{"term": key, "count": value} for key, value in sorted(patterns.items(), key=lambda item: (-item[1], item[0]))]


def _detect_single_atom_centers(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for entry in entries:
        term = str(entry.get("term", ""))
        entry_count = int(entry.get("count", 0))
        for element in _extract_elements(term):
            counts[element] = counts.get(element, 0) + entry_count
    return [{"term": key, "count": value} for key, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _detect_exposed_surfaces(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    surface_like = []
    for entry in entries:
        term = str(entry.get("term", ""))
        if canonicalize_surface_index(term) or "surface" in term.lower() or "facet" in term.lower():
            surface_like.append(entry)
    return _top_terms(surface_like, limit=20)


def _detect_site_role_terms(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    role_patterns = {
        "top": r"\btop\b|\bontop\b|\batop\b",
        "bridge": r"\bbridge\b",
        "hollow": r"\bhollow\b",
        "three_fold": r"\bthree[- ]?fold\b|\b3[- ]?fold\b|\bfcc\b",
        "four_fold": r"\bfour[- ]?fold\b|\b4[- ]?fold\b",
        "hcp": r"\bhcp\b",
    }
    counts: dict[str, int] = {}
    for entry in entries:
        term = str(entry.get("term", ""))
        if not term:
            continue
        count = int(entry.get("count", 0))
        lowered = term.lower()
        for role, pattern in role_patterns.items():
            if re.search(pattern, lowered):
                counts[role] = counts.get(role, 0) + count
    return [{"term": role, "count": count} for role, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _build_surface_site_contexts(
    material_class: str,
    material_entries: list[dict[str, Any]],
    support_entries: list[dict[str, Any]],
    facet_entries: list[dict[str, Any]],
    active_site_entries: list[dict[str, Any]],
    adsorption_site_entries: list[dict[str, Any]],
    state_entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    surface_terms = _top_terms(material_entries + support_entries, 10)
    facet_terms = _top_terms(facet_entries, 10)
    active_site_terms = _top_terms(active_site_entries, 10)
    adsorption_site_terms = _top_terms(adsorption_site_entries, 10)
    site_roles = _detect_site_role_terms(active_site_entries + adsorption_site_entries)

    contexts: list[dict[str, Any]] = []
    if surface_terms or facet_terms or active_site_terms or adsorption_site_terms:
        contexts.append(
            {
                "surface_family": material_class,
                "surface_terms": surface_terms,
                "facet_terms": facet_terms,
                "active_site_terms": active_site_terms,
                "adsorption_site_terms": adsorption_site_terms,
                "site_role_terms": site_roles,
                "relation": (
                    "metal-surface site geometry"
                    if material_class in {"metals_alloys", "supported_catalysts", "single_atom_catalysts"}
                    else "surface active-site correlation"
                ),
            }
        )
    return contexts


def _surface_index_material_context(entries: list[dict[str, Any]]) -> str | None:
    priority_patterns = [
        (r"β-?coooh|beta-?coooh|coooh", "β-CoOOH"),
        (r"\bzno\b", "ZnO"),
        (r"\bru\b", "Ru"),
    ]
    text = " ".join(str(entry.get("term", "")) for entry in entries).casefold()
    for pattern, material in priority_patterns:
        if re.search(pattern, text):
            return material
    return None


def _detect_surface_index_mappings(
    entries: list[dict[str, Any]],
    material_context: str | None = None,
) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for entry in _top_terms(entries, limit=50):
        term = str(entry.get("term", ""))
        mapping = canonicalize_surface_index(term, material_context=material_context)
        if not mapping:
            continue
        mappings.append(
            {
                "term": term,
                "count": int(entry.get("count", 0)),
                "input_notation": mapping["input_notation"],
                "input_indices": mapping["input_indices"],
                "canonical_input_indices": mapping["canonical_input_indices"],
                "software_miller_index": mapping["software_miller_index"],
                "software_facet": mapping["software_facet"],
                "material": mapping.get("material"),
                "crystal_system": mapping.get("crystal_system"),
                "space_group": mapping.get("space_group"),
                "warnings": mapping.get("warnings", []),
            }
        )
    return mappings[:20]


def _detect_spacegroup_terms(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched = []
    for entry in entries:
        term = str(entry.get("term", ""))
        lowered = term.lower()
        if match_crystal_structure_term(term) or any(token in lowered for token in ("space group", "cubic", "tetragonal", "orthorhombic", "monoclinic", "trigonal", "hexagonal")):
            matched.append(entry)
    return _top_terms(matched, limit=20)


def _detect_crystal_structure_terms(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    detected: dict[str, dict[str, Any]] = {}
    for entry in entries:
        term = str(entry.get("term", ""))
        match = match_crystal_structure_term(term)
        if not match:
            continue
        key = str(match["term"])
        current = detected.setdefault(
            key,
            {
                "term": key,
                "count": 0,
                "family": match.get("family"),
                "crystal_system": match.get("crystal_system"),
                "typical_space_group": match.get("typical_space_group"),
            },
        )
        current["count"] = int(current["count"]) + int(entry.get("count", 0))
    return sorted(detected.values(), key=lambda item: (-int(item["count"]), str(item["term"])))[:20]


def _build_class_profile(material_class: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    material_entries = _entries_for_fields(entries, {"materials", "Material", "material_parameters", "Composition"})
    support_entries = _entries_for_fields(entries, {"surfaces", "Surface/Support", "slab_models"})
    facet_entries = _entries_for_fields(entries, {"facets", "Facet", "surfaces", "Surface/Support"})
    dopant_entries = _entries_for_fields(entries, {"dopants", "Dopant/Modifier", "modifiers"})
    active_site_entries = _entries_for_fields(entries, {"active_sites", "Active Site"})
    adsorption_site_entries = _entries_for_fields(entries, {"adsorption_sites", "Adsorption Site"})
    cluster_entries = _entries_for_fields(entries, {"clusters", "single_atoms", "Cluster/Single Atom"})
    composition_entries = _entries_for_fields(entries, {"material_parameters", "Composition", "Loading"})
    state_entries = _entries_for_fields(entries, {"surface_terminations", "Surface Termination", "defects", "vacancy_models", "Defect"})
    reaction_entries = _entries_for_fields(entries, {"applications", "Reaction Type"})
    surface_index_context = _surface_index_material_context(material_entries + support_entries)
    crystal_structure_terms = _detect_crystal_structure_terms(material_entries + support_entries + composition_entries)
    surface_site_contexts = _build_surface_site_contexts(
        material_class,
        material_entries,
        support_entries,
        facet_entries,
        active_site_entries,
        adsorption_site_entries,
        state_entries,
    )

    if material_class == "supported_catalysts":
        support_candidates = []
        loaded_candidates = []

        for entry in material_entries + support_entries + composition_entries:
            term = str(entry.get("term", ""))
            lowered = term.lower()
            split_supports, split_loaded = _split_supported_components(term)
            for component in split_supports:
                support_candidates.append({"term": component, "count": int(entry.get("count", 0))})
            for component in split_loaded:
                loaded_candidates.append({"term": component, "count": int(entry.get("count", 0))})
            if any(token in lowered for token in ("ceo2", "tio2", "al2o3", "sio2", "graphene", "carbon", "ldh", "mos2", "support")):
                for component in _extract_component_compounds(term) or [term]:
                    if any(token in component.lower() for token in ("ceo2", "tio2", "al2o3", "sio2", "graphene", "carbon", "ldh", "mos2", "support")):
                        support_candidates.append({"term": component, "count": int(entry.get("count", 0))})

        for entry in cluster_entries + dopant_entries + active_site_entries + material_entries:
            term = str(entry.get("term", ""))
            if any(symbol in term for symbol in TRANSITION_OR_SUPPORT_TOKENS) and "support" not in term.lower():
                loaded_candidates.append(entry)

        return {
            "descriptor_schema": "supported_catalyst_profile",
            "elements": _build_material_descriptors(entries).get("elements", []),
            "material_kind": [{"term": "supported_catalyst", "count": len(entries)}],
            "support_components": _top_terms(support_candidates, 20),
            "loaded_components": _top_terms(loaded_candidates, 20),
            "exposed_surfaces": _detect_exposed_surfaces(facet_entries),
            "surface_index_mappings": _detect_surface_index_mappings(facet_entries, surface_index_context),
            "crystal_structure_terms": crystal_structure_terms,
            "surface_site_contexts": surface_site_contexts,
            "approx_loadings": _build_material_descriptors(composition_entries).get("approx_loadings", []),
            "reaction_families": _top_terms(reaction_entries, 20),
        }

    if material_class in {"carbon_materials", "single_atom_catalysts"}:
        return {
            "descriptor_schema": "carbon_or_sac_profile",
            "elements": _build_material_descriptors(entries).get("elements", []),
            "host_structures": _top_terms([entry for entry in material_entries + support_entries if any(token in str(entry.get("term", "")).lower() for token in ("graphene", "carbon", "g-c3n4", "cnt", "nanotube"))], 20),
            "dopant_or_loaded_species": _top_terms(dopant_entries + cluster_entries, 20),
            "coordination_environments": _detect_coordination_patterns(active_site_entries + state_entries + material_entries),
            "single_atom_centers": _detect_single_atom_centers(cluster_entries + active_site_entries + dopant_entries),
            "surface_site_contexts": _build_surface_site_contexts(
                material_class,
                material_entries,
                support_entries,
                facet_entries,
                active_site_entries,
                adsorption_site_entries,
                state_entries,
            ),
            "reaction_families": _top_terms(reaction_entries, 20),
        }

    if material_class == "metals_alloys":
        return {
            "descriptor_schema": "alloy_profile",
            "elements": _build_material_descriptors(entries).get("elements", []),
            "alloy_components": _top_terms(material_entries, 30),
            "approx_compositions": _top_terms(composition_entries, 20),
            "exposed_surfaces": _detect_exposed_surfaces(facet_entries),
            "surface_index_mappings": _detect_surface_index_mappings(facet_entries, surface_index_context),
            "crystal_structure_terms": crystal_structure_terms,
            "surface_states": _top_terms(state_entries, 20),
            "reaction_families": _top_terms(reaction_entries, 20),
        }

    if material_class == "oxides":
        return {
            "descriptor_schema": "oxide_profile",
            "elements": _build_material_descriptors(entries).get("elements", []),
            "oxide_components": _top_terms([entry for entry in material_entries if "o" in _normalize_term(str(entry.get("term", "")))], 30),
            "crystal_or_spacegroup_terms": _detect_spacegroup_terms(material_entries + composition_entries),
            "crystal_structure_terms": crystal_structure_terms,
            "surface_site_contexts": surface_site_contexts,
            "exposed_surfaces": _detect_exposed_surfaces(facet_entries),
            "surface_index_mappings": _detect_surface_index_mappings(facet_entries, surface_index_context),
            "defect_or_termination_states": _top_terms(state_entries, 20),
            "active_site_terms": _top_terms(active_site_entries, 20),
            "reaction_families": _top_terms(reaction_entries, 20),
        }

    if material_class == "perovskites_spinels":
        return {
            "descriptor_schema": "perovskite_spinel_profile",
            "elements": _build_material_descriptors(entries).get("elements", []),
            "framework_components": _top_terms(material_entries, 30),
            "a_b_site_related_terms": _top_terms([entry for entry in material_entries + composition_entries if any(token in str(entry.get("term", "")).lower() for token in ("abo3", "ab2o4", "a-site", "b-site", "perovskite", "spinel"))], 20),
            "crystal_or_spacegroup_terms": _detect_spacegroup_terms(material_entries + composition_entries),
            "crystal_structure_terms": crystal_structure_terms,
            "surface_site_contexts": surface_site_contexts,
            "exposed_surfaces": _detect_exposed_surfaces(facet_entries),
            "surface_index_mappings": _detect_surface_index_mappings(facet_entries, surface_index_context),
            "reaction_families": _top_terms(reaction_entries, 20),
        }

    return {
        "descriptor_schema": "generic_material_profile",
        "elements": _build_material_descriptors(entries).get("elements", []),
        "components": _top_terms(material_entries, 20),
        "crystal_structure_terms": crystal_structure_terms,
        "surface_site_contexts": surface_site_contexts,
        "surface_states": _top_terms(state_entries, 20),
        "reaction_families": _top_terms(reaction_entries, 20),
    }


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
            "schema_version": "2.0",
            "material_class": material_class,
            "updated_at": _now(),
            "summary": {
                "terms": len(merged_entries),
                "known_useful": sum(1 for entry in merged_entries if entry.get("kind") == "known_useful"),
                "unknown": sum(1 for entry in merged_entries if entry.get("kind") != "known_useful"),
            },
            "keyword_inventory": _build_keyword_inventory(merged_entries),
            "material_descriptors": _build_material_descriptors(merged_entries),
            "class_profile": _build_class_profile(material_class, merged_entries),
            "entries": [_compact_class_entry(entry) for entry in merged_entries],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written[material_class] = str(path)

    target_material_class_dir = (Path(output_dir) / "material_classes").resolve()
    if written and target_material_class_dir == DEFAULT_MATERIAL_CLASS_DIR.resolve():
        build_surface_parameter_registry(target_material_class_dir)

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
            "schema_version": "2.0",
            "material_class": material_class,
            "updated_at": _now(),
            "summary": {
                "terms": 0,
                "known_useful": 0,
                "unknown": 0,
            },
            "keyword_inventory": {},
            "material_descriptors": {},
            "class_profile": {},
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
