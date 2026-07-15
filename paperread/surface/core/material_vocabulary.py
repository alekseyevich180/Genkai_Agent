from __future__ import annotations

import re
from typing import Any


MATERIAL_VOCABULARY: dict[str, dict[str, Any]] = {
    "0.4 wt % sAu": {"category": "composition_loading", "normalized": "0.4 wt% single-atom Au"},
    "Ag/g-C3N4": {"category": "supported_catalyst", "normalized": "Ag supported on graphitic carbon nitride"},
    "Ba0.5Sr0.5Co0.8Fe0.2O3-d": {"category": "perovskite_oxide", "normalized": "BSCF oxygen-deficient perovskite oxide"},
    "Ba0.5Sr0.5Co0.8Fe0.2O3–d": {"category": "perovskite_oxide", "normalized": "BSCF oxygen-deficient perovskite oxide"},
    "black phosphorus": {"category": "two_dimensional_material", "normalized": "black phosphorus"},
    "Black Phosphorus Nanosheets": {"category": "two_dimensional_material", "normalized": "black phosphorus nanosheets"},
    "antimonene": {"category": "two_dimensional_material", "normalized": "antimonene"},
    "Bulk Ir": {"category": "bulk_metal", "normalized": "bulk Ir"},
    "Bulk Pt": {"category": "bulk_metal", "normalized": "bulk Pt"},
    "Bulk Ru": {"category": "bulk_metal", "normalized": "bulk Ru"},
    "carbon cloth": {"category": "carbon_support", "normalized": "carbon cloth"},
    "CdN0C4-gra": {"category": "single_atom_graphene_model", "normalized": "CdN0C4 graphene model"},
    "CdN4C0-gra": {"category": "single_atom_graphene_model", "normalized": "CdN4C0 graphene model"},
    "Co nanochains": {"category": "nanostructure", "normalized": "Co nanochains"},
    "Co oxides": {"category": "oxide_material", "normalized": "cobalt oxides"},
    "CoO nanocubes": {"category": "nanostructure", "normalized": "CoO nanocubes"},
    "Ag nanospheres": {"category": "nanostructure", "normalized": "Ag nanospheres"},
    "Co2+ (d7, high spin)": {"category": "site_descriptor", "normalized": "Co2+ (d7, high spin)"},
    "Co3+ (d6, low spin)": {"category": "site_descriptor", "normalized": "Co3+ (d6, low spin)"},
    "CoIII-containing species": {"category": "site_descriptor", "normalized": "CoIII-containing species"},
    "CoOct (+4)": {"category": "site_descriptor", "normalized": "CoOct (+4)"},
    "Co–Fe–Cr (oxy)Hydroxides": {"category": "oxyhydroxide_material", "normalized": "Co-Fe-Cr oxyhydroxides"},
    "Cu-based": {"category": "composition_descriptor", "normalized": "Cu-based"},
    "Cu-based nanostructures": {"category": "nanostructure", "normalized": "Cu-based nanostructures"},
    "Cyanide-modified": {"category": "surface_modifier", "normalized": "cyanide-modified"},
    "Fe-free": {"category": "composition_descriptor", "normalized": "Fe-free"},
    "Fe)OOH": {"category": "oxyhydroxide_material", "normalized": "FeOOH"},
    "g-C3N4": {"category": "carbon_nitride", "normalized": "graphitic carbon nitride"},
    "Graphene": {"category": "carbon_material", "normalized": "graphene"},
    "Graphene (G)": {"category": "carbon_material", "normalized": "graphene"},
    "graphene-like carbon": {"category": "carbon_material", "normalized": "graphene-like carbon"},
    "graphene plane": {"category": "carbon_material", "normalized": "graphene plane"},
    "Heterostructure": {"category": "structure_descriptor", "normalized": "heterostructure"},
    "hydroxides": {"category": "material_family", "normalized": "hydroxides"},
    "1 M KOH": {"category": "electrolyte", "normalized": "1 M KOH electrolyte"},
    "1 M NaOH": {"category": "electrolyte", "normalized": "1 M NaOH electrolyte"},
    "interfacial interactions": {"category": "interaction_descriptor", "normalized": "interfacial interactions"},
    "Lattice-Strain": {"category": "structure_descriptor", "normalized": "lattice strain"},
    "nanoporous": {"category": "nanostructure", "normalized": "nanoporous"},
    "phase evolution": {"category": "structure_descriptor", "normalized": "phase evolution"},
    "layered phase": {"category": "structure_descriptor", "normalized": "layered phase"},
    "layered double hydroxide (LDH)": {"category": "layered_double_hydroxide", "normalized": "layered double hydroxide"},
    "layered double hydroxides": {"category": "layered_double_hydroxide", "normalized": "layered double hydroxides"},
    "planar deposition": {"category": "process_descriptor", "normalized": "planar deposition"},
    "Mo-Ni3S2/NixPy/NF electrode": {"category": "composite_electrode", "normalized": "Mo-Ni3S2/NixPy on nickel foam"},
    "bimetallic alloy": {"category": "alloy_material", "normalized": "bimetallic alloy"},
    "Ni(Fe)": {"category": "composition_descriptor", "normalized": "Ni(Fe)"},
    "Ni1-xFexOOH": {"category": "oxyhydroxide_material", "normalized": "Ni1-xFexOOH"},
    "Ni1−xFexOOH": {"category": "oxyhydroxide_material", "normalized": "Ni1-xFexOOH"},
    "Nickel–Bismuth Oxide": {"category": "oxide_material", "normalized": "nickel-bismuth oxide"},
    "NiCo Layer Double Hydroxide": {"category": "layered_double_hydroxide", "normalized": "NiCo layered double hydroxide"},
    "NiCo LDH/CC": {"category": "supported_catalyst", "normalized": "NiCo LDH on carbon cloth"},
    "NiFe layered double hydroxide": {"category": "layered_double_hydroxide", "normalized": "NiFe layered double hydroxide"},
    "NiFe LDH": {"category": "layered_double_hydroxide", "normalized": "NiFe layered double hydroxide"},
    "NiFe oxyhydroxide": {"category": "oxyhydroxide_material", "normalized": "NiFe oxyhydroxide"},
    "NixPy": {"category": "metal_phosphide", "normalized": "nickel phosphide NixPy"},
    "Noble metal": {"category": "material_family", "normalized": "noble metal"},
    "non-precious metal catalysts": {"category": "material_family", "normalized": "non-precious metal catalysts"},
    "oxide catalysts": {"category": "material_family", "normalized": "oxide catalysts"},
    "oxygen-contained intermediates": {"category": "adsorbate_intermediate", "normalized": "oxygen-contained intermediates"},
    "oxygen species": {"category": "adsorbate_intermediate", "normalized": "oxygen species"},
    "Polyaniline fibers": {"category": "conducting_polymer", "normalized": "polyaniline fibers"},
    "hollow nanorods": {"category": "nanostructure", "normalized": "hollow nanorods"},
    "mixed (Ni,Fe)oxyhydroxides": {"category": "oxyhydroxide_material", "normalized": "mixed (Ni,Fe)oxyhydroxides"},
    "Fe atoms in NiFe oxyhydroxide": {"category": "site_descriptor", "normalized": "Fe atoms in NiFe oxyhydroxide"},
    "ultrathin graphene sheets": {"category": "carbon_material", "normalized": "ultrathin graphene sheets"},
    "sAu": {"category": "single_atom_catalyst", "normalized": "single-atom Au"},
    "single-atom Au": {"category": "single_atom_catalyst", "normalized": "single-atom Au"},
    "single-atom catalyst": {"category": "single_atom_catalyst", "normalized": "single-atom catalyst"},
    "single-atom catalysts": {"category": "single_atom_catalyst", "normalized": "single-atom catalysts"},
    "Pt bimetallic": {"category": "alloy_material", "normalized": "Pt bimetallic"},
    "Pt-Bi Alloy": {"category": "alloy_material", "normalized": "Pt-Bi alloy"},
    "PtBi alloy": {"category": "alloy_material", "normalized": "PtBi alloy"},
    "PtTiMe ternary alloys": {"category": "alloy_material", "normalized": "PtTiMe ternary alloys"},
    "Ru modified": {"category": "surface_modifier", "normalized": "Ru-modified"},
    "sAu/NiFe LDH": {"category": "single_atom_catalyst", "normalized": "single-atom Au on NiFe LDH"},
    "Sn SAs/G-Na": {"category": "single_atom_catalyst", "normalized": "Sn single atoms on Na-modified graphene"},
    "sodium metal batteries": {"category": "battery_system", "normalized": "sodium metal batteries"},
    "sub-saturation": {"category": "process_descriptor", "normalized": "sub-saturation"},
    "transition metal-based catalysts": {"category": "material_family", "normalized": "transition-metal-based catalysts"},
    "transition metal": {"category": "material_family", "normalized": "transition metal"},
    "tri-metallic": {"category": "composition_descriptor", "normalized": "trimetallic"},
    "TM@Sb (TM = Sc": {"category": "single_atom_catalyst", "normalized": "TM@Sb single-atom antimonene model"},
    "ultrananocrystalline diamond": {"category": "carbon_material", "normalized": "ultrananocrystalline diamond"},
    "bulk material": {"category": "bulk_descriptor", "normalized": "bulk material"},
    "bulk phase": {"category": "bulk_descriptor", "normalized": "bulk phase"},
    "bimetallic": {"category": "alloy_material", "normalized": "bimetallic"},
    "bimetallic catalysts": {"category": "alloy_material", "normalized": "bimetallic catalysts"},
    "phosphides": {"category": "material_family", "normalized": "phosphides"},
    "catalyst development": {"category": "process_descriptor", "normalized": "catalyst development"},
    "dendrite": {"category": "morphology", "normalized": "dendrite"},
    "dendrite-free": {"category": "morphology", "normalized": "dendrite-free"},
    "hydroxyl species": {"category": "adsorbate_intermediate", "normalized": "hydroxyl species"},
    "ammonia": {"category": "molecule", "normalized": "ammonia"},
    "selenides": {"category": "material_family", "normalized": "selenides"},
    "tellurides": {"category": "material_family", "normalized": "tellurides"},
    "Zn-Air": {"category": "battery_system", "normalized": "Zn-Air"},
    "Zn-Air Batteries": {"category": "battery_system", "normalized": "Zn-Air batteries"},
    "single nickel atoms": {"category": "single_atom_catalyst", "normalized": "single nickel atoms"},
    "five-coordinated Cr5c": {"category": "site_descriptor", "normalized": "five-coordinated Cr5c"},
    "three-coordinated Cr3c": {"category": "site_descriptor", "normalized": "three-coordinated Cr3c"},
    "monochain CrO3": {"category": "structure_descriptor", "normalized": "monochain CrO3"},
    "OER intermediates": {"category": "adsorbate_intermediate", "normalized": "OER intermediates"},
    "Nernst equation": {"category": "electrochemical_descriptor", "normalized": "Nernst equation"},
    "tensile strain": {"category": "structure_descriptor", "normalized": "tensile strain"},
    "oxygen evolution": {"category": "reaction_or_application", "normalized": "oxygen evolution"},
    "ΔG*H": {"category": "adsorbate_intermediate", "normalized": "ΔG*H"},
    "octahedral Co and O ions (B-layer)": {"category": "site_descriptor", "normalized": "octahedral Co and O ions (B-layer)"},
    "carbon doping": {"category": "composition_descriptor", "normalized": "carbon doping"},
    "High OH or mixed OH/O": {"category": "adsorbate_intermediate", "normalized": "High OH or mixed OH/O"},
    "octahedral Co": {"category": "site_descriptor", "normalized": "octahedral Co"},
    "B-layer (octahedral Co and O ions)": {"category": "site_descriptor", "normalized": "B-layer (octahedral Co and O ions)"},
    "ionosorbed oxygen species": {"category": "adsorbate_intermediate", "normalized": "ionosorbed oxygen species"},
    "gas sensor": {"category": "device_application", "normalized": "gas sensor"},
    "molecular orbital": {"category": "electronic_structure", "normalized": "molecular orbital"},
    "free energy landscape": {"category": "thermodynamic_descriptor", "normalized": "free energy landscape"},
    "trifunctional": {"category": "functional_descriptor", "normalized": "trifunctional"},
    "catalyst": {"category": "material_family", "normalized": "catalyst"},
    "catalysts": {"category": "material_family", "normalized": "catalysts"},
    "oxide": {"category": "material_family", "normalized": "oxide"},
    "composition": {"category": "composition_descriptor", "normalized": "composition"},
    "structure": {"category": "structure_descriptor", "normalized": "structure"},
    "binding": {"category": "interaction_descriptor", "normalized": "binding"},
    "electrochemical processes": {"category": "process_descriptor", "normalized": "electrochemical processes"},
    "Shape-dependent electrocatalysis": {"category": "reaction_or_application", "normalized": "shape-dependent electrocatalysis"},
    "Catalytic Oxidation": {"category": "reaction_or_application", "normalized": "catalytic oxidation"},
    "(photo)electrocatalysts": {"category": "material_family", "normalized": "(photo)electrocatalysts"},
    "electrocatalytic oxygen evolution": {"category": "reaction_or_application", "normalized": "electrocatalytic oxygen evolution"},
    "NO oxidation": {"category": "reaction_or_application", "normalized": "NO oxidation"},
    "space group Fd3̅m": {"category": "space_group", "normalized": "space group Fd-3m"},
    "β-CoOOH": {"category": "oxyhydroxide_material", "normalized": "beta-CoOOH"},
}

ADSORBATE_INTERMEDIATE_PATTERNS = [
    re.compile(r"^\*?(?:H|O|O2|OH|OOH|HO|HOO|H2O|H2O2|NO2|ONOO)\*?$", re.IGNORECASE),
    re.compile(r"^\*$"),
    re.compile(r"^(?:H|OH)ads$", re.IGNORECASE),
    re.compile(r"^Habs$", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9]+OOH\*$", re.IGNORECASE),
    re.compile(r"^overpotential\s*\(.*ηOER.*ηORR.*\)$", re.IGNORECASE),
    re.compile(r"^overpotential\s*\(ηOER\s*=\s*\d+(?:\.\d+)?\s*V$", re.IGNORECASE),
    re.compile(r"^ηORR\s*=\s*\d+(?:\.\d+)?\s*V\)$", re.IGNORECASE),
]

DESCRIPTOR_PATTERNS = [
    re.compile(r"^(?:mono|bi)-$", re.IGNORECASE),
    re.compile(r"^Co3\+δ$", re.IGNORECASE),
    re.compile(r"^CO32[−-]$", re.IGNORECASE),
    re.compile(r"^Cr[35]c$", re.IGNORECASE),
    re.compile(r"^Bi0[25]:NiO$", re.IGNORECASE),
    re.compile(r"^space group\s+[A-Za-z0-9_/\-\u0305]+(?:\s*\(No\.\s*\d+\))?$", re.IGNORECASE),
]


def _normalize_key(term: str) -> str:
    return term.strip().replace("−", "-").replace("–", "-").replace("—", "-")


def match_material_vocabulary_term(term: str) -> dict[str, Any] | None:
    stripped = term.strip()
    if not stripped:
        return None
    normalized = _normalize_key(stripped)
    for key, info in MATERIAL_VOCABULARY.items():
        if _normalize_key(key).casefold() == normalized.casefold():
            payload = dict(info)
            payload["term"] = key
            return payload
    for pattern in ADSORBATE_INTERMEDIATE_PATTERNS:
        if pattern.fullmatch(normalized):
            return {
                "term": stripped,
                "category": "adsorbate_intermediate",
                "normalized": stripped,
            }
    for pattern in DESCRIPTOR_PATTERNS:
        if pattern.fullmatch(normalized):
            return {
                "term": stripped,
                "category": "composition_descriptor",
                "normalized": stripped,
            }
    return None


def is_material_vocabulary_term(term: str) -> bool:
    return match_material_vocabulary_term(term) is not None


def research_category_for_material_vocabulary(term: str) -> str:
    match = match_material_vocabulary_term(term)
    if not match:
        return "other_useful_information"
    category = str(match.get("category", ""))
    if category in {"adsorbate_intermediate", "electrolyte"}:
        return "adsorption_reaction"
    if category in {"single_atom_catalyst", "single_atom_graphene_model", "nanostructure"}:
        return "clusters_single_atoms"
    if category in {"composition_loading", "composition_descriptor", "surface_modifier", "structure_descriptor"}:
        return "surface_structure"
    return "surface_materials"
