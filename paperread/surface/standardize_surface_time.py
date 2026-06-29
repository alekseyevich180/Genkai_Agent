from __future__ import annotations

import argparse

import pandas as pd

try:
    from .common import chat_completion, parse_markdown_table
except ImportError:  # pragma: no cover - direct script execution
    from common import chat_completion, parse_markdown_table


COLUMNS = ["Index", "Time"]


def build_prompt(table_text: str) -> str:
    return f"""
You will be given a markdown table with surface-research time expressions.
Standardize the Time column into minutes whenever possible.

Rules:
- Convert hours, days, overnight, and ranges into minutes.
- Keep qualitative labels only if they cannot be converted safely.
- Keep one row per input row.
- Output exactly one markdown table with columns: | Index | Time |

Input table:
{table_text}
""".strip()


def standardize_time(
    input_csv: str,
    output_csv: str,
    index_column: str = "Index",
    time_column: str = "Time",
    model: str | None = None,
) -> str:
    df = pd.read_csv(input_csv)
    lines = ["| Index | Time |", "|-------|------|"]
    for _, row in df.iterrows():
        time_value = row.get(time_column)
        if pd.isna(time_value):
            time_value = "N/A"
        lines.append(f"| {row[index_column]} | {time_value} |")
    response = chat_completion(build_prompt("\n".join(lines)), model=model)
    parsed = parse_markdown_table(response, COLUMNS)
    output_df = pd.DataFrame(parsed, columns=COLUMNS)
    output_df.to_csv(output_csv, index=False)
    return output_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standardize surface-research time expressions into minutes."
    )
    parser.add_argument("input_csv", help="Input CSV file.")
    parser.add_argument("output_csv", help="Output CSV file.")
    parser.add_argument("--index-column", default="Index", help="Index column name.")
    parser.add_argument("--time-column", default="Time", help="Time column name.")
    parser.add_argument("--model", default=None, help="Optional model override.")
    args = parser.parse_args()
    result = standardize_time(
        args.input_csv,
        args.output_csv,
        index_column=args.index_column,
        time_column=args.time_column,
        model=args.model,
    )
    print(result)


if __name__ == "__main__":
    main()
