"""Static validation for artifact-aware workflow graphs."""

from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict, Field, model_validator

from genkai.contracts.validation import ValidationIssue, ValidationReport

from .stage import ArtifactRequirement, StageSpec


class WorkflowGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stages: list[StageSpec]
    inputs: list[ArtifactRequirement] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_stage_ids(self) -> "WorkflowGraph":
        ids = [stage.stage_id for stage in self.stages]
        if len(ids) != len(set(ids)):
            raise ValueError("workflow stage_id values must be unique")
        return self


def _has_cycle(stages: dict[str, StageSpec]) -> bool:
    indegree = {stage_id: 0 for stage_id in stages}
    outgoing = {stage_id: [] for stage_id in stages}
    for stage in stages.values():
        for dependency in stage.depends_on:
            if dependency in stages:
                indegree[stage.stage_id] += 1
                outgoing[dependency].append(stage.stage_id)

    ready = deque(stage_id for stage_id, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        stage_id = ready.popleft()
        visited += 1
        for downstream in outgoing[stage_id]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                ready.append(downstream)
    return visited != len(stages)


def validate_workflow(graph: WorkflowGraph) -> ValidationReport:
    errors: list[ValidationIssue] = []
    stages = {stage.stage_id: stage for stage in graph.stages}

    for stage in graph.stages:
        unknown = [item for item in stage.depends_on if item not in stages]
        for dependency in unknown:
            errors.append(
                ValidationIssue(
                    code="unknown_stage_dependency",
                    message=f"{stage.stage_id} depends on unknown stage {dependency}",
                    path=stage.stage_id,
                )
            )

        available = list(graph.inputs)
        for dependency in stage.depends_on:
            if dependency in stages:
                available.extend(stages[dependency].produces)

        for required in stage.consumes:
            same_type = [
                item
                for item in available
                if item.artifact_type == required.artifact_type
            ]
            if any(item.schema_major == required.schema_major for item in same_type):
                continue
            if same_type:
                errors.append(
                    ValidationIssue(
                        code="schema_version_incompatible",
                        message=(
                            f"{stage.stage_id} requires {required}; available major "
                            f"versions: {sorted({item.schema_major for item in same_type})}"
                        ),
                        path=stage.stage_id,
                    )
                )
            elif available:
                errors.append(
                    ValidationIssue(
                        code="artifact_type_mismatch",
                        message=(
                            f"{stage.stage_id} requires {required}; dependencies "
                            "produce different artifact types"
                        ),
                        path=stage.stage_id,
                    )
                )
            else:
                errors.append(
                    ValidationIssue(
                        code="missing_artifact_producer",
                        message=f"no producer is available for {required}",
                        path=stage.stage_id,
                    )
                )

    if _has_cycle(stages):
        errors.append(
            ValidationIssue(
                code="workflow_cycle",
                message="workflow dependencies contain a cycle",
            )
        )

    return ValidationReport(
        errors=errors,
        checks=(
            []
            if errors
            else [
                ValidationIssue(
                    code="workflow_contracts_valid",
                    message="all workflow artifact dependencies are satisfiable",
                )
            ]
        ),
    )
