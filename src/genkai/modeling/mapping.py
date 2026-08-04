from __future__ import annotations

import argparse
import csv
from importlib.resources import files
import json
import re
from pathlib import Path
from typing import Any

from genkai.literature.surface.core.chemical_vocabulary import (
    METAL_SYMBOLS,
    extract_element_symbols,
    normalize_element_name,
    normalize_material_terms,
)
from genkai.literature.surface.core.surface_indices import (
    canonicalize_surface_index,
    normalize_surface_facet_for_software,
)
from genkai.literature.surface.core.surface_ontology import (
    EXECUTABLE_TASKS,
    GENERIC_REACTION_TYPES,
    MATERIAL_CLASS_RULES,
    REACTION_KEYWORDS,
    SUPPORTED_MODELING_TASKS,
    material_class_rule_matches,
)

TASK_SCHEMA_PACKAGE = "genkai.modeling.schema"
TASK_SCHEMA_NAME = "task_parameter_schema.json"
TASK_SCHEMA_RESOURCE = f"{TASK_SCHEMA_PACKAGE}:{TASK_SCHEMA_NAME}"

def _clean_scalar(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "na", "none", "null", "nan", "-"}:
        return None
    return text


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = []
        for item in value.values():
            items.extend(_to_list(item))
    else:
        items = [part.strip() for part in str(value).split(",")]

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_scalar(item)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_strings(item))
        return flattened
    if isinstance(value, dict):
        flattened = []
        for item in value.values():
            flattened.extend(_flatten_strings(item))
        return flattened
    text = _clean_scalar(value)
    return [text] if text else []


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        text = _clean_scalar(value)
        if text:
            return text
    return None


def _normalize_facet(raw: str, material_context: str | None = None) -> str:
    return normalize_surface_facet_for_software(raw, material_context)


def _infer_surface_formula(surface_terms: list[str]) -> str | None:
    """Extract an explicit oxide formula without guessing from a structure family."""
    for term in surface_terms:
        for candidate in re.findall(r"(?:[A-Z][a-z]?\d*){2,}", term):
            if "O" not in extract_element_symbols(candidate):
                continue
            if re.fullmatch(r"(?:[A-Z][a-z]?\d*)+", candidate):
                return candidate
    return None


def _normalize_species(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    exact = normalize_element_name(text)
    if exact:
        return exact
    symbols = extract_element_symbols(text, include_material_aliases=False)
    return symbols[0] if symbols else None


def _normalize_reaction(raw: str) -> str:
    lowered = raw.strip().lower()
    for keyword, normalized in REACTION_KEYWORDS:
        if keyword in lowered:
            return normalized
    if "oxidation" in lowered:
        return "oxidation"
    if "reduction" in lowered:
        return "reduction"
    if "adsorption" in lowered:
        return "adsorption"
    return raw.strip()


def _infer_cluster_structures(cluster_entries: list[str]) -> list[str]:
    structures: list[str] = []
    joined = " ".join(cluster_entries).lower()
    for label in ("fcc", "hcp", "bcc"):
        if label in joined:
            structures.append(label)
    return structures


def _infer_cluster_atom_count(cluster_entries: list[str]) -> dict[str, Any] | None:
    for entry in cluster_entries:
        text = entry.strip()
        if not text:
            continue
        match = re.search(
            r"\b(?P<element>[A-Z][a-z]?)(?:\s*[-_ ]?\s*)(?P<count>[1-9]\d{0,3})\b",
            text,
        )
        if match and int(match.group("count")) >= 2:
            return {
                "value": int(match.group("count")),
                "source_term": text,
                "element": match.group("element"),
            }
        match = re.search(r"\b(?P<count>[1-9]\d{0,3})\s*[- ]?atom\b", text, flags=re.IGNORECASE)
        if match and int(match.group("count")) >= 2:
            return {
                "value": int(match.group("count")),
                "source_term": text,
                "element": _normalize_species(text),
            }
    return None


def _normalize_adsorbate_candidate(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    text = text.replace("adsorbed ", "").replace("Adsorbed ", "")
    text = text.replace("adsorbate ", "").replace("Adsorbate ", "")
    text = text.strip(" .;:")
    text = text.replace("*", "")
    text = re.sub(r"\bads\b", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return None
    return text


def _adsorbate_candidates(adsorbates: list[str]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in adsorbates:
        normalized = _normalize_adsorbate_candidate(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append({"raw": item, "normalized_species": normalized})
    return candidates


def _infer_site_symbols(active_sites: list[str]) -> list[str]:
    symbols: list[str] = []
    for item in active_sites:
        symbol = _normalize_species(item)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _infer_explicit_count(entries: list[str], noun_pattern: str) -> dict[str, Any] | None:
    number_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
    for entry in entries:
        match = re.search(
            rf"\b(?P<count>[1-9]\d*|{'|'.join(number_words)})\s+(?:surface\s+|oxygen\s+)?{noun_pattern}\b",
            entry,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        raw_count = match.group("count").lower()
        return {
            "value": int(raw_count) if raw_count.isdigit() else number_words[raw_count],
            "source_term": entry,
        }
    return None


def _infer_site_group_size(adsorption_sites: list[str]) -> dict[str, Any] | None:
    denticity = (("monodentate", 1), ("bidentate", 2), ("tridentate", 3))
    for entry in adsorption_sites:
        lowered = entry.lower()
        for term, count in denticity:
            if term in lowered:
                return {"value": count, "source_term": entry, "term": term}
    return None


def _infer_site_roles(*values: list[str]) -> list[str]:
    joined = " ".join(item.lower() for group in values for item in group)
    roles: list[str] = []
    role_patterns = [
        ("top", ("top", "ontop", "atop")),
        ("bridge", ("bridge",)),
        ("hollow", ("hollow",)),
        ("three_fold", ("three-fold", "three fold", "3-fold", "fcc")),
        ("four_fold", ("four-fold", "four fold", "4-fold")),
        ("hcp", ("hcp",)),
    ]
    for label, tokens in role_patterns:
        if any(token in joined for token in tokens):
            roles.append(label)
    return roles


def _build_surface_site_contexts(
    materials: list[str],
    supports: list[str],
    facets: list[str],
    active_sites: list[str],
    adsorption_sites: list[str],
    surface_indices: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    surface_terms = [item for item in materials + supports if item]
    facet_terms = [item for item in facets if item]
    active_terms = [item for item in active_sites if item]
    adsorption_terms = [item for item in adsorption_sites if item]
    roles = _infer_site_roles(active_terms, adsorption_terms)
    contexts: list[dict[str, Any]] = []
    if surface_terms or facet_terms or active_terms or adsorption_terms or surface_indices:
        contexts.append(
            {
                "surface_terms": surface_terms[:8],
                "facet_terms": facet_terms[:8],
                "active_site_terms": active_terms[:8],
                "adsorption_site_terms": adsorption_terms[:8],
                "site_role_terms": roles,
                "surface_indices": surface_indices[:8],
                "relation": "surface-site-facet association",
            }
        )
    return contexts


def _pick_reaction_type(extraction: dict[str, Any], table_row: dict[str, str] | None) -> str | None:
    table_reaction = _clean_scalar((table_row or {}).get("Reaction Type"))
    application_reaction = _first_nonempty(*_flatten_strings(extraction.get("applications")))
    if application_reaction and table_reaction and table_reaction.strip().lower() in GENERIC_REACTION_TYPES:
        return application_reaction
    return _first_nonempty(table_reaction, application_reaction)


def _infer_material_classes(values: list[str]) -> list[str]:
    normalized_materials = normalize_material_terms(values)
    normalized_formulas = [
        item["normalized_formula"]
        for item in normalized_materials
        if item.get("normalized_formula")
    ]
    joined = " ".join(values + normalized_formulas).lower()
    matches = [
        name
        for name, rules in MATERIAL_CLASS_RULES
        if name != "metals_alloys"
        if any(material_class_rule_matches(joined, rule) for rule in rules)
    ]
    element_symbols = {
        symbol
        for item in normalized_materials
        for symbol in item.get("elements", [])
    }
    metal_context = any(
        token in joined
        for token in ("alloy", "cluster", "nanocluster", "nanoparticle", "single atom")
    )
    pure_metal_context = any(normalize_element_name(value) for value in values)
    if (
        element_symbols.intersection(METAL_SYMBOLS)
        and (metal_context or pure_metal_context)
        and "metals_alloys" not in matches
    ):
        matches.append("metals_alloys")
    if not matches:
        return ["other_inorganic_materials"]
    return matches


def _load_relations(relations_jsonl: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    content = Path(relations_jsonl).read_text(encoding="utf-8").strip()
    if not content:
        return rows

    decoder = json.JSONDecoder()
    index = 0
    length = len(content)
    while index < length:
        while index < length and content[index].isspace():
            index += 1
        if index >= length:
            break
        payload, index = decoder.raw_decode(content, index)
        if not isinstance(payload, dict):
            continue
        extraction = payload.get("extraction", payload)
        rows.append(
            {
                "id": payload.get("id"),
                "title": payload.get("title") or payload.get("Title"),
                "text": payload.get("text") or payload.get("Text"),
                "extraction": extraction,
            }
        )
    return rows


def _load_table(table_csv: str | None) -> list[dict[str, str]]:
    if not table_csv:
        return []
    with open(table_csv, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _index_table_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        key = _first_nonempty(row.get("Index"), row.get("id"), row.get("ID"))
        if key:
            indexed[key] = row
    return indexed


def _infer_tasks(
    extraction: dict[str, Any],
    table_row: dict[str, str] | None,
    material_classes: list[str],
    modeling_keywords: list[str],
) -> tuple[list[str], dict[str, Any]]:
    tasks: list[str] = []
    evidence: dict[str, list[str]] = {}
    rejected_recommendations: list[dict[str, str]] = []

    def add_task(task: str, *terms: str) -> None:
        if task not in tasks:
            tasks.append(task)
        task_evidence = evidence.setdefault(task, [])
        for term in terms:
            if term and term not in task_evidence:
                task_evidence.append(term)

    keyword_text = " ".join(modeling_keywords).lower()
    vacancy_material_classes = {
        "oxides",
        "hydroxides_oxyhydroxides",
        "perovskites_spinels",
        "defect_engineered_materials",
        "supported_catalysts",
    }
    cluster_material_classes = {"supported_catalysts", "metals_alloys"}
    material_candidates = ["adsorbate_landscape"]
    if vacancy_material_classes.intersection(material_classes):
        material_candidates.insert(0, "vacancy_landscape")
    if cluster_material_classes.intersection(material_classes):
        material_candidates.append("surface_cluster_builder")

    recommended = [
        task
        for task in _flatten_strings(extraction.get("recommended_modeling_tasks"))
        if task in SUPPORTED_MODELING_TASKS
    ]
    for task in recommended:
        if task in EXECUTABLE_TASKS and task not in material_candidates:
            rejected_recommendations.append(
                {
                    "task": task,
                    "reason": "The recommended executable task is not compatible with the inferred material classes.",
                }
            )
            continue
        add_task(task, f"recommended_modeling_tasks:{task}")

    defects = " ".join(
        _flatten_strings(extraction.get("defects"))
        + _flatten_strings(extraction.get("vacancy_models"))
        + _flatten_strings((table_row or {}).get("Defect"))
    ).lower()
    vacancy_cues = [item for item in [defects, *modeling_keywords] if "vacan" in item.lower()]
    if vacancy_cues and "vacancy_landscape" in material_candidates:
        add_task("vacancy_landscape", *vacancy_cues)

    adsorption = (
        _flatten_strings(extraction.get("adsorbates"))
        + _flatten_strings(extraction.get("adsorption_sites"))
        + _flatten_strings(extraction.get("coverage"))
        + _flatten_strings((table_row or {}).get("Adsorbate/Reactant"))
        + _flatten_strings((table_row or {}).get("Adsorption Site"))
        + _flatten_strings((table_row or {}).get("Coverage"))
    )
    adsorption_keyword_cues = [
        item
        for item in modeling_keywords
        if any(token in item.lower() for token in ("adsor", "coverage", "coadsor", "intermediate"))
    ]
    if adsorption or adsorption_keyword_cues:
        add_task("adsorbate_landscape", *(adsorption + adsorption_keyword_cues))

    clusters = (
        _flatten_strings(extraction.get("clusters"))
        + _flatten_strings((table_row or {}).get("Cluster/Single Atom"))
    )
    cluster_text = " ".join(clusters).lower()
    cluster_keyword_cues = [
        item
        for item in modeling_keywords
        if any(token in item.lower() for token in ("cluster", "nanoparticle", "nanocluster"))
    ]
    if (
        any(word in cluster_text for word in {"cluster", "nanocluster", "nanoparticle"})
        or cluster_keyword_cues
    ) and "surface_cluster_builder" in material_candidates:
        add_task("surface_cluster_builder", *(clusters + cluster_keyword_cues))

    singles = (
        _flatten_strings(extraction.get("single_atoms"))
        + _flatten_strings((table_row or {}).get("Cluster/Single Atom"))
        + _flatten_strings((table_row or {}).get("Active Site"))
    )
    single_text = " ".join(singles).lower()
    if "single atom" in single_text:
        add_task("single_atom_site", *singles)

    dopants = _flatten_strings(extraction.get("dopants")) + _flatten_strings((table_row or {}).get("Dopant/Modifier"))
    if dopants:
        add_task("doped_surface", *dopants)

    terminations = _flatten_strings(extraction.get("surface_terminations")) + _flatten_strings((table_row or {}).get("Surface Termination"))
    if terminations:
        add_task("surface_functionalization", *terminations)

    surfaces = (
        _flatten_strings(extraction.get("surfaces"))
        + _flatten_strings(extraction.get("slab_models"))
        + _flatten_strings(extraction.get("facets"))
        + _flatten_strings((table_row or {}).get("Surface/Support"))
        + _flatten_strings((table_row or {}).get("Facet"))
    )
    if surfaces:
        add_task("slab_generation", *surfaces)

    return tasks, {
        "selection_order": ["material_class", "research_keywords_and_explicit_fields"],
        "material_classes": material_classes,
        "material_compatible_executable_tasks": material_candidates,
        "research_keywords": modeling_keywords,
        "keyword_text": keyword_text,
        "selected_task_evidence": evidence,
        "rejected_recommendations": rejected_recommendations,
    }


def _load_surface_modeling_parameter_schema() -> dict[str, Any]:
    resource = files(TASK_SCHEMA_PACKAGE).joinpath(TASK_SCHEMA_NAME)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    tasks = payload.get("tasks")
    if (
        payload.get("schema_version") != "1.0"
        or not isinstance(tasks, dict)
        or not tasks
    ):
        raise ValueError("invalid canonical surface-modeling task schema")
    return {
        "schema_path": TASK_SCHEMA_RESOURCE,
        "schema_resource": TASK_SCHEMA_RESOURCE,
        "schema_version": payload["schema_version"],
        "tasks": tasks,
    }


def _build_task_inputs(task_name: str, extraction: dict[str, Any], table_row: dict[str, str] | None) -> dict[str, Any]:
    payload = {
        "material": _first_nonempty(
            _first_nonempty(*_flatten_strings(extraction.get("materials"))),
            (table_row or {}).get("Material"),
        ),
        "surfaces": _to_list(extraction.get("surfaces")) or _to_list((table_row or {}).get("Surface/Support")),
        "facets": [_normalize_facet(item) for item in (_to_list(extraction.get("facets")) or _to_list((table_row or {}).get("Facet")))],
        "active_sites": _to_list(extraction.get("active_sites")) or _to_list((table_row or {}).get("Active Site")),
        "reaction_type": _first_nonempty((table_row or {}).get("Reaction Type")),
    }
    if task_name == "vacancy_landscape":
        payload["defects"] = _to_list(extraction.get("defects")) or _to_list((table_row or {}).get("Defect"))
        payload["vacancy_models"] = _to_list(extraction.get("vacancy_models"))
        payload["explicit_vacancy_count"] = _infer_explicit_count(
            payload["defects"] + payload["vacancy_models"],
            r"vacanc(?:y|ies)",
        )
    elif task_name == "adsorbate_landscape":
        payload["adsorbates"] = _to_list(extraction.get("adsorbates")) or _to_list((table_row or {}).get("Adsorbate/Reactant"))
        payload["adsorbate_species"] = _adsorbate_candidates(payload["adsorbates"])
        payload["adsorption_sites"] = _to_list(extraction.get("adsorption_sites")) or _to_list((table_row or {}).get("Adsorption Site"))
        payload["site_group_size"] = _infer_site_group_size(payload["adsorption_sites"])
        payload["coverage"] = _to_list(extraction.get("coverage")) or _to_list((table_row or {}).get("Coverage"))
    elif task_name == "surface_cluster_builder":
        payload["clusters"] = _to_list(extraction.get("clusters")) or _to_list((table_row or {}).get("Cluster/Single Atom"))
        direct_cluster_species = [
            species
            for species in (_normalize_species(item) for item in payload["clusters"])
            if species
        ]
        payload["cluster_species"] = direct_cluster_species
        payload["cluster_species_source"] = "clusters" if direct_cluster_species else None
        if not direct_cluster_species and payload["clusters"]:
            for source_field, candidates in (
                ("active_sites", payload["active_sites"]),
                ("material", [payload["material"]]),
            ):
                metals = [
                    symbol
                    for candidate in candidates
                    if candidate
                    for symbol in extract_element_symbols(candidate, include_material_aliases=False)
                    if symbol in METAL_SYMBOLS
                ]
                if metals:
                    payload["cluster_species"] = [metals[0]]
                    payload["cluster_species_source"] = source_field
                    break
        payload["cluster_atom_count"] = _infer_cluster_atom_count(payload["clusters"])
        payload["cluster_structures"] = _infer_cluster_structures(payload["clusters"])
    return payload


def _build_argument_template(
    task_name: str,
    task_inputs: dict[str, Any],
    normalized_mapping: dict[str, Any],
    parameter_schema_registry: dict[str, Any],
) -> dict[str, Any]:
    task_schema = parameter_schema_registry["tasks"].get(task_name, {})
    parameters = task_schema.get("parameters", {})
    argument_values = {name: None for name in parameters}
    argument_sources: dict[str, dict[str, Any]] = {}

    def mark(
        parameter_name: str,
        *,
        value: Any,
        status: str,
        reason: str,
        confidence: str = "medium",
        source_field: str | None = None,
        source_term: str | None = None,
        from_task_inputs: list[str] | None = None,
        from_normalized_mapping: list[str] | None = None,
        depends_on: list[str] | None = None,
    ) -> None:
        argument_values[parameter_name] = value
        argument_sources[parameter_name] = {
            "status": status,
            "confidence": confidence,
            "source_field": source_field,
            "source_term": source_term,
            "reason": reason,
            "from_task_inputs": from_task_inputs or [],
            "from_normalized_mapping": from_normalized_mapping or [],
            "depends_on": depends_on or [],
        }

    if "task_name" in parameters:
        mark(
            "task_name",
            value=task_name,
            status="auto",
            confidence="high",
            reason="Executable task name is already selected by ptomodel.",
        )

    if task_name == "adsorbate_landscape":
        site_symbols = _infer_site_symbols(task_inputs.get("active_sites", []))
        if site_symbols:
            mark(
                "site_symbols",
                value=",".join(site_symbols),
                status="auto",
                confidence="high",
                source_field="active_sites",
                source_term=task_inputs.get("active_sites", [None])[0],
                reason="Active-site labels mention concrete element symbols that can seed adsorption-site detection.",
                from_task_inputs=["active_sites"],
            )
        site_group_size = task_inputs.get("site_group_size")
        if site_group_size:
            mark(
                "site_group_size",
                value=site_group_size["value"],
                status="auto",
                confidence="high",
                source_field="adsorption_sites",
                source_term=site_group_size["source_term"],
                reason="Explicit denticity translates directly to the number of neighboring surface sites used by one adsorbate.",
                from_task_inputs=["adsorption_sites", "site_group_size"],
            )
    elif task_name == "vacancy_landscape":
        explicit_vacancy_count = task_inputs.get("explicit_vacancy_count")
        if explicit_vacancy_count:
            mark(
                "vacancy_counts",
                value=str(explicit_vacancy_count["value"]),
                status="auto",
                confidence="high",
                source_field="defects",
                source_term=explicit_vacancy_count["source_term"],
                reason="The paper phrase states an explicit vacancy count.",
                from_task_inputs=["defects", "vacancy_models", "explicit_vacancy_count"],
            )
    elif task_name == "surface_cluster_builder":
        surface_formula = _infer_surface_formula(task_inputs.get("surfaces", []))
        if surface_formula and "surface_formula" in parameters:
            mark(
                "surface_formula",
                value=surface_formula,
                status="auto",
                confidence="high",
                source_field="surfaces",
                source_term=_first_nonempty(*(task_inputs.get("surfaces") or [])),
                reason="An explicit oxide formula can retrieve the bulk reference before stable-facet slab generation.",
                from_task_inputs=["surfaces"],
            )
        cluster_species = task_inputs.get("cluster_species", [])
        if cluster_species:
            cluster_species_source = task_inputs.get("cluster_species_source") or "clusters"
            mark(
                "cluster_element",
                value=cluster_species[0],
                status="auto",
                confidence="high" if cluster_species_source == "clusters" else "medium",
                source_field=cluster_species_source,
                source_term=(task_inputs.get(cluster_species_source) or [None])[0]
                if isinstance(task_inputs.get(cluster_species_source), list)
                else task_inputs.get(cluster_species_source),
                reason=(
                    "Cluster species normalized from paper cluster mentions."
                    if cluster_species_source == "clusters"
                    else "Generic nanoparticle evidence lacks an element; use the explicit metal active-site/material context from the same record."
                ),
                from_task_inputs=["cluster_species", cluster_species_source],
            )
            if "cluster_from_mp" in parameters:
                mark(
                    "cluster_from_mp",
                    value=True,
                    status="auto",
                    confidence="high",
                    source_field="clusters",
                    source_term=(task_inputs.get("clusters") or [None])[0],
                    reason="Retrieve the elemental bulk reference and stable crystal family from Materials Project before cluster construction.",
                    from_task_inputs=["cluster_species"],
                )
        cluster_atom_count = task_inputs.get("cluster_atom_count")
        if cluster_atom_count:
            mark(
                "cluster_atoms",
                value=cluster_atom_count["value"],
                status="auto",
                confidence="high",
                source_field="clusters",
                source_term=cluster_atom_count["source_term"],
                reason="Cluster size is explicitly encoded in the cluster formula or phrase.",
                from_task_inputs=["clusters", "cluster_atom_count"],
            )
        cluster_structures = task_inputs.get("cluster_structures", [])
        if cluster_structures:
            mark(
                "cluster_structures",
                value=cluster_structures,
                status="auto",
                confidence="high",
                source_field="clusters",
                source_term=(task_inputs.get("clusters") or [None])[0],
                reason="Cluster text explicitly mentions crystal-structure keywords.",
                from_task_inputs=["clusters"],
            )

    for parameter_name, parameter_spec in parameters.items():
        if parameter_name in argument_sources:
            continue

        if (
            task_name == "surface_cluster_builder"
            and parameter_name == "cluster_bulk_file"
            and argument_values.get("cluster_element")
            and not argument_values.get("cluster_from_mp")
        ):
            mark(
                parameter_name,
                value=None,
                status="alternative_not_selected",
                confidence="high",
                source_field="clusters",
                source_term=_first_nonempty(*(task_inputs.get("clusters") or [])),
                reason="An explicit cluster element is sufficient for the builder; a bulk file is an optional alternative source of element and lattice data.",
                from_task_inputs=["cluster_species"],
            )
        elif (
            task_name == "surface_cluster_builder"
            and parameter_name == "surface"
            and argument_values.get("surface_formula")
        ):
            mark(
                parameter_name,
                value=None,
                status="alternative_not_selected",
                confidence="high",
                source_field="surfaces",
                source_term=_first_nonempty(*(task_inputs.get("surfaces") or [])),
                reason="The formula selects the Materials Project bulk-to-stable-slab route instead of an existing surface path.",
                from_task_inputs=["surfaces"],
            )
        elif task_name == "surface_cluster_builder" and parameter_name == "surface_facet":
            facet_set = normalized_mapping.get("facet_set") or []
            if facet_set:
                mark(
                    parameter_name,
                    value=facet_set[0],
                    status="auto",
                    confidence="high",
                    source_field="facets",
                    source_term=facet_set[0],
                    reason="The paper supplies an explicit surface facet.",
                    from_normalized_mapping=["facet_set"],
                )
            else:
                mark(
                    parameter_name,
                    value=None,
                    status="stable_facet_registry_or_manual",
                    confidence="medium",
                    source_field="facets",
                    source_term=None,
                    reason="No paper facet is available; resolve from the reviewed stable-facet registry or require explicit input.",
                    from_normalized_mapping=["facet_set"],
                    depends_on=["stable_facet_registry"],
                )
        elif (
            task_name == "surface_cluster_builder"
            and parameter_name == "cluster_bulk_file"
            and argument_values.get("cluster_from_mp")
        ):
            mark(
                parameter_name,
                value=None,
                status="needs_upstream_artifact",
                confidence="high",
                source_field="clusters",
                source_term=_first_nonempty(*(task_inputs.get("clusters") or [])),
                reason="The elemental bulk file will be downloaded from Materials Project at execution time.",
                from_task_inputs=["cluster_species"],
                depends_on=["materials_project.cluster_bulk_structure"],
            )
        elif parameter_name in {"input", "surface", "molecule", "cluster", "cluster_bulk_file"}:
            source_field = "surfaces"
            source_term = _first_nonempty(
                *(task_inputs.get("surfaces") or []),
                task_inputs.get("material"),
            )
            depends_on = ["slab_generation.surface_structure"]
            if parameter_name == "input":
                depends_on = ["slab_generation.surface_structure"]
            elif parameter_name == "surface":
                depends_on = ["slab_generation.surface_structure"]
            elif parameter_name == "molecule":
                source_field = "adsorbates"
                source_term = _first_nonempty(
                    *[
                        candidate.get("raw")
                        for candidate in task_inputs.get("adsorbate_species", [])
                    ],
                    *(task_inputs.get("adsorbates") or []),
                )
                depends_on = ["molecule_structure_file"]
            elif parameter_name in {"cluster", "cluster_bulk_file"}:
                source_field = "clusters"
                source_term = _first_nonempty(*(task_inputs.get("clusters") or []))
                depends_on = ["surface_cluster_builder.cluster_structure"]
            mark(
                parameter_name,
                value=None,
                status="needs_upstream_artifact",
                confidence="high",
                source_field=source_field,
                source_term=source_term,
                reason="This parameter requires a real structure file produced or selected downstream; the paper only provides semantic context.",
                from_task_inputs=["material", "surfaces", "facets"],
                from_normalized_mapping=["primary_material", "primary_surface_or_support", "facet_set"],
                depends_on=depends_on,
            )
        elif parameter_name in {"vacancy_counts", "coverage_counts", "adsorption_sites", "active_symbols"}:
            source_field = {
                "vacancy_counts": "defects",
                "coverage_counts": "coverage",
                "adsorption_sites": "adsorption_sites",
                "active_symbols": "active_sites",
            }[parameter_name]
            mark(
                parameter_name,
                value=None,
                status="needs_manual_decision",
                confidence="medium",
                source_field=source_field,
                source_term=_first_nonempty(*(task_inputs.get(source_field) or [])),
                reason="Paper evidence narrows the context but does not uniquely determine this numeric or execution-time selection.",
                from_task_inputs=["coverage", "adsorption_sites", "active_sites", "defects", "vacancy_models"],
            )
        elif (
            task_name == "surface_cluster_builder"
            and parameter_name == "cluster_structures"
            and argument_values.get("cluster_from_mp")
        ):
            mark(
                parameter_name,
                value=None,
                status="needs_upstream_artifact",
                confidence="high",
                source_field="clusters",
                source_term=_first_nonempty(*(task_inputs.get("clusters") or [])),
                reason="The fcc/hcp/bcc cluster family will be mapped from the selected Materials Project elemental bulk space group.",
                from_task_inputs=["cluster_species"],
                depends_on=["materials_project.cluster_bulk_structure"],
            )
        elif parameter_name in {"cluster_atoms", "cluster_layers", "cluster_radius"}:
            selected_size_modes = [
                name
                for name in ("cluster_atoms", "cluster_layers", "cluster_radius")
                if argument_values.get(name) is not None
            ]
            if selected_size_modes:
                mark(
                    parameter_name,
                    value=None,
                    status="alternative_not_selected",
                    confidence="high",
                    source_field="clusters",
                    source_term=_first_nonempty(*(task_inputs.get("clusters") or [])),
                    reason=f"The mutually exclusive size mode {selected_size_modes[0]} is already selected.",
                    from_task_inputs=["clusters"],
                )
            else:
                mark(
                    parameter_name,
                    value=None,
                    status="needs_manual_decision",
                    confidence="medium",
                    source_field="clusters",
                    source_term=_first_nonempty(*(task_inputs.get("clusters") or [])),
                    reason="Cluster size mode must be chosen explicitly before invoking the builder.",
                    from_task_inputs=["clusters"],
                )
        else:
            default_status = "optional_unset"
            if parameter_spec.get("required"):
                default_status = "unresolved_required"
            mark(
                parameter_name,
                value=None,
                status=default_status,
                confidence="low",
                reason="No safe paper-to-parameter mapping is available yet; leave for downstream filling.",
            )

    required_missing = [
        name
        for name, spec in parameters.items()
        if spec.get("required") and argument_values.get(name) is None
    ]
    auto_mapped = [name for name, meta in argument_sources.items() if meta["status"] == "auto"]

    return {
        "arguments": argument_values,
        "argument_sources": argument_sources,
        "parameter_bindings": {
            name: {
                "value": argument_values.get(name),
                **argument_sources[name],
            }
            for name in argument_sources
        },
        "auto_mapped_parameters": auto_mapped,
        "required_missing_parameters": required_missing,
    }


def _build_parameter_correspondence(
    executable_tasks: list[str],
    task_inputs: dict[str, dict[str, Any]],
    normalized_mapping: dict[str, Any],
) -> dict[str, Any]:
    links: list[dict[str, Any]] = []

    def add_link(
        relation: str,
        *,
        source_fields: list[str],
        target_parameters: list[str],
        status: str,
        reason: str,
        source_terms: list[str] | None = None,
        prerequisite: str | None = None,
    ) -> None:
        links.append(
            {
                "relation": relation,
                "source_fields": source_fields,
                "source_terms": source_terms or [],
                "target_parameters": target_parameters,
                "status": status,
                "prerequisite": prerequisite,
                "reason": reason,
            }
        )

    surface_targets = []
    if "vacancy_landscape" in executable_tasks:
        surface_targets.append("vacancy_landscape.input")
    if "adsorbate_landscape" in executable_tasks:
        surface_targets.append("adsorbate_landscape.surface")
    if "surface_cluster_builder" in executable_tasks:
        surface_targets.append("surface_cluster_builder.surface")
    if surface_targets:
        add_link(
            "shared_surface_structure",
            source_fields=["materials", "surfaces", "facets", "surface_facets.surface_index"],
            source_terms=[
                item
                for item in [
                    normalized_mapping.get("primary_material"),
                    normalized_mapping.get("primary_surface_or_support"),
                    ", ".join(normalized_mapping.get("facet_set") or []),
                ]
                if item
            ],
            target_parameters=surface_targets,
            status="needs_upstream_artifact",
            prerequisite="slab_generation or user-selected structure file",
            reason="The same resolved slab or surface structure should feed all downstream tasks that operate on a surface artifact.",
        )

    ads_inputs = task_inputs.get("adsorbate_landscape", {})
    adsorbate_species = ads_inputs.get("adsorbate_species", [])
    if adsorbate_species:
        add_link(
            "adsorbate_to_molecule_file",
            source_fields=["adsorbates", "intermediates"],
            source_terms=[item["raw"] for item in adsorbate_species],
            target_parameters=["adsorbate_landscape.molecule"],
            status="needs_upstream_artifact",
            prerequisite="molecule structure file selection or generation",
            reason="Paper adsorbate names identify molecule candidates, but the executable parameter is a structure-file path.",
        )

    if ads_inputs.get("coverage"):
        add_link(
            "coverage_depends_on_surface_and_molecule",
            source_fields=["coverage"],
            source_terms=ads_inputs["coverage"],
            target_parameters=["adsorbate_landscape.coverage_counts"],
            status="needs_manual_decision",
            prerequisite="resolved surface supercell and molecule count convention",
            reason="Coverage text constrains the adsorbate loading but must be converted after the surface cell and adsorbate are fixed.",
        )

    cluster_inputs = task_inputs.get("surface_cluster_builder", {})
    cluster_targets = [
        target
        for target in [
            "surface_cluster_builder.cluster_element",
            "surface_cluster_builder.cluster_atoms",
            "surface_cluster_builder.cluster_structures",
        ]
        if target.split(".")[-1] in {"cluster_element", "cluster_atoms", "cluster_structures"}
    ]
    if cluster_inputs.get("clusters"):
        add_link(
            "cluster_phrase_to_builder_parameters",
            source_fields=["clusters", "Cluster/Single Atom"],
            source_terms=cluster_inputs["clusters"],
            target_parameters=cluster_targets,
            status="auto_or_manual_by_parameter",
            prerequisite=None,
            reason="Cluster text can directly provide the element, sometimes the atom count, and sometimes the crystal structure keyword.",
        )

    surface_site_contexts = normalized_mapping.get("surface_site_contexts") or []
    if surface_site_contexts and "adsorbate_landscape" in executable_tasks:
        add_link(
            "active_site_to_adsorption_site_search",
            source_fields=["active_sites", "adsorption_sites", "surface_site_contexts"],
            source_terms=surface_site_contexts[0].get("active_site_terms", [])
            + surface_site_contexts[0].get("adsorption_site_terms", []),
            target_parameters=["adsorbate_landscape.site_symbols", "adsorbate_landscape.site_group_size"],
            status="auto_or_manual_by_parameter",
            prerequisite="resolved surface structure",
            reason="Active-site labels can seed element-based site detection, while geometry choices remain execution-time decisions.",
        )

    return {
        "shared_context": {
            "primary_material": normalized_mapping.get("primary_material"),
            "primary_surface_or_support": normalized_mapping.get("primary_surface_or_support"),
            "facet_set": normalized_mapping.get("facet_set", []),
            "loaded_species": normalized_mapping.get("loaded_species", []),
            "reaction_family": normalized_mapping.get("reaction_family", []),
        },
        "links": links,
    }


def build_ptomodel_payload(
    relations_jsonl: str,
    table_csv: str | None = None,
    summary_txt: str | None = None,
    time_csv: str | None = None,
) -> dict[str, Any]:
    parameter_schema_registry = _load_surface_modeling_parameter_schema()
    relation_rows = _load_relations(relations_jsonl)
    table_rows = _load_table(table_csv)
    table_index = _index_table_rows(table_rows)
    documents: list[dict[str, Any]] = []

    for idx, relation_row in enumerate(relation_rows, start=1):
        extraction = relation_row["extraction"]
        relation_id = _first_nonempty(relation_row.get("id")) or f"doc_{idx}"
        table_row = table_index.get(relation_id)
        if table_row is None and idx <= len(table_rows):
            table_row = table_rows[idx - 1]

        materials = _to_list(extraction.get("materials")) or _to_list((table_row or {}).get("Material"))
        supports = _to_list(extraction.get("surfaces")) or _to_list((table_row or {}).get("Surface/Support"))
        raw_facets = _to_list(extraction.get("facets")) or _to_list((table_row or {}).get("Facet"))
        material_context = _first_nonempty(*(materials + supports))
        normalized_surface_indices = [
            canonicalize_surface_index(item, material_context=material_context)
            for item in raw_facets
        ]
        normalized_facets = [
            str(surface_index["software_facet"]) if surface_index else _normalize_facet(raw, material_context)
            for raw, surface_index in zip(raw_facets, normalized_surface_indices)
        ]
        cluster_entries = _to_list(extraction.get("clusters")) or _to_list((table_row or {}).get("Cluster/Single Atom"))
        adsorption_sites = _to_list(extraction.get("adsorption_sites")) or _to_list((table_row or {}).get("Adsorption Site"))
        cluster_species = [
            {"raw": item, "normalized_species": species}
            for item in cluster_entries
            for species in [_normalize_species(item)]
            if species
        ]
        reaction_type = _pick_reaction_type(extraction, table_row)
        modeling_keywords = _to_list(extraction.get("modeling_keywords")) or _to_list((table_row or {}).get("Modeling Keywords"))
        material_classes = _infer_material_classes(
            materials
            + supports
            + cluster_entries
            + _to_list(extraction.get("single_atoms"))
            + _to_list(extraction.get("surface_terminations"))
            + _to_list(extraction.get("defects"))
        )
        recognized_material_names = normalize_material_terms(materials + supports + cluster_entries)
        material_element_set = list(
            dict.fromkeys(
                symbol
                for item in recognized_material_names
                for symbol in item.get("elements", [])
            )
        )
        tasks, task_selection = _infer_tasks(
            extraction,
            table_row,
            material_classes,
            modeling_keywords,
        )
        executable_tasks = [task for task in tasks if task in EXECUTABLE_TASKS]
        deferred_tasks = [task for task in tasks if task not in EXECUTABLE_TASKS]
        normalized_mapping = {
            "primary_material": _first_nonempty(*materials),
            "material_classes": material_classes,
            "recognized_material_names": recognized_material_names,
            "element_set": material_element_set,
            "primary_surface_or_support": _first_nonempty(*supports),
            "facet_set": normalized_facets,
            "loaded_species": [item["normalized_species"] for item in cluster_species],
            "surface_site_contexts": _build_surface_site_contexts(
                materials,
                supports,
                raw_facets,
                _to_list(extraction.get("active_sites")) or _to_list((table_row or {}).get("Active Site")),
                adsorption_sites,
                [surface_index for surface_index in normalized_surface_indices if surface_index],
            ),
            "reaction_family": (
                [_normalize_reaction(reaction_type)]
                if reaction_type
                else []
            ),
        }
        task_inputs = {
            task_name: _build_task_inputs(task_name, extraction, table_row)
            for task_name in executable_tasks
        }

        documents.append(
            {
                "id": relation_id,
                "title": relation_row.get("title"),
                "selected_information": {
                    "materials": materials,
                    "material_classes": material_classes,
                    "recognized_material_names": recognized_material_names,
                    "element_set": material_element_set,
                    "supports_or_surfaces": supports,
                    "surface_facets": [
                        {
                            "raw": raw,
                            "normalized": normalized,
                            "surface_index": surface_index,
                        }
                        for raw, normalized, surface_index in zip(
                            raw_facets,
                            normalized_facets,
                            normalized_surface_indices,
                        )
                    ],
                    "surface_terminations": _to_list(extraction.get("surface_terminations")) or _to_list((table_row or {}).get("Surface Termination")),
                    "loaded_nanoparticles_or_clusters": cluster_species,
                    "single_atom_species": [
                        {"raw": item, "normalized_species": species}
                        for item in (_to_list(extraction.get("single_atoms")) or _to_list((table_row or {}).get("Cluster/Single Atom")))
                        for species in [_normalize_species(item)]
                        if species
                    ],
                    "reaction_types": (
                        [{"raw": reaction_type, "normalized": _normalize_reaction(reaction_type)}]
                        if reaction_type
                        else []
                    ),
                    "adsorbates": _to_list(extraction.get("adsorbates")) or _to_list((table_row or {}).get("Adsorbate/Reactant")),
                    "adsorption_sites": adsorption_sites,
                    "coverage": _to_list(extraction.get("coverage")) or _to_list((table_row or {}).get("Coverage")),
                    "defects": _to_list(extraction.get("defects")) or _to_list((table_row or {}).get("Defect")),
                    "active_sites": _to_list(extraction.get("active_sites")) or _to_list((table_row or {}).get("Active Site")),
                    "surface_site_contexts": normalized_mapping["surface_site_contexts"],
                    "modeling_keywords": modeling_keywords,
                },
                "normalized_mapping": normalized_mapping,
                "recommended_modeling_tasks": tasks,
                "task_selection": task_selection,
                "executable_tasks": executable_tasks,
                "deferred_tasks": deferred_tasks,
                "task_inputs": task_inputs,
                "parameter_correspondence": _build_parameter_correspondence(
                    executable_tasks,
                    task_inputs,
                    normalized_mapping,
                ),
                "task_parameter_schema_refs": {
                    task_name: {
                        "schema_path": parameter_schema_registry["schema_path"],
                        "task_key": task_name,
                    }
                    for task_name in executable_tasks
                    if task_name in parameter_schema_registry["tasks"]
                },
                "task_argument_template": {
                    task_name: _build_argument_template(
                        task_name,
                        task_inputs.get(task_name, {}),
                        normalized_mapping,
                        parameter_schema_registry,
                    )
                    for task_name in executable_tasks
                    if task_name in parameter_schema_registry["tasks"]
                },
            }
        )

    summary_excerpt: list[str] = []
    if summary_txt and Path(summary_txt).exists():
        summary_excerpt = [
            line.strip()
            for line in Path(summary_txt).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ][:12]

    recommended_tasks: list[str] = []
    for doc in documents:
        for task in doc["recommended_modeling_tasks"]:
            if task not in recommended_tasks:
                recommended_tasks.append(task)

    return {
        "schema_version": "1.0",
        "sources": {
            "relations_jsonl": relations_jsonl,
            "table_csv": table_csv,
            "summary_txt": summary_txt,
            "time_csv": time_csv,
        },
        "surface_modeling_parameter_schema": parameter_schema_registry,
        "summary_excerpt": summary_excerpt,
        "documents": documents,
        "global_recommended_tasks": recommended_tasks,
        "global_executable_tasks": [task for task in recommended_tasks if task in EXECUTABLE_TASKS],
        "global_deferred_tasks": [task for task in recommended_tasks if task not in EXECUTABLE_TASKS],
    }


def generate_ptomodel_output(
    relations_jsonl: str,
    output_dir: str,
    stem: str,
    table_csv: str | None = None,
    summary_txt: str | None = None,
    time_csv: str | None = None,
) -> dict[str, str]:
    payload = build_ptomodel_payload(
        relations_jsonl=relations_jsonl,
        table_csv=table_csv,
        summary_txt=summary_txt,
        time_csv=time_csv,
    )
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / f"{stem}_ptomodel.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ptomodel_json": str(json_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Filter and normalize paperread surface outputs into Agent-ready ptomodel JSON."
    )
    parser.add_argument("--relations", required=True, help="Path to *_surface_relations.jsonl")
    parser.add_argument("--table", default=None, help="Path to *_table.csv")
    parser.add_argument("--summary", default=None, help="Path to *_summary.txt")
    parser.add_argument("--time", default=None, help="Path to *_time.csv")
    parser.add_argument(
        "--output-dir",
        default="paperread/surface/output",
        help="Directory for ptomodel outputs.",
    )
    parser.add_argument(
        "--stem",
        default=None,
        help="Output filename stem. Defaults to the relations filename stem without _surface_relations.",
    )
    args = parser.parse_args(argv)

    stem = args.stem or Path(args.relations).stem.removesuffix("_surface_relations")
    outputs = generate_ptomodel_output(
        relations_jsonl=args.relations,
        table_csv=args.table,
        summary_txt=args.summary,
        time_csv=args.time,
        output_dir=args.output_dir,
        stem=stem,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
