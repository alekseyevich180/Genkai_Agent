from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .common import chat_completion, extract_json_block, load_records
except ImportError:  # pragma: no cover - direct script execution
    from common import chat_completion, extract_json_block, load_records


def build_prompt(title: str, text: str) -> str:
    schema = {
        "materials": [],
        "material_parameters": [],
        "surfaces": [],
        "surface_terminations": [],
        "slab_models": [],
        "facets": [],
        "dopants": [],
        "defects": [],
        "vacancy_models": [],
        "active_sites": [],
        "adsorbates": [],
        "adsorption_sites": [],
        "coverage": [],
        "intermediates": [],
        "products": [],
        "clusters": [],
        "single_atoms": [],
        "modifiers": [],
        "properties": [],
        "reaction_parameters": [],
        "modeling_keywords": [],
        "recommended_modeling_tasks": [],
        "applications": [],
        "links": [],
    }
    return f"""
You are extracting structured knowledge for surface science.

Return one JSON object only. Use this schema:
{json.dumps(schema, ensure_ascii=False)}

Rules:
- Extract only information supported by the text.
- Prefer short normalized phrases.
- `material_parameters` should capture parameters like composition, phase, morphology, particle size,
  surface area, loading, oxidation state, support, and crystal structure when present.
- `surfaces` should capture named surfaces, supports, slab materials, exposed surfaces, and surface
  phrases such as CeO2 surface, TiO2(110), Pt/CeO2, oxide surface, electrode surface, or interface.
- `surface_terminations` should capture terminations or functionalized surface states such as
  O-terminated, metal-terminated, hydroxylated, sulfurized, nitrided, reduced, oxidized, or reconstructed.
- `slab_models` should capture explicit slab/model cues such as slab, monolayer, bilayer,
  supercell, surface model, periodic model, exposed facet, or computational surface.
- `reaction_parameters` should capture parameters like temperature, time, pressure, atmosphere,
  solvent, pH, concentration, gas flow, potential, current density, conversion, selectivity,
  yield, rate, and stability when present.
- `defects` and `vacancy_models` should capture oxygen vacancy, sulfur vacancy, anion vacancy,
  cation vacancy, defect-rich, vacancy-rich, Vo, and related concentration/count information.
- `adsorbates`, `adsorption_sites`, and `coverage` should capture molecular adsorbates, surface
  intermediates with * notation, site names, bridge/top/hollow sites, monodentate/bidentate binding,
  coverage, monolayer, saturation coverage, and coadsorption when present.
- `clusters`, `single_atoms`, and `modifiers` should capture supported metal clusters, nanoparticles,
  cluster sizes such as Pt13, single atom catalysts, isolated metal sites, promoters, modifiers,
  dopants, decoration, loading, anchoring, and metal-support interaction terms.
- `modeling_keywords` should be a flat list of keywords useful for downstream structure generation.
- `recommended_modeling_tasks` should use only supported task names when evidence exists:
  vacancy_landscape, adsorbate_landscape, surface_cluster_builder, single_atom_site,
  doped_surface, surface_functionalization, slab_generation.
- `links` should be a list of objects with keys: source, relation, target.
- Good relation examples: has_facet, has_dopant, has_defect, has_active_site,
  adsorbs, forms_intermediate, produces, shows_property, used_for, has_material_parameter,
  has_reaction_parameter, has_termination, has_adsorption_site, has_coverage,
  has_cluster, has_single_atom, suggests_modeling_task.
- If a field has no evidence, return an empty list.

Title:
{title}

Passage:
{text}
""".strip()


def extract_relations(input_path: str, output_jsonl: str, model: str | None = None) -> str:
    records = load_records(input_path)
    with open(output_jsonl, "w", encoding="utf-8") as handle:
        for record in records:
            joined_text = "\n".join(record["texts"])
            response = chat_completion(build_prompt(record["title"], joined_text), model=model)
            payload = extract_json_block(response)
            output = {
                "id": record["id"],
                "title": record["title"],
                "text": joined_text,
                "extraction": payload,
            }
            handle.write(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    return output_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract surface-material entities and relations from JSON input."
    )
    parser.add_argument("input_json", help="JSON file containing Title/Text-style records.")
    parser.add_argument(
        "--output-jsonl",
        default=None,
        help="Output JSONL path. Defaults to the input path with _surface_relations.jsonl suffix.",
    )
    parser.add_argument("--model", default=None, help="Optional model override.")
    args = parser.parse_args()

    output_jsonl = args.output_jsonl or f"{Path(args.input_json).with_suffix('')}_surface_relations.jsonl"
    result = extract_relations(args.input_json, output_jsonl, args.model)
    print(result)


if __name__ == "__main__":
    main()
