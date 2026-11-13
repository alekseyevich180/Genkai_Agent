from __future__ import annotations

import re
from typing import Any


CRYSTAL_STRUCTURE_TERMS: dict[str, dict[str, Any]] = {
    "anatase": {
        "family": "TiO2 polymorph",
        "crystal_system": "tetragonal",
        "typical_space_group": "I4_1/amd (No. 141)",
        "notes": "Common TiO2 polymorph; often paired with (101) or (001) facets.",
    },
    "brookite": {
        "family": "TiO2 polymorph",
        "crystal_system": "orthorhombic",
        "typical_space_group": "Pbca (No. 61)",
    },
    "rutile": {
        "family": "oxide polymorph",
        "crystal_system": "tetragonal",
        "typical_space_group": "P4_2/mnm (No. 136)",
        "representative_compositions": ["TiO2", "SnO2", "RuO2", "IrO2", "MnO2"],
        "notes": "Common TiO2, RuO2, MnO2, and SnO2 structure type; often paired with (110).",
    },
    "spinel": {
        "family": "AB2O4 structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fd-3m (No. 227)",
        "notes": "Includes normal and inverse spinels such as Co3O4, Fe3O4, and related oxides.",
    },
    "normal spinel": {
        "family": "AB2O4 structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fd-3m (No. 227)",
    },
    "inverse spinel": {
        "family": "AB2O4 structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fd-3m (No. 227)",
    },
    "perovskite": {
        "family": "ABO3 structure type",
        "crystal_system": "structure-dependent",
        "typical_space_group": "varies with distortion and composition",
    },
    "fluorite": {
        "family": "AO2 structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fm-3m (No. 225)",
        "notes": "Common CeO2 and ZrO2-related structure type.",
    },
    "wurtzite": {
        "family": "AB hexagonal structure type",
        "crystal_system": "hexagonal",
        "typical_space_group": "P6_3mc (No. 186)",
        "notes": "Common ZnO structure type; four-index facets require hkil handling.",
    },
    "rocksalt": {
        "family": "AB structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fm-3m (No. 225)",
    },
    "rock salt": {
        "family": "AB structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fm-3m (No. 225)",
    },
    "pyrochlore": {
        "family": "A2B2O7 structure type",
        "crystal_system": "cubic",
        "typical_space_group": "Fd-3m (No. 227)",
    },
    "delafossite": {
        "family": "ABO2 layered structure type",
        "crystal_system": "trigonal/rhombohedral",
        "typical_space_group": "R-3m (No. 166)",
    },
    "brucite": {
        "family": "layered hydroxide structure type",
        "crystal_system": "trigonal",
        "typical_space_group": "P-3m1 (No. 164)",
    },
    "corundum": {
        "family": "A2O3 structure type",
        "crystal_system": "trigonal/rhombohedral",
        "typical_space_group": "R-3c (No. 167)",
    },
}


def normalize_crystal_structure_term(term: str) -> str:
    normalized = term.casefold().replace("–", "-").replace("—", "-")
    normalized = re.sub(r"[^a-z0-9+\-\s]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def match_crystal_structure_term(term: str) -> dict[str, Any] | None:
    normalized = normalize_crystal_structure_term(term)
    if not normalized:
        return None
    for name in sorted(CRYSTAL_STRUCTURE_TERMS, key=len, reverse=True):
        pattern = rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])"
        if re.search(pattern, normalized):
            info = dict(CRYSTAL_STRUCTURE_TERMS[name])
            info["term"] = name
            return info
    return None


def is_crystal_structure_term(term: str) -> bool:
    return match_crystal_structure_term(term) is not None


def render_crystal_structure_vocabulary(limit: int | None = None) -> str:
    names = sorted(CRYSTAL_STRUCTURE_TERMS)
    if limit is not None:
        names = names[:limit]
    return ", ".join(names)
