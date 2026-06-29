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
        "facets": [],
        "dopants": [],
        "defects": [],
        "active_sites": [],
        "adsorbates": [],
        "intermediates": [],
        "products": [],
        "properties": [],
        "reaction_parameters": [],
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
- `reaction_parameters` should capture parameters like temperature, time, pressure, atmosphere,
  solvent, pH, concentration, gas flow, potential, current density, conversion, selectivity,
  yield, rate, and stability when present.
- `links` should be a list of objects with keys: source, relation, target.
- Good relation examples: has_facet, has_dopant, has_defect, has_active_site,
  adsorbs, forms_intermediate, produces, shows_property, used_for, has_material_parameter,
  has_reaction_parameter.
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
            handle.write(json.dumps(output, ensure_ascii=False) + "\n")
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
