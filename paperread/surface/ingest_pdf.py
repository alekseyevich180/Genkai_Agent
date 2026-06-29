from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


SECTION_ALIASES = {
    "abstract": "abstract",
    "introduction": "introduction",
    "experimental": "methods",
    "experiment": "methods",
    "materials and methods": "methods",
    "methods": "methods",
    "method": "methods",
    "results": "results",
    "results and discussion": "results_discussion",
    "discussion": "discussion",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
}


def _run_command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return result.stdout


def extract_pdf_text(pdf_path: str) -> str:
    return _run_command(["pdftotext", "-layout", pdf_path, "-"])


def extract_pdf_title(pdf_path: str) -> str:
    info = _run_command(["pdfinfo", pdf_path])
    for line in info.splitlines():
        if line.startswith("Title:"):
            title = line.split(":", 1)[1].strip()
            if title:
                return title
    return ""


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def infer_title(text: str, metadata_title: str = "") -> str:
    if metadata_title:
        return metadata_title
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned and len(cleaned) <= 300:
            return cleaned
    return "Untitled surface paper"


def split_sections(text: str) -> dict[str, str]:
    normalized = normalize_text(text)
    sections: dict[str, list[str]] = {"full_text": []}
    current_key = "full_text"
    for line in normalized.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        canonical = SECTION_ALIASES.get(lowered)
        if canonical and len(stripped.split()) <= 5:
            current_key = canonical
            sections.setdefault(current_key, [])
            continue
        sections.setdefault(current_key, []).append(stripped)
    return {key: "\n".join(value).strip() for key, value in sections.items() if any(v for v in value)}


def build_surface_inputs_from_sections(
    title: str,
    sections: dict[str, str],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    methods_text = "\n\n".join(
        part for part in (
            sections.get("methods", ""),
            sections.get("results", ""),
        )
        if part
    ) or sections.get("full_text", "")

    relations_text = "\n\n".join(
        part for part in (
            sections.get("abstract", ""),
            sections.get("results_discussion", ""),
            sections.get("results", ""),
            sections.get("discussion", ""),
            sections.get("conclusion", ""),
        )
        if part
    ) or sections.get("full_text", "")

    conditions_payload = {
        "surface_conditions": {
            "Title": title,
            "Text": methods_text,
        }
    }
    relations_payload = {
        "surface_relations": {
            "Title": title,
            "Text": relations_text,
        }
    }
    return conditions_payload, relations_payload


def ingest_pdf(
    pdf_path: str,
    output_dir: str,
) -> dict[str, str]:
    outdir = Path(output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    raw_text = extract_pdf_text(pdf_path)
    normalized = normalize_text(raw_text)
    title = infer_title(normalized, extract_pdf_title(pdf_path))
    sections = split_sections(normalized)
    conditions_payload, relations_payload = build_surface_inputs_from_sections(title, sections)

    stem = Path(pdf_path).stem
    text_path = outdir / f"{stem}_text.txt"
    sections_path = outdir / f"{stem}_sections.json"
    conditions_path = outdir / f"{stem}_conditions_input.json"
    relations_path = outdir / f"{stem}_relations_input.json"

    text_path.write_text(normalized, encoding="utf-8")
    sections_path.write_text(json.dumps({"title": title, "sections": sections}, ensure_ascii=False, indent=2), encoding="utf-8")
    conditions_path.write_text(json.dumps(conditions_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    relations_path.write_text(json.dumps(relations_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "text_path": str(text_path),
        "sections_path": str(sections_path),
        "conditions_input_json": str(conditions_path),
        "relations_input_json": str(relations_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract surface-oriented text sections from a PDF file."
    )
    parser.add_argument("input_pdf", help="Input PDF file.")
    parser.add_argument(
        "--output-dir",
        default="paperread/surface/output",
        help="Directory for generated intermediate files.",
    )
    args = parser.parse_args()
    outputs = ingest_pdf(args.input_pdf, args.output_dir)
    for _, path in outputs.items():
        print(path)


if __name__ == "__main__":
    main()

