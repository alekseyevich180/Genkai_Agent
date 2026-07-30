"""Run and stage manifests for reproducible workflows."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .artifacts import ArtifactRef, ExecutionState
from .validation import ValidationReport


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    execution_state: ExecutionState = ExecutionState.PLANNED
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=ValidationReport)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    run_id: str = Field(min_length=1)
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+(?:\.\d+)?$")
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    stages: list[StageRecord] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=ValidationReport)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_manifest_references(self) -> "RunManifest":
        stage_ids: set[str] = set()
        for stage in self.stages:
            if stage.stage_id in stage_ids:
                raise ValueError(f"duplicate stage_id: {stage.stage_id}")
            stage_ids.add(stage.stage_id)

        artifact_ids: set[str] = set()
        for artifact in self.artifacts:
            if artifact.artifact_id in artifact_ids:
                raise ValueError(f"duplicate artifact_id: {artifact.artifact_id}")
            missing = set(artifact.parent_ids).difference(artifact_ids)
            if missing:
                names = ", ".join(sorted(missing))
                raise ValueError(f"unknown parent artifact: {names}")
            artifact_ids.add(artifact.artifact_id)
        return self

    def append_stage(self, stage: StageRecord) -> None:
        if any(existing.stage_id == stage.stage_id for existing in self.stages):
            raise ValueError(f"duplicate stage_id: {stage.stage_id}")
        self.stages.append(stage)
        self.updated_at = _now()

    def register_artifact(self, artifact: ArtifactRef) -> None:
        existing_ids = {item.artifact_id for item in self.artifacts}
        if artifact.artifact_id in existing_ids:
            raise ValueError(f"duplicate artifact_id: {artifact.artifact_id}")
        missing = set(artifact.parent_ids).difference(existing_ids)
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"unknown parent artifact: {names}")
        self.artifacts.append(artifact)
        self.updated_at = _now()
