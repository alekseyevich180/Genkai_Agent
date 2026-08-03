from __future__ import annotations

import re
from typing import Any


# IUPAC element order through radon (Z=86). Aliases cover spelling variants and
# legacy/common names that still occur in papers and materials databases.
_ELEMENT_ROWS = [
    ("H", "hydrogen", "protium", "deuterium", "tritium"),
    ("He", "helium"),
    ("Li", "lithium"),
    ("Be", "beryllium"),
    ("B", "boron"),
    ("C", "carbon"),
    ("N", "nitrogen"),
    ("O", "oxygen"),
    ("F", "fluorine"),
    ("Ne", "neon"),
    ("Na", "sodium", "natrium"),
    ("Mg", "magnesium"),
    ("Al", "aluminium", "aluminum"),
    ("Si", "silicon"),
    ("P", "phosphorus"),
    ("S", "sulfur", "sulphur"),
    ("Cl", "chlorine"),
    ("Ar", "argon"),
    ("K", "potassium", "kalium"),
    ("Ca", "calcium"),
    ("Sc", "scandium"),
    ("Ti", "titanium"),
    ("V", "vanadium"),
    ("Cr", "chromium", "chrome"),
    ("Mn", "manganese"),
    ("Fe", "iron", "ferrum"),
    ("Co", "cobalt"),
    ("Ni", "nickel"),
    ("Cu", "copper", "cuprum"),
    ("Zn", "zinc"),
    ("Ga", "gallium"),
    ("Ge", "germanium"),
    ("As", "arsenic"),
    ("Se", "selenium"),
    ("Br", "bromine"),
    ("Kr", "krypton"),
    ("Rb", "rubidium"),
    ("Sr", "strontium"),
    ("Y", "yttrium"),
    ("Zr", "zirconium"),
    ("Nb", "niobium", "columbium"),
    ("Mo", "molybdenum"),
    ("Tc", "technetium"),
    ("Ru", "ruthenium"),
    ("Rh", "rhodium"),
    ("Pd", "palladium"),
    ("Ag", "silver", "argentum"),
    ("Cd", "cadmium"),
    ("In", "indium"),
    ("Sn", "tin", "stannum"),
    ("Sb", "antimony", "stibium"),
    ("Te", "tellurium"),
    ("I", "iodine"),
    ("Xe", "xenon"),
    ("Cs", "cesium", "caesium"),
    ("Ba", "barium"),
    ("La", "lanthanum"),
    ("Ce", "cerium"),
    ("Pr", "praseodymium"),
    ("Nd", "neodymium"),
    ("Pm", "promethium"),
    ("Sm", "samarium"),
    ("Eu", "europium"),
    ("Gd", "gadolinium"),
    ("Tb", "terbium"),
    ("Dy", "dysprosium"),
    ("Ho", "holmium"),
    ("Er", "erbium"),
    ("Tm", "thulium"),
    ("Yb", "ytterbium"),
    ("Lu", "lutetium"),
    ("Hf", "hafnium"),
    ("Ta", "tantalum"),
    ("W", "tungsten", "wolfram"),
    ("Re", "rhenium"),
    ("Os", "osmium"),
    ("Ir", "iridium"),
    ("Pt", "platinum"),
    ("Au", "gold", "aurum"),
    ("Hg", "mercury", "quicksilver", "hydrargyrum"),
    ("Tl", "thallium"),
    ("Pb", "lead", "plumbum"),
    ("Bi", "bismuth"),
    ("Po", "polonium"),
    ("At", "astatine"),
    ("Rn", "radon"),
]

ELEMENTS: tuple[dict[str, Any], ...] = tuple(
    {
        "atomic_number": atomic_number,
        "symbol": row[0],
        "name": row[1],
        "aliases": list(row[1:]),
    }
    for atomic_number, row in enumerate(_ELEMENT_ROWS, start=1)
)
ELEMENT_BY_SYMBOL = {item["symbol"]: item for item in ELEMENTS}
ELEMENT_ALIAS_TO_SYMBOL = {
    alias.casefold(): item["symbol"]
    for item in ELEMENTS
    for alias in [item["symbol"], *item["aliases"]]
}
ELEMENT_NAME_ALIAS_TO_SYMBOL = {
    alias.casefold(): item["symbol"]
    for item in ELEMENTS
    for alias in item["aliases"]
}

# Elemental allotropes and common material labels used as material names rather
# than element names in papers.
ELEMENTAL_MATERIAL_ALIASES = {
    "graphite": "C",
    "graphene": "C",
    "diamond": "C",
    "carbon black": "C",
    "black phosphorus": "P",
    "red phosphorus": "P",
    "white phosphorus": "P",
    "antimonene": "Sb",
    "silicene": "Si",
    "germanene": "Ge",
    "stanene": "Sn",
}

# Curated mineral names and common compound names frequently used without a
# formula in materials papers. Generic structure-type words are omitted where a
# unique composition cannot be assigned.
MATERIAL_NAME_ALIASES: dict[str, dict[str, Any]] = {
    "alumina": {"formula": "Al2O3", "kind": "common_name"},
    "corundum": {"formula": "Al2O3", "kind": "mineral"},
    "silica": {"formula": "SiO2", "kind": "common_name"},
    "quartz": {"formula": "SiO2", "kind": "mineral"},
    "cristobalite": {"formula": "SiO2", "kind": "mineral"},
    "tridymite": {"formula": "SiO2", "kind": "mineral"},
    "ceria": {"formula": "CeO2", "kind": "common_name"},
    "zirconia": {"formula": "ZrO2", "kind": "common_name"},
    "titania": {"formula": "TiO2", "kind": "common_name"},
    "anatase": {"formula": "TiO2", "kind": "mineral"},
    "brookite": {"formula": "TiO2", "kind": "mineral"},
    "hematite": {"formula": "Fe2O3", "kind": "mineral"},
    "magnetite": {"formula": "Fe3O4", "kind": "mineral"},
    "wustite": {"formula": "FeO", "kind": "mineral"},
    "wuestite": {"formula": "FeO", "kind": "mineral"},
    "goethite": {"formula": "FeOOH", "kind": "mineral"},
    "lepidocrocite": {"formula": "FeOOH", "kind": "mineral"},
    "chromia": {"formula": "Cr2O3", "kind": "common_name"},
    "eskolaite": {"formula": "Cr2O3", "kind": "mineral"},
    "zincite": {"formula": "ZnO", "kind": "mineral"},
    "cuprite": {"formula": "Cu2O", "kind": "mineral"},
    "tenorite": {"formula": "CuO", "kind": "mineral"},
    "cassiterite": {"formula": "SnO2", "kind": "mineral"},
    "pyrolusite": {"formula": "MnO2", "kind": "mineral"},
    "hausmannite": {"formula": "Mn3O4", "kind": "mineral"},
    "hausmannitene": {"formula": "Mn3O4", "kind": "common_name"},
    "bunsenite": {"formula": "NiO", "kind": "mineral"},
    "periclase": {"formula": "MgO", "kind": "mineral"},
    "lime": {"formula": "CaO", "kind": "common_name"},
    "brucite": {"formula": "Mg(OH)2", "kind": "mineral"},
    "gibbsite": {"formula": "Al(OH)3", "kind": "mineral"},
    "boehmite": {"formula": "AlOOH", "kind": "mineral"},
    "diaspore": {"formula": "AlOOH", "kind": "mineral"},
    "molybdenite": {"formula": "MoS2", "kind": "mineral"},
    "tungstenite": {"formula": "WS2", "kind": "mineral"},
    "pyrite": {"formula": "FeS2", "kind": "mineral"},
    "marcasite": {"formula": "FeS2", "kind": "mineral"},
    "galena": {"formula": "PbS", "kind": "mineral"},
    "sphalerite": {"formula": "ZnS", "kind": "mineral"},
    "chalcopyrite": {"formula": "CuFeS2", "kind": "mineral"},
    "pentlandite": {"formula": "(Fe,Ni)9S8", "kind": "mineral"},
    "millerite": {"formula": "NiS", "kind": "mineral"},
    "covellite": {"formula": "CuS", "kind": "mineral"},
    "chalcocite": {"formula": "Cu2S", "kind": "mineral"},
    "bornite": {"formula": "Cu5FeS4", "kind": "mineral"},
    "cinnabar": {"formula": "HgS", "kind": "mineral"},
    "stibnite": {"formula": "Sb2S3", "kind": "mineral"},
    "realgar": {"formula": "As4S4", "kind": "mineral"},
    "orpiment": {"formula": "As2S3", "kind": "mineral"},
    "halite": {"formula": "NaCl", "kind": "mineral"},
    "sylvite": {"formula": "KCl", "kind": "mineral"},
    "fluorite": {"formula": "CaF2", "kind": "mineral"},
    "cryolite": {"formula": "Na3AlF6", "kind": "mineral"},
    "calcite": {"formula": "CaCO3", "kind": "mineral"},
    "aragonite": {"formula": "CaCO3", "kind": "mineral"},
    "vaterite": {"formula": "CaCO3", "kind": "mineral"},
    "dolomite": {"formula": "CaMg(CO3)2", "kind": "mineral"},
    "magnesite": {"formula": "MgCO3", "kind": "mineral"},
    "siderite": {"formula": "FeCO3", "kind": "mineral"},
    "smithsonite": {"formula": "ZnCO3", "kind": "mineral"},
    "rhodochrosite": {"formula": "MnCO3", "kind": "mineral"},
    "barite": {"formula": "BaSO4", "kind": "mineral"},
    "baryte": {"formula": "BaSO4", "kind": "mineral"},
    "gypsum": {"formula": "CaSO4.2H2O", "kind": "mineral"},
    "anhydrite": {"formula": "CaSO4", "kind": "mineral"},
    "celestite": {"formula": "SrSO4", "kind": "mineral"},
    "scheelite": {"formula": "CaWO4", "kind": "mineral"},
    "wolframite": {"formula": "(Fe,Mn)WO4", "kind": "mineral"},
    "ilmenite": {"formula": "FeTiO3", "kind": "mineral"},
    "zircon": {"formula": "ZrSiO4", "kind": "mineral"},
    "hydroxyapatite": {"formula": "Ca5(PO4)3OH", "kind": "mineral"},
    "kaolinite": {"formula": "Al2Si2O5(OH)4", "kind": "mineral"},
}

METAL_SYMBOLS = {
    "Li", "Be", "Na", "Mg", "Al", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Cs", "Ba",
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta",
    "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po",
}


def normalize_element_name(term: str) -> str | None:
    return ELEMENT_ALIAS_TO_SYMBOL.get(term.strip().casefold())


def _symbols_from_formula(formula: str) -> list[str]:
    symbols: list[str] = []
    for symbol in re.findall(r"[A-Z][a-z]?", formula):
        if symbol in ELEMENT_BY_SYMBOL and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def recognize_material_name(term: str) -> list[dict[str, Any]]:
    lowered = term.casefold()
    matches: list[dict[str, Any]] = []
    for alias, info in sorted(MATERIAL_NAME_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if not re.search(rf"(?<![a-z]){re.escape(alias.casefold())}(?![a-z])", lowered):
            continue
        formula = info["formula"]
        matches.append(
            {
                "raw": term,
                "matched_name": alias,
                "normalized_formula": formula,
                "kind": info["kind"],
                "elements": _symbols_from_formula(formula),
            }
        )
    return matches


def extract_element_symbols(term: str, *, include_material_aliases: bool = True) -> list[str]:
    symbols: list[str] = []

    def add(symbol: str) -> None:
        if symbol not in symbols:
            symbols.append(symbol)

    lowered = term.casefold()
    for alias, symbol in sorted(ELEMENT_NAME_ALIAS_TO_SYMBOL.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered):
            add(symbol)
    formula_tokens = re.findall(r"(?<![A-Za-z])(?:[A-Z][a-z]?\d*)+(?![a-z])", term)
    for formula_token in formula_tokens:
        for symbol in _symbols_from_formula(formula_token):
            add(symbol)
    for symbol in ELEMENT_BY_SYMBOL:
        if re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![a-z])", term):
            add(symbol)
    for alias, symbol in ELEMENTAL_MATERIAL_ALIASES.items():
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered):
            add(symbol)
    if include_material_aliases:
        for match in recognize_material_name(term):
            for symbol in match["elements"]:
                add(symbol)
    return symbols


def normalize_material_terms(terms: list[str]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for term in terms:
        alias_matches = recognize_material_name(term)
        if alias_matches:
            normalized.extend(alias_matches)
            continue
        symbols = extract_element_symbols(term, include_material_aliases=False)
        normalized.append(
            {
                "raw": term,
                "matched_name": None,
                "normalized_formula": term,
                "kind": "formula_or_element" if symbols else "unresolved_name",
                "elements": symbols,
            }
        )
    return normalized
