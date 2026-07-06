from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATERIAL_CLASS_DIR = REPO_ROOT / "paperread" / "surface" / "experience" / "material_classes"
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
    class_profiles: dict[str, Any] = {}

    common_material_classes = sorted(payloads)
    common_reactions: list[str] = []
    common_elements: list[str] = []
    common_support_terms: list[str] = []
    common_coordination_terms: list[str] = []
    common_loading_terms: list[str] = []

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
        class_profiles[material_class] = {
            "descriptor_schema": profile.get("descriptor_schema", "generic_material_profile"),
            "top_elements": _top_terms(descriptors.get("elements", []), limit=10),
            "top_element_sets": _top_terms(descriptors.get("element_sets", []), limit=10),
            "top_material_terms": _top_terms(inventory.get("materials", []), limit=10),
            "top_surface_terms": _top_terms(inventory.get("supports_surfaces", []), limit=10),
            "top_state_terms": _top_terms(inventory.get("surface_states", []), limit=10),
            "top_dopant_terms": _top_terms(inventory.get("dopants_modifiers", []), limit=10),
            "top_active_site_terms": _top_terms(inventory.get("active_sites", []), limit=10),
            "top_reaction_terms": _top_terms(profile.get("reaction_families", []), limit=10),
            "top_loading_terms": _top_terms(descriptors.get("approx_loadings", []), limit=10),
            "profile": profile,
        }

        extend_unique(common_reactions, _top_terms(profile.get("reaction_families", []), limit=10))
        extend_unique(common_elements, _top_terms(descriptors.get("elements", []), limit=10))
        extend_unique(common_support_terms, _top_terms(profile.get("support_components", []), limit=10))
        extend_unique(common_coordination_terms, _top_terms(profile.get("coordination_environments", []), limit=10))
        extend_unique(common_loading_terms, _top_terms(descriptors.get("approx_loadings", []), limit=10))

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
                f"- Top surfaces: {', '.join(profile['top_surface_terms']) or 'N/A'}",
                f"- Top states: {', '.join(profile['top_state_terms']) or 'N/A'}",
                f"- Top dopants: {', '.join(profile['top_dopant_terms']) or 'N/A'}",
                f"- Top active sites: {', '.join(profile['top_active_site_terms']) or 'N/A'}",
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
        if profile.get("top_dopant_terms"):
            hints.append(f"dopants {', '.join(profile['top_dopant_terms'][:4])}")
        if profile.get("top_active_site_terms"):
            hints.append(f"active sites {', '.join(profile['top_active_site_terms'][:4])}")
        if profile.get("top_reaction_terms"):
            hints.append(f"reactions {', '.join(profile['top_reaction_terms'][:4])}")
        if hints:
            lines.append(f"- {material_class}: {'; '.join(hints)}")

    return "\n".join(lines)
