from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"", "N/A", "nan"} else text


def _read_relations(jsonl_path: str) -> dict[str, object]:
    with open(jsonl_path, "r", encoding="utf-8") as handle:
        line = handle.readline().strip()
    return json.loads(line)["extraction"] if line else {}


def _collect_condition_lines(df: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()

    for _, row in df.iterrows():
        material = _clean(row.get("Material"))
        reaction_type = _clean(row.get("Reaction Type"))
        atmosphere = _clean(row.get("Atmosphere"))
        temperature = _clean(row.get("Temperature"))
        time = _clean(row.get("Time"))
        composition = _clean(row.get("Composition"))
        surface_area = _clean(row.get("Surface Area"))
        current_density = _clean(row.get("Current Density"))
        cycles = _clean(row.get("Stability/Cycles"))

        if material and atmosphere and temperature and time:
            line = f"- {material} 在 {atmosphere} 气氛下 {temperature}、{time} {reaction_type or '处理'}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if composition:
            line = f"- {composition}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if surface_area:
            line = f"- {surface_area}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if reaction_type == "Electrochemical Testing" and current_density and cycles:
            line = f"- 电化学测试 {current_density}、{cycles}"
            if line not in seen:
                seen.add(line)
                lines.append(line)

    return lines


def _flatten_param_items(items: list[object]) -> list[str]:
    results: list[str] = []
    for item in items:
        if isinstance(item, dict):
            for _, value in item.items():
                cleaned = _clean(value)
                if cleaned:
                    results.append(cleaned)
        else:
            cleaned = _clean(item)
            if cleaned:
                results.append(cleaned)
    return results


def build_summary_text(table_csv: str, relations_jsonl: str) -> str:
    table_name = Path(table_csv).name
    relations_name = Path(relations_jsonl).name

    df = pd.read_csv(table_csv)
    relations = _read_relations(relations_jsonl)

    condition_lines = _collect_condition_lines(df)
    materials = _flatten_param_items(relations.get("materials", []))
    material_parameters = _flatten_param_items(relations.get("material_parameters", []))
    reaction_parameters = _flatten_param_items(relations.get("reaction_parameters", []))
    properties = _flatten_param_items(relations.get("properties", []))

    lines = [
        "这次抽到的关键信息包括：",
        "",
        f"在 {table_name} 里：",
        "",
    ]
    lines.extend(condition_lines or ["- 未提取到可汇总的条件信息"])
    lines.extend([
        "",
        f"在 {relations_name} 里：",
        "",
        f"- 材料：{'、'.join(materials) if materials else '未提取'}",
        f"- 材料参数：{'、'.join(material_parameters) if material_parameters else '未提取'}",
        f"- 反应参数：{'、'.join(reaction_parameters) if reaction_parameters else '未提取'}",
        f"- 性能：{'、'.join(properties) if properties else '未提取'}",
    ])
    return "\n".join(lines) + "\n"


def write_summary(table_csv: str, relations_jsonl: str, output_txt: str) -> str:
    summary_text = build_summary_text(table_csv, relations_jsonl)
    Path(output_txt).write_text(summary_text, encoding="utf-8")
    return output_txt


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a human-readable TXT summary from surface extraction outputs."
    )
    parser.add_argument("table_csv", help="Condition table CSV.")
    parser.add_argument("relations_jsonl", help="Surface relations JSONL.")
    parser.add_argument("output_txt", help="Summary TXT output path.")
    args = parser.parse_args()
    result = write_summary(args.table_csv, args.relations_jsonl, args.output_txt)
    print(result)


if __name__ == "__main__":
    main()

