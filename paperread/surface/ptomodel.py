from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

try:
    from .surface_ontology import (
        EXECUTABLE_TASKS,
        GENERIC_REACTION_TYPES,
        MATERIAL_CLASS_RULES,
        REACTION_KEYWORDS,
        SUPPORTED_MODELING_TASKS,
    )
    from .surface_indices import canonicalize_surface_index, normalize_surface_facet_for_software
except ImportError:  # pragma: no cover - direct script execution
    from surface_ontology import (
        EXECUTABLE_TASKS,
        GENERIC_REACTION_TYPES,
        MATERIAL_CLASS_RULES,
        REACTION_KEYWORDS,
        SUPPORTED_MODELING_TASKS,
    )
    from surface_indices import canonicalize_surface_index, normalize_surface_facet_for_software

SURFACE_MODELING_PARAMETER_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents/Agent/skills/surface-modeling/schema/task_parameter_schema.json"
)

ELEMENT_NAME_TO_SYMBOL = {
    "platinum": "Pt",
    "nickel": "Ni",
    "tin": "Sn",
    "cobalt": "Co",
    "iron": "Fe",
    "copper": "Cu",
    "ruthenium": "Ru",
    "rhodium": "Rh",
    "iridium": "Ir",
    "gold": "Au",
    "silver": "Ag",
    "palladium": "Pd",
    "zinc": "Zn",
    "manganese": "Mn",
    "cerium": "Ce",
    "titanium": "Ti",
}


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


def _normalize_species(raw: str) -> str | None:
    text = raw.strip()
    if not text:
        return None
    match = re.search(r"\b([A-Z][a-z]?)(?:\d+)?\b", text)
    if match:
        return match.group(1)
    lowered = text.lower()
    for name, symbol in ELEMENT_NAME_TO_SYMBOL.items():
        if name in lowered:
            return symbol
    return None


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


def _infer_site_symbols(active_sites: list[str]) -> list[str]:
    symbols: list[str] = []
    for item in active_sites:
        symbol = _normalize_species(item)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


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
    joined = " ".join(values).lower()
    matches = [name for name, rules in MATERIAL_CLASS_RULES if any(rule in joined for rule in rules)]
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


def _infer_tasks(extraction: dict[str, Any], table_row: dict[str, str] | None) -> list[str]:
    tasks = []
    recommended = [
        task
        for task in _flatten_strings(extraction.get("recommended_modeling_tasks"))
        if task in SUPPORTED_MODELING_TASKS
    ]
    tasks.extend(recommended)

    defects = " ".join(
        _flatten_strings(extraction.get("defects"))
        + _flatten_strings(extraction.get("vacancy_models"))
        + _flatten_strings((table_row or {}).get("Defect"))
    ).lower()
    if "vacan" in defects and "vacancy_landscape" not in tasks:
        tasks.append("vacancy_landscape")

    adsorption = (
        _flatten_strings(extraction.get("adsorbates"))
        + _flatten_strings(extraction.get("adsorption_sites"))
        + _flatten_strings(extraction.get("coverage"))
        + _flatten_strings((table_row or {}).get("Adsorbate/Reactant"))
        + _flatten_strings((table_row or {}).get("Adsorption Site"))
        + _flatten_strings((table_row or {}).get("Coverage"))
    )
    if adsorption and "adsorbate_landscape" not in tasks:
        tasks.append("adsorbate_landscape")

    clusters = (
        _flatten_strings(extraction.get("clusters"))
        + _flatten_strings((table_row or {}).get("Cluster/Single Atom"))
    )
    cluster_text = " ".join(clusters).lower()
    if any(word in cluster_text for word in {"cluster", "nanocluster", "nanoparticle"}) and "surface_cluster_builder" not in tasks:
        tasks.append("surface_cluster_builder")

    singles = (
        _flatten_strings(extraction.get("single_atoms"))
        + _flatten_strings((table_row or {}).get("Cluster/Single Atom"))
        + _flatten_strings((table_row or {}).get("Active Site"))
    )
    single_text = " ".join(singles).lower()
    if "single atom" in single_text and "single_atom_site" not in tasks:
        tasks.append("single_atom_site")

    dopants = _flatten_strings(extraction.get("dopants")) + _flatten_strings((table_row or {}).get("Dopant/Modifier"))
    if dopants and "doped_surface" not in tasks:
        tasks.append("doped_surface")

    terminations = _flatten_strings(extraction.get("surface_terminations")) + _flatten_strings((table_row or {}).get("Surface Termination"))
    if terminations and "surface_functionalization" not in tasks:
        tasks.append("surface_functionalization")

    surfaces = (
        _flatten_strings(extraction.get("surfaces"))
        + _flatten_strings(extraction.get("slab_models"))
        + _flatten_strings(extraction.get("facets"))
        + _flatten_strings((table_row or {}).get("Surface/Support"))
        + _flatten_strings((table_row or {}).get("Facet"))
    )
    if surfaces and "slab_generation" not in tasks:
        tasks.append("slab_generation")

    return tasks


def _load_surface_modeling_parameter_schema() -> dict[str, Any]:
    if not SURFACE_MODELING_PARAMETER_SCHEMA_PATH.exists():
        return {
            "schema_path": str(SURFACE_MODELING_PARAMETER_SCHEMA_PATH),
            "schema_version": None,
            "tasks": {},
        }
    payload = json.loads(SURFACE_MODELING_PARAMETER_SCHEMA_PATH.read_text(encoding="utf-8"))
    return {
        "schema_path": str(SURFACE_MODELING_PARAMETER_SCHEMA_PATH),
        "schema_version": payload.get("schema_version"),
        "tasks": payload.get("tasks", {}),
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
    elif task_name == "adsorbate_landscape":
        payload["adsorbates"] = _to_list(extraction.get("adsorbates")) or _to_list((table_row or {}).get("Adsorbate/Reactant"))
        payload["adsorption_sites"] = _to_list(extraction.get("adsorption_sites")) or _to_list((table_row or {}).get("Adsorption Site"))
        payload["coverage"] = _to_list(extraction.get("coverage")) or _to_list((table_row or {}).get("Coverage"))
    elif task_name == "surface_cluster_builder":
        payload["clusters"] = _to_list(extraction.get("clusters")) or _to_list((table_row or {}).get("Cluster/Single Atom"))
        payload["cluster_species"] = [
            species
            for species in (_normalize_species(item) for item in payload["clusters"])
            if species
        ]
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
        from_task_inputs: list[str] | None = None,
        from_normalized_mapping: list[str] | None = None,
    ) -> None:
        argument_values[parameter_name] = value
        argument_sources[parameter_name] = {
            "status": status,
            "reason": reason,
            "from_task_inputs": from_task_inputs or [],
            "from_normalized_mapping": from_normalized_mapping or [],
        }

    if "task_name" in parameters:
        mark(
            "task_name",
            value=task_name,
            status="auto",
            reason="Executable task name is already selected by ptomodel.",
        )

    if task_name == "adsorbate_landscape":
        site_symbols = _infer_site_symbols(task_inputs.get("active_sites", []))
        if site_symbols:
            mark(
                "site_symbols",
                value=",".join(site_symbols),
                status="auto",
                reason="Active-site labels mention concrete element symbols that can seed adsorption-site detection.",
                from_task_inputs=["active_sites"],
            )
    elif task_name == "surface_cluster_builder":
        cluster_species = task_inputs.get("cluster_species", [])
        if cluster_species:
            mark(
                "cluster_element",
                value=cluster_species[0],
                status="auto",
                reason="Cluster species normalized from paper cluster mentions.",
                from_task_inputs=["cluster_species"],
            )
        cluster_structures = _infer_cluster_structures(task_inputs.get("clusters", []))
        if cluster_structures:
            mark(
                "cluster_structures",
                value=cluster_structures,
                status="auto",
                reason="Cluster text explicitly mentions crystal-structure keywords.",
                from_task_inputs=["clusters"],
            )

    for parameter_name, parameter_spec in parameters.items():
        if parameter_name in argument_sources:
            continue

        if parameter_name in {"input", "surface", "molecule", "cluster", "cluster_bulk_file"}:
            mark(
                parameter_name,
                value=None,
                status="needs_upstream_artifact",
                reason="This parameter requires a real structure file produced or selected downstream; the paper only provides semantic context.",
                from_task_inputs=["material", "surfaces", "facets"],
                from_normalized_mapping=["primary_material", "primary_surface_or_support", "facet_set"],
            )
        elif parameter_name in {"vacancy_counts", "coverage_counts", "adsorption_sites", "active_symbols"}:
            mark(
                parameter_name,
                value=None,
                status="needs_manual_decision",
                reason="Paper evidence narrows the context but does not uniquely determine this numeric or execution-time selection.",
                from_task_inputs=["coverage", "adsorption_sites", "active_sites", "defects", "vacancy_models"],
            )
        elif parameter_name in {"cluster_atoms", "cluster_layers", "cluster_radius"}:
            mark(
                parameter_name,
                value=None,
                status="needs_manual_decision",
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
        "auto_mapped_parameters": auto_mapped,
        "required_missing_parameters": required_missing,
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
        tasks = _infer_tasks(extraction, table_row)
        executable_tasks = [task for task in tasks if task in EXECUTABLE_TASKS]
        deferred_tasks = [task for task in tasks if task not in EXECUTABLE_TASKS]
        modeling_keywords = _to_list(extraction.get("modeling_keywords")) or _to_list((table_row or {}).get("Modeling Keywords"))
        material_classes = _infer_material_classes(
            materials
            + supports
            + cluster_entries
            + _to_list(extraction.get("single_atoms"))
            + _to_list(extraction.get("surface_terminations"))
            + _to_list(extraction.get("defects"))
        )
        normalized_mapping = {
            "primary_material": _first_nonempty(*materials),
            "material_classes": material_classes,
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
                "executable_tasks": executable_tasks,
                "deferred_tasks": deferred_tasks,
                "task_inputs": task_inputs,
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
