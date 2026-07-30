from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any


REVIEW_STATUSES = {
    "needs_manual_decision",
    "needs_upstream_artifact",
    "unresolved_required",
    "stable_facet_registry_or_manual",
}


def _read_csv(path: str | None) -> list[dict[str, str]]:
    if not path or not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json_records(path: str | None) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, list) else [payload]
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def build_modeling_checklist(plan: dict[str, Any]) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    review_items: list[dict[str, Any]] = []
    for document in plan.get("documents", []):
        templates = document.get("task_argument_template", {})
        for task_name in document.get("recommended_modeling_tasks", []):
            template = templates.get(task_name, {})
            bindings = template.get("parameter_bindings", {})
            task_review = []
            for parameter, binding in bindings.items():
                if binding.get("status") not in REVIEW_STATUSES:
                    continue
                item = {
                    "document_id": document.get("id"),
                    "task": task_name,
                    "parameter": parameter,
                    "status": binding.get("status"),
                    "source_term": binding.get("source_term"),
                    "reason": binding.get("reason"),
                    "depends_on": binding.get("depends_on", []),
                }
                task_review.append(item)
                review_items.append(item)
            tasks.append(
                {
                    "document_id": document.get("id"),
                    "task": task_name,
                    "executable": task_name in document.get("executable_tasks", []),
                    "arguments": template.get("arguments", {}),
                    "auto_mapped_parameters": template.get("auto_mapped_parameters", []),
                    "review_items": task_review,
                }
            )

    return {
        "schema_version": "1.0",
        "status": "needs_review" if review_items else "ready",
        "rules": {
            "materials_project_api_key": "Read MP_API_KEY from the environment; never persist it.",
            "surface_loading": "Nanoparticles may only be placed on a vacuum-containing slab, never directly on a bulk unit cell.",
            "facet_priority": [
                "paper-explicit facet",
                "reviewed stable-facet registry",
                "manual reviewed facet",
            ],
            "missing_facet_policy": "Stop when no reviewed stable facet can be resolved.",
        },
        "tasks": tasks,
        "review_items": review_items,
        "expected_model_files": {
            "bulk_reference": "modeling/structures/bulk_from_materials_project.cif",
            "surface_slab": "modeling/structures/stable_surface_slab.vasp",
            "supported_nanoparticle": "modeling/structures/*_on_surface.cif",
            "modeling_manifest": "modeling/structures/modeling_manifest.json",
        },
    }


_modeling_checklist = build_modeling_checklist


def write_compact_job_bundle(
    *,
    output_dir: str,
    outputs: dict[str, str],
    source_path: str | None = None,
    cleanup_generated: bool = True,
) -> dict[str, str]:
    outdir = Path(output_dir)
    modeling_dir = outdir / "modeling"
    structures_dir = modeling_dir / "structures"
    structures_dir.mkdir(parents=True, exist_ok=True)

    relation_records = _read_json_records(outputs.get("relations_jsonl"))
    conditions = _read_csv(outputs.get("conditions_csv"))
    times = _read_csv(outputs.get("time_csv"))
    summary = ""
    if outputs.get("summary_txt") and Path(outputs["summary_txt"]).exists():
        summary = Path(outputs["summary_txt"]).read_text(encoding="utf-8")
    title = relation_records[0].get("title") if relation_records else None
    article = {
        "schema_version": "1.0",
        "source": source_path,
        "title": title,
        "conditions": conditions,
        "standardized_time": times,
        "surface_relations": [record.get("extraction", record) for record in relation_records],
        "summary": summary,
    }
    article_path = outdir / "article.json"
    article_path.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")

    plan: dict[str, Any] = {}
    if outputs.get("ptomodel_json") and Path(outputs["ptomodel_json"]).exists():
        plan = json.loads(Path(outputs["ptomodel_json"]).read_text(encoding="utf-8"))
    plan_path = modeling_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    checklist = build_modeling_checklist(plan)
    checklist["files"] = {
        "article": str(article_path.relative_to(outdir)),
        "modeling_plan": str(plan_path.relative_to(outdir)),
        "structures_directory": str(structures_dir.relative_to(outdir)),
    }
    checklist_path = modeling_dir / "checklist.json"
    checklist_path.write_text(json.dumps(checklist, ensure_ascii=False, indent=2), encoding="utf-8")

    compact_paths = {article_path.resolve(), plan_path.resolve(), checklist_path.resolve()}
    if cleanup_generated:
        for key, raw_path in outputs.items():
            path = Path(raw_path)
            if not path.exists() or path.resolve() in compact_paths:
                continue
            if path.is_file() and outdir.resolve() in path.resolve().parents:
                path.unlink()
            elif key == "experience_material_classes_dir" and path.is_dir() and outdir.resolve() in path.resolve().parents:
                shutil.rmtree(path)

    return {
        "article_json": str(article_path),
        "modeling_plan_json": str(plan_path),
        "modeling_checklist_json": str(checklist_path),
        "modeling_structures_dir": str(structures_dir),
    }
