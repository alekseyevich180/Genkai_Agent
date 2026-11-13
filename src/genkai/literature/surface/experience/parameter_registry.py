from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.crystal_structures import match_crystal_structure_term


def _find_project_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "agents" / "Agent").is_dir():
            return parent
    return Path.cwd()


REPO_ROOT = _find_project_root()
DEFAULT_MATERIAL_CLASS_DIR = Path(__file__).resolve().parent / "material_classes"
DEFAULT_REGISTRY_PATH = (
    REPO_ROOT
    / "agents/Agent/skills/paperread/experience/surface_parameter_registry.json"
)
DEFAULT_REGISTRY_MARKDOWN_PATH = (
    REPO_ROOT
    / "agents/Agent/skills/paperread/experience/surface_parameter_registry.md"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top_terms(items: list[dict[str, Any]], limit: int = 12) -> list[str]:
    return [
        str(item.get("term", "")).strip()
        for item in items[:limit]
        if str(item.get("term", "")).strip()
    ]


def _top_surface_index_mappings(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    mappings = []
    for item in items[:limit]:
        term = str(item.get("term", "")).strip()
        software_facet = str(item.get("software_facet", "")).strip()
        if not term or not software_facet:
            continue
        mappings.append(
            {
                "term": term,
                "software_facet": software_facet,
                "software_miller_index": item.get("software_miller_index", []),
                "input_notation": item.get("input_notation"),
                "crystal_system": item.get("crystal_system"),
                "space_group": item.get("space_group"),
                "warnings": item.get("warnings", []),
            }
        )
    return mappings


def _top_crystal_structure_terms(items: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    structures = []
    for item in items[:limit]:
        term = str(item.get("term", "")).strip()
        if not term:
            continue
        vocabulary_match = match_crystal_structure_term(term) or {}
        structures.append(
            {
                "term": term,
                "family": item.get("family"),
                "crystal_system": item.get("crystal_system"),
                "typical_space_group": item.get("typical_space_group"),
                "representative_compositions": item.get(
                    "representative_compositions", vocabulary_match.get("representative_compositions", [])
                ),
            }
        )
    return structures


def _top_surface_site_contexts(items: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    contexts = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        contexts.append(
            {
                "surface_terms": item.get("surface_terms", [])[:4],
                "facet_terms": item.get("facet_terms", [])[:4],
                "active_site_terms": item.get("active_site_terms", [])[:4],
                "adsorption_site_terms": item.get("adsorption_site_terms", [])[:4],
                "site_role_terms": item.get("site_role_terms", [])[:4],
                "relation": item.get("relation"),
            }
        )
    return contexts


def _fallback_surface_site_contexts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    surface_terms = list(profile.get("top_surface_terms", [])[:4])
    facet_terms = [
        item["term"]
        for item in profile.get("top_surface_index_mappings", [])[:4]
        if item.get("term")
    ]
    active_site_terms = list(profile.get("top_active_site_terms", [])[:4])
    adsorption_site_terms = list(profile.get("top_active_site_terms", [])[:4])
    if not (surface_terms or facet_terms or active_site_terms or adsorption_site_terms):
        return []
    return [
        {
            "surface_terms": surface_terms,
            "facet_terms": facet_terms,
            "active_site_terms": active_site_terms,
            "adsorption_site_terms": adsorption_site_terms,
            "site_role_terms": [],
            "relation": "surface-site association (derived from legacy profile)",
        }
    ]


def _load_material_class_payloads(material_class_dir: Path) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    if not material_class_dir.exists():
        return payloads
    for path in sorted(material_class_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        payloads[path.stem] = payload
    return payloads


def build_surface_parameter_registry(
    material_class_dir: Path | None = None,
    output_json_path: Path | None = None,
    output_markdown_path: Path | None = None,
) -> dict[str, Any]:
    material_class_dir = material_class_dir or DEFAULT_MATERIAL_CLASS_DIR
    output_json_path = output_json_path or DEFAULT_REGISTRY_PATH
    output_markdown_path = output_markdown_path or DEFAULT_REGISTRY_MARKDOWN_PATH

    payloads = _load_material_class_payloads(material_class_dir)
    if not payloads:
        raise FileNotFoundError(
            f"material-class JSON assets not found: {material_class_dir}"
        )
    class_profiles: dict[str, Any] = {}

    common_material_classes = sorted(payloads)
    common_reactions: list[str] = []
    common_elements: list[str] = []
    common_support_terms: list[str] = []
    common_coordination_terms: list[str] = []
    common_loading_terms: list[str] = []
    common_crystal_structure_terms: list[str] = []
    common_surface_site_relations: list[str] = []

    def extend_unique(target: list[str], values: list[str], limit: int = 20) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)
            if len(target) >= limit:
                break

    for material_class, payload in payloads.items():
        profile = payload.get("class_profile", {})
        descriptors = payload.get("material_descriptors", {})
        inventory = payload.get("keyword_inventory", {})
        surface_site_contexts = profile.get("surface_site_contexts") or _fallback_surface_site_contexts(
            {
                "top_surface_terms": _top_terms(inventory.get("supports_surfaces", []), limit=10),
                "top_surface_index_mappings": profile.get("surface_index_mappings", []),
                "top_active_site_terms": _top_terms(inventory.get("active_sites", []), limit=10),
            }
        )
        class_profiles[material_class] = {
            "descriptor_schema": profile.get("descriptor_schema", "generic_material_profile"),
            "top_elements": _top_terms(descriptors.get("elements", []), limit=10),
            "top_element_sets": _top_terms(descriptors.get("element_sets", []), limit=10),
            "top_material_terms": _top_terms(inventory.get("materials", []), limit=10),
            "top_oxide_compositions": _top_terms(
                profile.get("oxide_compositions", inventory.get("oxide_compositions", [])),
                limit=10,
            ),
            "top_surface_terms": _top_terms(inventory.get("supports_surfaces", []), limit=10),
            "top_surface_index_mappings": _top_surface_index_mappings(profile.get("surface_index_mappings", []), limit=10),
            "top_crystal_structure_terms": _top_crystal_structure_terms(profile.get("crystal_structure_terms", []), limit=10),
            "top_state_terms": _top_terms(inventory.get("surface_states", []), limit=10),
            "top_reported_surface_stability_descriptors": _top_terms(
                profile.get(
                    "reported_surface_stability_descriptors",
                    inventory.get("surface_stability_descriptors", []),
                ),
                limit=10,
            ),
            "top_dopant_terms": _top_terms(inventory.get("dopants_modifiers", []), limit=10),
            "top_active_site_terms": _top_terms(inventory.get("active_sites", []), limit=10),
            "top_surface_site_contexts": _top_surface_site_contexts(surface_site_contexts, limit=6),
            "top_reaction_terms": _top_terms(profile.get("reaction_families", []), limit=10),
            "top_loading_terms": _top_terms(descriptors.get("approx_loadings", []), limit=10),
            "profile": profile,
        }

        extend_unique(common_reactions, _top_terms(profile.get("reaction_families", []), limit=10))
        extend_unique(common_elements, _top_terms(descriptors.get("elements", []), limit=10))
        extend_unique(common_support_terms, _top_terms(profile.get("support_components", []), limit=10))
        extend_unique(common_coordination_terms, _top_terms(profile.get("coordination_environments", []), limit=10))
        extend_unique(common_loading_terms, _top_terms(descriptors.get("approx_loadings", []), limit=10))
        extend_unique(common_crystal_structure_terms, _top_terms(profile.get("crystal_structure_terms", []), limit=10))
        extend_unique(
            common_surface_site_relations,
            [
                f"{', '.join(item.get('surface_terms', [])[:2])} | {', '.join(item.get('facet_terms', [])[:2])} | {', '.join(item.get('active_site_terms', [])[:2])}"
                for item in surface_site_contexts
                if isinstance(item, dict)
            ],
        )

    registry = {
        "schema_version": "1.0",
        "generated_at": _now(),
        "source_material_class_dir": str(material_class_dir),
        "common": {
            "material_classes": common_material_classes,
            "reaction_keywords": common_reactions,
            "element_keywords": common_elements,
            "support_keywords": common_support_terms,
            "coordination_keywords": common_coordination_terms,
            "loading_keywords": common_loading_terms,
            "crystal_structure_keywords": common_crystal_structure_terms,
            "surface_site_keywords": common_surface_site_relations,
        },
        "class_profiles": class_profiles,
    }

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Surface Parameter Registry",
        "",
        f"- Material classes: {', '.join(common_material_classes)}",
        f"- Reaction keywords: {', '.join(common_reactions[:12]) or 'N/A'}",
        f"- Element keywords: {', '.join(common_elements[:12]) or 'N/A'}",
        f"- Support keywords: {', '.join(common_support_terms[:12]) or 'N/A'}",
        f"- Coordination keywords: {', '.join(common_coordination_terms[:12]) or 'N/A'}",
        f"- Loading keywords: {', '.join(common_loading_terms[:12]) or 'N/A'}",
        f"- Crystal structure keywords: {', '.join(common_crystal_structure_terms[:12]) or 'N/A'}",
        f"- Surface-site associations: {', '.join(common_surface_site_relations[:12]) or 'N/A'}",
        "",
    ]
    for material_class, profile in sorted(class_profiles.items()):
        lines.extend(
            [
                f"## {material_class}",
                "",
                f"- Schema: `{profile['descriptor_schema']}`",
                f"- Top elements: {', '.join(profile['top_elements']) or 'N/A'}",
                f"- Top materials: {', '.join(profile['top_material_terms']) or 'N/A'}",
                *(
                    [f"- Oxide compositions: {', '.join(profile['top_oxide_compositions'])}"]
                    if profile["top_oxide_compositions"]
                    else []
                ),
                f"- Top surfaces: {', '.join(profile['top_surface_terms']) or 'N/A'}",
                "- Crystal structures: "
                + (
                    ", ".join(
                        f"{item['term']} ({item.get('crystal_system') or 'structure-dependent'}"
                        + (
                            f"; compositions: {', '.join(item['representative_compositions'])}"
                            if item.get("representative_compositions")
                            else ""
                        )
                        + ")"
                        for item in profile["top_crystal_structure_terms"]
                    )
                    or "N/A"
                ),
                "- Surface index mappings: "
                + (
                    ", ".join(
                        f"{item['term']} -> {item['software_facet']}"
                        for item in profile["top_surface_index_mappings"]
                    )
                    or "N/A"
                ),
                f"- Top states: {', '.join(profile['top_state_terms']) or 'N/A'}",
                *(
                    [
                        "- Reported surface-stability terms: "
                        + ", ".join(profile["top_reported_surface_stability_descriptors"])
                    ]
                    if profile["top_reported_surface_stability_descriptors"]
                    else []
                ),
                f"- Top dopants: {', '.join(profile['top_dopant_terms']) or 'N/A'}",
                f"- Top active sites: {', '.join(profile['top_active_site_terms']) or 'N/A'}",
                "- Surface-site associations: "
                + (
                    "; ".join(
                        f"surface={', '.join(item.get('surface_terms', [])[:2]) or 'N/A'}"
                        f" | facet={', '.join(item.get('facet_terms', [])[:2]) or 'N/A'}"
                        f" | active={', '.join(item.get('active_site_terms', [])[:2]) or 'N/A'}"
                        f" | adsorption={', '.join(item.get('adsorption_site_terms', [])[:2]) or 'N/A'}"
                        for item in profile.get("top_surface_site_contexts", [])
                    )
                    or "N/A"
                ),
                f"- Top reactions: {', '.join(profile['top_reaction_terms']) or 'N/A'}",
                f"- Top loadings: {', '.join(profile['top_loading_terms']) or 'N/A'}",
                "",
            ]
        )
    output_markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return registry


def load_surface_parameter_registry(registry_path: Path | None = None) -> dict[str, Any]:
    path = registry_path or DEFAULT_REGISTRY_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def render_registry_prompt_hint(registry: dict[str, Any], limit: int = 8) -> str:
    if not registry:
        return ""

    common = registry.get("common", {})
    class_profiles = registry.get("class_profiles", {})
    lines = ["Known reusable surface-parameter vocabulary from prior papers:"]

    material_classes = common.get("material_classes", [])
    if material_classes:
        lines.append(f"- Material classes: {', '.join(material_classes[:limit])}")
    if common.get("reaction_keywords"):
        lines.append(f"- Common reaction keywords: {', '.join(common['reaction_keywords'][:limit])}")
    if common.get("element_keywords"):
        lines.append(f"- Common elements: {', '.join(common['element_keywords'][:limit])}")
    if common.get("loading_keywords"):
        lines.append(f"- Common loading expressions: {', '.join(common['loading_keywords'][:limit])}")
    if common.get("crystal_structure_keywords"):
        lines.append(f"- Common crystal/mineral structure keywords: {', '.join(common['crystal_structure_keywords'][:limit])}")
    if common.get("surface_site_keywords"):
        lines.append(f"- Common surface-site associations: {', '.join(common['surface_site_keywords'][:limit])}")

    for material_class in (
        "supported_catalysts",
        "carbon_materials",
        "single_atom_catalysts",
        "metals_alloys",
        "oxides",
        "perovskites_spinels",
    ):
        profile = class_profiles.get(material_class)
        if not profile:
            continue
        hints = []
        if profile.get("top_material_terms"):
            hints.append(f"materials {', '.join(profile['top_material_terms'][:4])}")
        if profile.get("top_surface_terms"):
            hints.append(f"surfaces {', '.join(profile['top_surface_terms'][:4])}")
        if profile.get("top_oxide_compositions"):
            hints.append(f"reported oxide compositions {', '.join(profile['top_oxide_compositions'][:4])}")
        if profile.get("top_crystal_structure_terms"):
            structures = [
                f"{item['term']} ({item.get('crystal_system') or 'structure-dependent'}"
                + (
                    f"; compositions: {', '.join(item['representative_compositions'])}"
                    if item.get("representative_compositions")
                    else ""
                )
                + ")"
                for item in profile["top_crystal_structure_terms"][:4]
            ]
            hints.append(f"crystal structures {', '.join(structures)}")
        if profile.get("top_surface_index_mappings"):
            mappings = [
                f"{item['term']} -> {item['software_facet']}"
                for item in profile["top_surface_index_mappings"][:4]
            ]
            hints.append(f"facet mappings {', '.join(mappings)}")
        if profile.get("top_reported_surface_stability_descriptors"):
            hints.append(
                "reported stability terms "
                + ", ".join(profile["top_reported_surface_stability_descriptors"][:4])
            )
        if profile.get("top_dopant_terms"):
            hints.append(f"dopants {', '.join(profile['top_dopant_terms'][:4])}")
        if profile.get("top_active_site_terms"):
            hints.append(f"active sites {', '.join(profile['top_active_site_terms'][:4])}")
        if profile.get("top_surface_site_contexts"):
            context_terms = [
                f"{', '.join(item.get('surface_terms', [])[:2])} -> {', '.join(item.get('active_site_terms', [])[:2]) or ', '.join(item.get('adsorption_site_terms', [])[:2])}"
                for item in profile["top_surface_site_contexts"][:4]
            ]
            hints.append(f"site associations {', '.join(context_terms)}")
        if profile.get("top_reaction_terms"):
            hints.append(f"reactions {', '.join(profile['top_reaction_terms'][:4])}")
        if hints:
            lines.append(f"- {material_class}: {'; '.join(hints)}")

    return "\n".join(lines)
