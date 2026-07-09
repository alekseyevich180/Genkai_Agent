from __future__ import annotations

import re

try:
    from .crystal_structures import is_crystal_structure_term
except ImportError:  # pragma: no cover - direct script execution fallback
    from crystal_structures import is_crystal_structure_term

SUPPORTED_MODELING_TASKS = {
    "vacancy_landscape",
    "adsorbate_landscape",
    "surface_cluster_builder",
    "single_atom_site",
    "doped_surface",
    "surface_functionalization",
    "slab_generation",
}

EXECUTABLE_TASKS = {
    "vacancy_landscape",
    "adsorbate_landscape",
    "surface_cluster_builder",
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
    "terrace",
    "step",
    "stepped surface",
    "kink",
    "edge",
    "basal plane",
    "crystal plane",
    "miller index",
    "exposed facet",
    "exposed surface",
    "clean surface",
    "surface atom",
    "surface atoms",
    "surface cation",
    "surface oxygen",
    "subsurface",
    "surface area",
    "specific surface area",
    "roughness",
    "reconstruction",
    "surface reconstruction",
    "surface stability",
    "surface defect",
    "surface defects",
    "dft",
    "density functional theory",
    "first-principles",
    "first principles",
    "ab initio",
    "dos",
    "pdos",
    "density of states",
    "bader",
    "bader charge",
    "xas",
    "xafs",
    "exafs",
    "xps",
    "xrd",
    "sem",
    "tem",
    "raman",
    "ftir",
    "cv",
    "lsv",
    "eis",
    "reaction mechanism",
    "reaction mechanisms",
    "electronic structure",
    "computational method",
    "computational methods",
    "hubbard u",
    "hubbard-u approach",
    "hubbard-u correction",
    "dispersion interaction",
    "dispersion interactions",
    "charge redistribution",
    "charge transfer",
    "activation energy",
    "kinetic characterization",
}

KNOWN_MODELING_TOKENS = {
    "surface",
    "slab",
    "support",
    "interface",
    "facet",
    "termination",
    "terminated",
    "adsorbate",
    "adsorption",
    "coverage",
    "site",
    "vacancy",
    "defect",
    "dopant",
    "doped",
    "modifier",
    "promoter",
    "cluster",
    "nanocluster",
    "nanoparticle",
    "single atom",
    "isolated",
    "oxygen vacancy",
    "anion vacancy",
    "cation vacancy",
    "hydroxylated",
    "sulfurized",
    "nitrided",
    "reduced",
    "oxidized",
    "reconstructed",
    "top site",
    "bridge site",
    "hollow site",
    "monodentate",
    "bidentate",
    "coadsorption",
    "monolayer",
    "metal-support",
    "anchoring",
    "terrace",
    "step",
    "kink",
    "edge",
    "basal plane",
    "crystal plane",
    "miller index",
    "exposed facet",
    "exposed surface",
    "clean surface",
    "surface atom",
    "surface atoms",
    "surface cation",
    "surface oxygen",
    "subsurface",
    "surface area",
    "specific surface area",
    "roughness",
    "reconstruction",
    "surface reconstruction",
    "surface stability",
    "surface defect",
    "surface defects",
}

RELATION_FIELDS = [
    "applications",
    "materials",
    "material_parameters",
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
    "Reaction Type",
    "Material",
    "Composition",
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
    "Loading",
    "Product",
    "Modeling Keywords",
]

HIGH_VALUE_FIELDS = {
    "material_parameters",
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
    "Composition",
    "Surface/Support",
    "Facet",
    "Defect",
    "Adsorbate/Reactant",
    "Adsorption Site",
    "Coverage",
    "Cluster/Single Atom",
    "Loading",
    "Modeling Keywords",
}

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
        "applications",
        "Reaction Type",
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

KEYWORD_BUCKET_RULES = {
    "materials": {"materials", "Material"},
    "compositions": {"material_parameters", "Composition", "Loading"},
    "supports_surfaces": {"surfaces", "Surface/Support", "slab_models"},
    "facets": {"facets", "Facet"},
    "surface_states": {
        "surface_terminations",
        "Surface Termination",
        "defects",
        "vacancy_models",
        "Defect",
    },
    "dopants_modifiers": {"dopants", "Dopant/Modifier", "modifiers"},
    "active_sites": {"active_sites", "Active Site"},
    "adsorbates_reactants": {"adsorbates", "Adsorbate/Reactant", "intermediates", "products", "Product"},
    "adsorption_sites": {"adsorption_sites", "Adsorption Site"},
    "coverage": {"coverage", "Coverage"},
    "clusters_single_atoms": {"clusters", "single_atoms", "Cluster/Single Atom"},
    "reactions": {"applications", "Reaction Type"},
    "modeling_keywords": {"modeling_keywords", "Modeling Keywords", "recommended_modeling_tasks"},
}

PERIODIC_SYMBOLS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar",
    "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se",
    "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy",
    "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb",
    "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf",
    "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn", "Nh", "Fl",
    "Mc", "Lv", "Ts", "Og",
}

ELEMENT_NAMES = {
    "actinium",
    "aluminium",
    "aluminum",
    "americium",
    "antimony",
    "argon",
    "arsenic",
    "astatine",
    "barium",
    "berkelium",
    "beryllium",
    "bismuth",
    "bohrium",
    "boron",
    "bromine",
    "cadmium",
    "caesium",
    "calcium",
    "californium",
    "carbon",
    "cerium",
    "cesium",
    "chlorine",
    "chromium",
    "cobalt",
    "copernicium",
    "copper",
    "curium",
    "darmstadtium",
    "dubnium",
    "dysprosium",
    "einsteinium",
    "erbium",
    "europium",
    "fermium",
    "flerovium",
    "fluorine",
    "francium",
    "gadolinium",
    "gallium",
    "germanium",
    "gold",
    "hafnium",
    "hassium",
    "helium",
    "holmium",
    "hydrogen",
    "indium",
    "iodine",
    "iridium",
    "iron",
    "krypton",
    "lanthanum",
    "lawrencium",
    "lead",
    "lithium",
    "livermorium",
    "lutetium",
    "magnesium",
    "manganese",
    "meitnerium",
    "mendelevium",
    "mercury",
    "molybdenum",
    "moscovium",
    "neodymium",
    "neon",
    "neptunium",
    "nickel",
    "nihonium",
    "niobium",
    "nitrogen",
    "nobelium",
    "oganesson",
    "osmium",
    "oxygen",
    "palladium",
    "phosphorus",
    "platinum",
    "plutonium",
    "polonium",
    "potassium",
    "praseodymium",
    "promethium",
    "protactinium",
    "radium",
    "radon",
    "rhenium",
    "rhodium",
    "roentgenium",
    "rubidium",
    "ruthenium",
    "rutherfordium",
    "samarium",
    "scandium",
    "seaborgium",
    "selenium",
    "silicon",
    "silver",
    "sodium",
    "strontium",
    "sulfur",
    "sulphur",
    "tantalum",
    "technetium",
    "tellurium",
    "tennessine",
    "terbium",
    "thallium",
    "thorium",
    "thulium",
    "tin",
    "titanium",
    "tungsten",
    "uranium",
    "vanadium",
    "xenon",
    "ytterbium",
    "yttrium",
    "zinc",
    "zirconium",
}

REACTION_ABBREVIATIONS = {
    "OER",
    "HER",
    "HOR",
    "ORR",
    "CO2RR",
    "CO2R",
    "CO2ER",
    "CORR",
    "NRR",
    "NO3RR",
    "NO2RR",
    "MOR",
    "EOR",
    "AOR",
    "FOR",
    "FAOR",
    "GOR",
    "BOR",
    "UOR",
    "CER",
    "WOR",
    "WGS",
    "RWGS",
}

COMMON_FORMULA_OR_MOLECULE_TERMS = {
    "acetone",
    "ch3oh",
    "co",
    "co2",
    "h2",
    "h2o",
    "koh",
    "no",
    "o2",
    "oh",
    "oh*",
    "oh−",
    "water",
    "formaldehyde",
    "formic acid",
    "glycerol",
    "ethanol",
    "isobutene",
    "methanol",
    "oxygenates",
    "propane",
    "volatile organic compound",
    "volatile organic compounds",
}

COMMON_REACTION_OR_APPLICATION_TERMS = {
    "bifunctional electrocatalyst",
    "bifunctional electrocatalysts",
    "catalytic mechanism",
    "co oxidation",
    "co2 reduction",
    "condensation",
    "electrocatalysis",
    "electrocatalyst",
    "electrocatalysts",
    "electrocatalytic",
    "electrocatalytic activity",
    "electrocatalytic energy conversion",
    "electrocatalytic mechanism",
    "electrocatalytic oer",
    "electrocatalytic oxygen evolution reaction",
    "electrocatalytic water splitting",
    "electrochemical",
    "electrochemical oer",
    "electrochemical oxidation",
    "electrochemical oxidation of water",
    "electrochemical water splitting",
    "energy conversion technologies",
    "energy storage",
    "electrode materials",
    "electrolyzer efficiency",
    "fuel cell",
    "fuel cells",
    "hydrogen evolution reaction",
    "hydrogen evolution reaction (her)",
    "hydrogen generation",
    "hydrogen oxidation",
    "hydrogen production",
    "ketonization",
    "nitrogen reduction",
    "oer catalysts",
    "oxidation",
    "oxygen evolution reaction",
    "oxygen evolution reaction (oer)",
    "oxygen reduction",
    "oxygen reduction reaction",
    "polymer fuel cells",
    "proton exchange membrane fuel cells",
    "water oxidation",
    "water splitting",
}

GENERIC_EXPERIENCE_PLACEHOLDERS = {
    "full",
    "yes",
    "no",
    "none",
    "n/a",
    "not applicable",
}

MATERIAL_KIND_TOKENS = {
    "supported_catalyst": ("supported", "support", "/", "anchored", "metal-support"),
    "single_atom_catalyst": ("single atom", "single atoms", "sac", "sacs"),
    "nanoparticle": ("nanoparticle", "nanoparticles", "np", "nps"),
    "cluster": ("cluster", "nanocluster"),
    "nanosheet": ("nanosheet", "nanosheets"),
    "oxide": ("oxide", "o2", "ceo2", "tio2", "co3o4", "nio", "ruo2", "mno"),
    "hydroxide_oxyhydroxide": ("hydroxide", "oxyhydroxide", "ldh", "niooh", "feooh", "coooh"),
    "sulfide": ("sulfide", "mos2", "ws2", "fes", "nis", "cos"),
    "nitride": ("nitride", "nitrided", "mon"),
    "carbon_material": ("graphene", "carbon", "graphite", "cnt", "g-c3n4", "c3n4"),
    "surface": ("surface", "facet", "interface", "slab"),
}

TRANSITION_OR_SUPPORT_TOKENS = (
    "Pt", "Pd", "Ni", "Co", "Fe", "Cu", "Ru", "Rh", "Ir", "Au", "Ag", "Sn", "Zn", "Mn", "Cr", "V", "Mo", "W"
)

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

REACTION_KEYWORDS = [
    ("oxygen evolution reaction", "OER"),
    ("hydrogen evolution reaction", "HER"),
    ("oxygen reduction reaction", "ORR"),
    ("co2 reduction", "CO2RR"),
    ("carbon dioxide reduction", "CO2RR"),
    ("co oxidation", "CO oxidation"),
    ("methanol oxidation", "methanol oxidation"),
    ("water splitting", "water splitting"),
    ("nitrogen reduction", "NRR"),
    ("ammonia synthesis", "ammonia synthesis"),
]

GENERIC_REACTION_TYPES = {
    "catalyst preparation",
    "annealing",
    "electrochemical test",
    "electrochemical measurements",
    "electrochemical measurement",
    "electrochemical characterization",
    "characterization",
    "calcination",
    "reduction",
    "pretreatment",
    "synthesis",
}


def is_supported_modeling_task(value: str) -> bool:
    return value in SUPPORTED_MODELING_TASKS


def is_known_surface_term(value: str) -> bool:
    return is_known_surface_experience_term(value)


def is_known_modeling_term(value: str) -> bool:
    return is_known_surface_experience_term(value)


def is_element_symbol_expression(value: str) -> bool:
    cleaned = value.strip().strip("{}[]()")
    if not cleaned:
        return False
    parts = [part for part in re.split(r"[\s,;/+|&-]+", cleaned) if part]
    if not parts:
        return False
    return all(part in PERIODIC_SYMBOLS for part in parts)


def is_element_name_expression(value: str) -> bool:
    cleaned = re.sub(r"\([^)]*\)", "", value).strip().casefold()
    parts = [part for part in re.split(r"[\s,;/+|&-]+", cleaned) if part]
    if not parts:
        return False
    return all(part in ELEMENT_NAMES for part in parts)


def is_material_class_label(value: str) -> bool:
    return value.strip().casefold() in {material_class.casefold() for material_class in MATERIAL_CLASSES}


def is_formula_like_expression(value: str) -> bool:
    cleaned = value.strip().replace("–", "-").replace("—", "-")
    if not cleaned:
        return False
    if cleaned.casefold() in COMMON_FORMULA_OR_MOLECULE_TERMS:
        return True
    return bool(re.fullmatch(r"(?:[A-Z][a-z]?\d*){1,10}(?:[+\-/@](?:[A-Z][a-z]?\d*){1,10})*", cleaned))


def is_reaction_abbreviation(value: str) -> bool:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned in REACTION_ABBREVIATIONS


def is_simple_oxidation_state(value: str) -> bool:
    cleaned = value.strip()
    return bool(re.fullmatch(r"[A-Z][a-z]?\d*[+-]", cleaned)) and re.sub(r"\d|\+|-", "", cleaned) in PERIODIC_SYMBOLS


def is_known_surface_experience_term(value: str) -> bool:
    stripped = value.strip()
    lower = stripped.lower()
    if not stripped:
        return True
    if lower in GENERIC_EXPERIENCE_PLACEHOLDERS:
        return True
    if lower in SUPPORTED_MODELING_TASKS:
        return True
    if is_material_class_label(stripped):
        return True
    if is_element_symbol_expression(stripped):
        return True
    if is_element_name_expression(stripped):
        return True
    if is_formula_like_expression(stripped):
        return True
    if is_reaction_abbreviation(stripped):
        return True
    if is_simple_oxidation_state(stripped):
        return True
    if is_crystal_structure_term(stripped):
        return True
    if re.fullmatch(r"\(?\d[\d\s-]{1,8}\)?", stripped):
        return True
    if lower in COMMON_REACTION_OR_APPLICATION_TERMS:
        return True
    if any(term in lower for term in KNOWN_SURFACE_TERMS | KNOWN_MODELING_TOKENS):
        return True
    return False
