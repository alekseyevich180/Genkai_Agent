from __future__ import annotations

import re
from typing import Any


HEXAGONAL_STRUCTURE_HINTS = {
    "ru": {
        "crystal_system": "hexagonal",
        "structure": "hcp Ru",
        "space_group": "P6_3/mmc (No. 194)",
    },
    "zno": {
        "crystal_system": "hexagonal",
        "structure": "wurtzite ZnO",
        "space_group": "P6_3mc (No. 186)",
        "surface_note": "Common nonpolar ZnO (10-10) is software Miller (100) for three-index slab builders.",
    },
    "beta-coooh": {
        "crystal_system": "hexagonal/trigonal",
        "structure": "layered beta-CoOOH",
        "space_group": "structure-dependent; confirm against the CIF before slab generation",
    },
    "β-coooh": {
        "crystal_system": "hexagonal/trigonal",
        "structure": "layered beta-CoOOH",
        "space_group": "structure-dependent; confirm against the CIF before slab generation",
    },
    "coooh": {
        "crystal_system": "hexagonal/trigonal",
        "structure": "layered CoOOH",
        "space_group": "structure-dependent; confirm against the CIF before slab generation",
    },
}

COMMON_MALFORMED_HEX_FACETS = {
    ("β-coooh", (0, 1, 1, -2)): (0, 1, -1, 2),
    ("beta-coooh", (0, 1, 1, -2)): (0, 1, -1, 2),
    ("coooh", (0, 1, 1, -2)): (0, 1, -1, 2),
}


def _plain_material_key(material: str | None) -> str:
    if not material:
        return ""
    key = material.casefold().replace("β", "beta")
    key = re.sub(r"[^a-z0-9]+", "-", key).strip("-")
    if "beta-coooh" in key:
        return "beta-coooh"
    if "coooh" in key:
        return "coooh"
    if re.search(r"(^|-)zno($|-)", key):
        return "zno"
    if re.search(r"(^|-)ru($|-)", key):
        return "ru"
    return key


def _structure_hint(material: str | None) -> dict[str, str]:
    raw_key = material.casefold().strip() if material else ""
    plain_key = _plain_material_key(material)
    return HEXAGONAL_STRUCTURE_HINTS.get(raw_key) or HEXAGONAL_STRUCTURE_HINTS.get(plain_key, {})


def normalize_overbar_digits(text: str) -> str:
    normalized = text.replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = re.sub(r"(\d)[\u0304\u0305]", r"-\1", normalized)
    normalized = normalized.replace("¯", "-")
    return normalized


def extract_surface_material_and_facet(term: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"(?P<material>[A-Za-zα-ωΑ-ΩβΒ][A-Za-z0-9α-ωΑ-ΩβΒδΔ+\-–−_/]*)?\s*(?P<facet>\([0-9+\-−–—¯\u0304\u0305\s,]+\))",
        term,
    )
    if not match:
        match = re.search(
            r"(?P<material>[A-Za-zα-ωΑ-ΩβΒ][A-Za-z0-9α-ωΑ-ΩβΒδΔ+\-–−_/]*)?\s*\((?P<open_facet>[0-9+\-−–—¯\u0304\u0305\s,]+)$",
            term.strip(),
        )
        if match:
            material = (match.group("material") or "").strip() or None
            return material, f"({match.group('open_facet')})"
    if not match:
        return None, None
    material = (match.group("material") or "").strip() or None
    return material, match.group("facet")


def parse_miller_indices(facet: str) -> list[int] | None:
    inner = normalize_overbar_digits(facet).strip().strip("()[]{}")
    if not inner:
        return None
    if re.search(r"[\s,]", inner):
        tokens = re.findall(r"[+-]?\d+", inner)
    else:
        tokens = re.findall(r"[+-]?\d", inner)
    if len(tokens) not in {3, 4}:
        return None
    return [int(token) for token in tokens]


def _format_miller(indices: list[int] | tuple[int, ...]) -> str:
    if all(-9 <= index <= 9 for index in indices):
        return "(" + "".join(str(index) for index in indices) + ")"
    return "(" + " ".join(str(index) for index in indices) + ")"


def _hex_miller_bravais_to_software(
    material_key: str,
    indices: tuple[int, int, int, int],
) -> tuple[tuple[int, int, int], tuple[int, int, int, int], list[str]]:
    warnings: list[str] = []
    h, k, i, l = indices
    corrected = indices
    if h + k + i != 0:
        replacement = COMMON_MALFORMED_HEX_FACETS.get((material_key, indices))
        if replacement:
            corrected = replacement
            h, k, i, l = corrected
            warnings.append(
                "Corrected malformed hexagonal hkil notation; expected i=-(h+k)."
            )
        else:
            warnings.append("Hexagonal hkil notation is inconsistent because h+k+i != 0.")
    return (h, k, l), corrected, warnings


def canonicalize_surface_index(
    raw: str,
    material_context: str | None = None,
) -> dict[str, Any] | None:
    material_from_term, facet = extract_surface_material_and_facet(raw)
    if facet is None and raw.strip().startswith("("):
        facet = raw.strip()
    if facet is None:
        return None

    material = material_from_term or material_context
    indices = parse_miller_indices(facet)
    if not indices:
        return None

    hint = _structure_hint(material)
    material_key = _plain_material_key(material)
    notation = "miller"
    software_indices = tuple(indices)
    canonical_input_indices = tuple(indices)
    warnings: list[str] = []

    if len(indices) == 4:
        notation = "miller_bravais_hkil"
        software_indices, canonical_input_indices, warnings = _hex_miller_bravais_to_software(
            material_key,
            tuple(indices),  # type: ignore[arg-type]
        )

    return {
        "raw": raw,
        "material": material,
        "raw_facet": facet,
        "input_notation": notation,
        "input_indices": list(indices),
        "canonical_input_indices": list(canonical_input_indices),
        "software_miller_index": list(software_indices),
        "software_facet": _format_miller(software_indices),
        "crystal_system": hint.get("crystal_system"),
        "structure": hint.get("structure"),
        "space_group": hint.get("space_group"),
        "surface_note": hint.get("surface_note"),
        "warnings": warnings,
    }


def normalize_surface_facet_for_software(raw: str, material_context: str | None = None) -> str:
    normalized = canonicalize_surface_index(raw, material_context)
    if normalized:
        return str(normalized["software_facet"])
    text = raw.strip()
    inner = re.sub(r"[\s,]+", "", text.strip("()[]{}"))
    if re.fullmatch(r"-?\d{3,4}", inner):
        return f"({inner})"
    return text


def is_surface_index_term(term: str) -> bool:
    return canonicalize_surface_index(term) is not None
