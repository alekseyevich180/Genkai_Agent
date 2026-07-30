"""Surface candidate preparation facade."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from genkai.contracts.artifacts import (
    EvidenceLevel,
    ExecutionState,
    ModelingPlanArtifact,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.run import StageRecord
from genkai.workflow.store import load_manifest, save_manifest


def build_surface_candidates(
    plan: ModelingPlanArtifact,
    run_root: str | Path,
    mode: Literal["dry-run", "production"] = "dry-run",
) -> StructureSetArtifact:
    """Prepare candidate-generation tasks without invoking skill scripts."""

    root = Path(run_root)
    manifest = load_manifest(root)
    plan_payload = json.loads((root / plan.path).read_text(encoding="utf-8"))
    checklist_path = root / str(plan.metadata["checklist_path"])
    checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
    output_path = root / "stages" / "03_surface_modeling" / "candidates.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "execution_mode": mode,
        "execution_state": "prepared",
        "source_plan": plan.path.as_posix(),
        "tasks": plan_payload.get("global_executable_tasks", []),
        "manual_decisions": checklist.get("review_items", []),
        "structures": [],
        "note": "Candidate commands are prepared; no modeling script was executed.",
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    artifact = StructureSetArtifact(
        artifact_id=f"{manifest.run_id}:structure-set",
        path=output_path.relative_to(root),
        sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
        producer="genkai.modeling.surface",
        parent_ids=[plan.artifact_id],
        execution_state=ExecutionState.PREPARED,
        evidence_level=EvidenceLevel.HEURISTIC,
        validation_status=ValidationStatus.NEEDS_REVIEW,
        metadata={
            "structure_count": 0,
            "mode": mode,
            "contains_command_plan_only": True,
        },
    )
    manifest.register_artifact(artifact)
    manifest.append_stage(
        StageRecord(
            stage_id="03_surface_modeling",
            adapter="genkai.modeling.surface",
            execution_state=ExecutionState.PREPARED,
            input_artifact_ids=[plan.artifact_id],
            output_artifact_ids=[artifact.artifact_id],
        )
    )
    save_manifest(root, manifest)
    return artifact
