from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

try:
    from .common import chat_completion, load_records, parse_markdown_table
except ImportError:  # pragma: no cover - direct script execution
    from common import chat_completion, load_records, parse_markdown_table


COLUMNS = [
    "Reaction Type",
    "Material",
    "Composition",
    "Phase",
    "Morphology/Size",
    "Surface Area",
    "Surface/Support",
    "Facet",
    "Active Site",
    "Defect",
    "Dopant/Modifier",
    "Adsorbate/Reactant",
    "Feed/Concentration",
    "Atmosphere",
    "Pressure",
    "Gas Flow",
    "Solvent",
    "pH",
    "Temperature",
    "Time",
    "Loading",
    "Potential/Bias",
    "Current Density",
    "Product",
    "Conversion",
    "Selectivity",
    "Yield",
    "Rate/Activity",
    "Stability/Cycles",
]


def build_prompt(title: str, text: str) -> str:
    return f"""
You will be given a title and a surface-science-related passage. Extract experimental or processing
conditions into a markdown table for surface research.

Rules:
- Focus on surface reactions, catalyst preparation, adsorption tests, annealing, calcination,
  reduction, oxidation, deposition, electrochemical electrode preparation, and related workflows.
- Capture both reaction-related parameters and material-related parameters when present.
- Use "N/A" when information is absent or uncertain.
- If multiple independent procedures are present, use multiple rows.
- Keep multiple values in one cell separated by commas.
- Do not invent missing values.

Output exactly one markdown table with these columns:
| Reaction Type | Material | Composition | Phase | Morphology/Size | Surface Area | Surface/Support | Facet | Active Site | Defect | Dopant/Modifier | Adsorbate/Reactant | Feed/Concentration | Atmosphere | Pressure | Gas Flow | Solvent | pH | Temperature | Time | Loading | Potential/Bias | Current Density | Product | Conversion | Selectivity | Yield | Rate/Activity | Stability/Cycles |

Title:
{title}

Passage:
{text}
""".strip()


def extract_conditions(
    input_path: str,
    output_prefix: str,
    model: str | None = None,
    save_raw: bool = False,
) -> tuple[str | None, str]:
    records = load_records(input_path)
    raw_rows: list[dict[str, str]] = []
    table_rows: list[dict[str, str]] = []

    for record in records:
        for idx, text in enumerate(record["texts"], start=1):
            row_id = f'{record["id"]}_{idx}'
            response = chat_completion(build_prompt(record["title"], text), model=model)
            raw_rows.append(
                {
                    "Index": row_id,
                    "Title": record["title"],
                    "Passage": text,
                    "Summary": response,
                }
            )
            for parsed_row in parse_markdown_table(response, COLUMNS):
                parsed_row["Index"] = row_id
                table_rows.append(parsed_row)

    table_path = f"{output_prefix}_table.csv"
    raw_path = None
    if save_raw:
        raw_path = f"{output_prefix}_raw.csv"
        pd.DataFrame(raw_rows).to_csv(raw_path, index=False)
    pd.DataFrame(table_rows, columns=["Index"] + COLUMNS).to_csv(table_path, index=False)
    return raw_path, table_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract surface-research experimental conditions from JSON input."
    )
    parser.add_argument("input_json", help="JSON file containing Title/Text-style records.")
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Prefix for output CSV files. Defaults to the input path without suffix.",
    )
    parser.add_argument("--model", default=None, help="Optional model override.")
    parser.add_argument(
        "--save-raw",
        action="store_true",
        help="Also save raw LLM responses as <prefix>_raw.csv.",
    )
    args = parser.parse_args()

    output_prefix = args.output_prefix or str(Path(args.input_json).with_suffix(""))
    raw_path, table_path = extract_conditions(
        args.input_json,
        output_prefix,
        args.model,
        save_raw=args.save_raw,
    )
    if raw_path:
        print(raw_path)
    print(table_path)


if __name__ == "__main__":
    main()
