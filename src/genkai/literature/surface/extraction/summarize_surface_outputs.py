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
    content = Path(jsonl_path).read_text(encoding="utf-8").strip()
    if not content:
        return {}

    try:
        payload = json.loads(content)
        if isinstance(payload, list):
            return payload[0].get("extraction", {}) if payload else {}
        if isinstance(payload, dict):
            return payload.get("extraction", {})
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    idx = 0
    length = len(content)
    while idx < length:
        while idx < length and content[idx].isspace():
            idx += 1
        if idx >= length:
            break
        payload, next_idx = decoder.raw_decode(content, idx)
        if isinstance(payload, dict):
            return payload.get("extraction", {})
        idx = next_idx
    return {}


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
        facet = _clean(row.get("Facet"))
        adsorbate = _clean(row.get("Adsorbate/Reactant"))
        adsorption_site = _clean(row.get("Adsorption Site"))
        coverage = _clean(row.get("Coverage"))
        cluster = _clean(row.get("Cluster/Single Atom"))
        modeling_keywords = _clean(row.get("Modeling Keywords"))

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
        if material and facet:
            line = f"- {material} 暴露/涉及晶面 {facet}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if adsorbate:
            site_part = f"，吸附位点 {adsorption_site}" if adsorption_site else ""
            coverage_part = f"，覆盖度 {coverage}" if coverage else ""
            line = f"- 吸附物/反应物：{adsorbate}{site_part}{coverage_part}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if cluster:
            line = f"- 团簇/单原子建模线索：{cluster}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
        if modeling_keywords:
            line = f"- 建模关键词：{modeling_keywords}"
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
    surfaces = _flatten_param_items(relations.get("surfaces", []))
    facets = _flatten_param_items(relations.get("facets", []))
    surface_terminations = _flatten_param_items(relations.get("surface_terminations", []))
    defects = _flatten_param_items(relations.get("defects", []))
    vacancy_models = _flatten_param_items(relations.get("vacancy_models", []))
    active_sites = _flatten_param_items(relations.get("active_sites", []))
    adsorbates = _flatten_param_items(relations.get("adsorbates", []))
    adsorption_sites = _flatten_param_items(relations.get("adsorption_sites", []))
    coverage = _flatten_param_items(relations.get("coverage", []))
    clusters = _flatten_param_items(relations.get("clusters", []))
    single_atoms = _flatten_param_items(relations.get("single_atoms", []))
    modeling_keywords = _flatten_param_items(relations.get("modeling_keywords", []))
    recommended_tasks = _flatten_param_items(relations.get("recommended_modeling_tasks", []))

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
        "- 材料：",
    ])
    if materials:
        lines.extend([f"  - {item}" for item in materials])
    else:
        lines.append("  - 未提取")

    lines.append("- 材料参数：")
    if material_parameters:
        lines.extend([f"  - {item}" for item in material_parameters])
    else:
        lines.append("  - 未提取")

    lines.append("- 反应参数：")
    if reaction_parameters:
        lines.extend([f"  - {item}" for item in reaction_parameters])
    else:
        lines.append("  - 未提取")

    lines.append("- 性能：")
    if properties:
        lines.extend([f"  - {item}" for item in properties])
    else:
        lines.append("  - 未提取")

    lines.append("- 表面/晶面：")
    surface_items = surfaces + facets + surface_terminations
    if surface_items:
        lines.extend([f"  - {item}" for item in surface_items])
    else:
        lines.append("  - 未提取")

    lines.append("- 缺陷/活性位点：")
    defect_items = defects + vacancy_models + active_sites
    if defect_items:
        lines.extend([f"  - {item}" for item in defect_items])
    else:
        lines.append("  - 未提取")

    lines.append("- 吸附/覆盖度：")
    adsorption_items = adsorbates + adsorption_sites + coverage
    if adsorption_items:
        lines.extend([f"  - {item}" for item in adsorption_items])
    else:
        lines.append("  - 未提取")

    site_context_lines = []
    if surface_items and (active_sites or adsorption_sites):
        site_context_lines.append(f"  - 表面: {', '.join(surfaces[:3] + facets[:3])}")
        if active_sites:
            site_context_lines.append(f"  - active site: {', '.join(active_sites[:3])}")
        if adsorption_sites:
            site_context_lines.append(f"  - adsorption site: {', '.join(adsorption_sites[:3])}")
    if site_context_lines:
        lines.append("- 表面-位点关联：")
        lines.extend(site_context_lines)

    lines.append("- 团簇/单原子：")
    cluster_items = clusters + single_atoms
    if cluster_items:
        lines.extend([f"  - {item}" for item in cluster_items])
    else:
        lines.append("  - 未提取")

    lines.append("- 建模关键词：")
    if modeling_keywords:
        lines.extend([f"  - {item}" for item in modeling_keywords])
    else:
        lines.append("  - 未提取")

    lines.append("- 推荐建模任务：")
    if recommended_tasks:
        lines.extend([f"  - {item}" for item in recommended_tasks])
    else:
        lines.append("  - 未提取")
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
