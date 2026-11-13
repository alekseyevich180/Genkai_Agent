"""Public PToModel API and artifact-aware workflow facade."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from genkai.contracts.artifacts import (
    EvidenceLevel,
    ExecutionState,
    ExtractionArtifact,
    ModelingPlanArtifact,
    ValidationStatus,
)
from genkai.contracts.run import StageRecord
from genkai.modeling.checklist import build_modeling_checklist
from genkai.modeling.mapping import (
    _build_argument_template,
    _infer_cluster_atom_count,
    _infer_material_classes,
    _load_surface_modeling_parameter_schema,
    build_ptomodel_payload,
    generate_ptomodel_output,
    main,
)
from genkai.workflow.store import load_manifest, save_manifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_modeling_plan(
    extraction: ExtractionArtifact,
    run_root: str | Path,
) -> ModelingPlanArtifact:
    root = Path(run_root)
    manifest = load_manifest(root)
    source = root / extraction.path
    payload = build_ptomodel_payload(str(source))

    modeling_dir = root / "modeling"
    modeling_dir.mkdir(parents=True, exist_ok=True)
    plan_path = modeling_dir / "plan.json"
    plan_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    checklist = build_modeling_checklist(payload)
    checklist["artifact_refs"] = {
        "paper": "article.json",
        "extraction": extraction.path.as_posix(),
        "modeling_plan": "modeling/plan.json",
        "checklist": "modeling/checklist.json",
    }
    checklist_path = modeling_dir / "checklist.json"
    checklist_path.write_text(
        json.dumps(checklist, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    needs_review = checklist["status"] == "needs_review"
    artifact = ModelingPlanArtifact(
        artifact_id=f"{manifest.run_id}:modeling-plan",
        path=plan_path.relative_to(root),
        sha256=_sha256(plan_path),
        producer="genkai.modeling.ptomodel",
        parent_ids=[extraction.artifact_id],
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.HEURISTIC,
        validation_status=(
            ValidationStatus.NEEDS_REVIEW
            if needs_review
            else ValidationStatus.PASSED
        ),
        metadata={
            "checklist_path": checklist_path.relative_to(root).as_posix(),
            "review_item_count": len(checklist["review_items"]),
        },
    )
    manifest.register_artifact(artifact)
    manifest.append_stage(
        StageRecord(
            stage_id="02_ptomodel",
            adapter="genkai.modeling.ptomodel",
            execution_state=ExecutionState.SUCCEEDED,
            input_artifact_ids=[extraction.artifact_id],
            output_artifact_ids=[artifact.artifact_id],
        )
    )
    save_manifest(root, manifest)
    return artifact


if __name__ == "__main__":
    raise SystemExit(main())
