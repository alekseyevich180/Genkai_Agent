"""Versioned references to scientific workflow artifacts."""

from __future__ import annotations

from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)

from .provenance import Provenance


class ExecutionState(str, Enum):
    PLANNED = "planned"
    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class EvidenceLevel(str, Enum):
    PAPER_EXTRACTED = "paper_extracted"
    HEURISTIC = "heuristic"
    MOCK = "mock"
    MLIP_PREDICTED = "mlip_predicted"
    DFT_CALCULATED = "dft_calculated"
    EXPERIMENT_REPORTED = "experiment_reported"


class ValidationStatus(str, Enum):
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    NOT_VALIDATED = "not_validated"


class _ArtifactBase(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    artifact_id: str = Field(min_length=1)
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+(?:\.\d+)?$")
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    producer: str = Field(min_length=1)
    parent_ids: list[str] = Field(default_factory=list)
    execution_state: ExecutionState = ExecutionState.PLANNED
    evidence_level: EvidenceLevel = EvidenceLevel.HEURISTIC
    validation_status: ValidationStatus = ValidationStatus.NOT_VALIDATED
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Field(default_factory=Provenance)

    @field_validator("path", mode="before")
    @classmethod
    def validate_run_relative_path(cls, value: object) -> str:
        raw = str(value)
        if "\\" in raw:
            raise ValueError("artifact paths must use POSIX separators")
        path = PurePosixPath(raw)
        if path.is_absolute() or not path.parts or path == PurePosixPath("."):
            raise ValueError("artifact path must be relative to the run root")
        if ".." in path.parts:
            raise ValueError("artifact path cannot escape the run root")
        return path.as_posix()

    @field_serializer("path")
    def serialize_path(self, value: Path) -> str:
        return value.as_posix()


class PaperArtifact(_ArtifactBase):
    artifact_type: Literal["paper"] = "paper"


class ExtractionArtifact(_ArtifactBase):
    artifact_type: Literal["extraction"] = "extraction"


class ModelingPlanArtifact(_ArtifactBase):
    artifact_type: Literal["modeling-plan"] = "modeling-plan"


class StructureSetArtifact(_ArtifactBase):
    artifact_type: Literal["structure-set"] = "structure-set"


class CalculationInputArtifact(_ArtifactBase):
    artifact_type: Literal["calculation-input"] = "calculation-input"


class CalculationResultArtifact(_ArtifactBase):
    artifact_type: Literal["calculation-result"] = "calculation-result"


DATASET_REQUIRED_METADATA = {
    "label_source",
    "energy_unit",
    "force_unit",
    "stress_unit",
    "electronic_structure_method",
    "functional",
    "pseudopotential_family",
    "split_strategy",
    "train_count",
    "validation_count",
    "test_count",
}


class DatasetArtifact(_ArtifactBase):
    artifact_type: Literal["dataset"] = "dataset"

    @model_validator(mode="after")
    def incomplete_metadata_requires_review(self) -> "DatasetArtifact":
        missing = DATASET_REQUIRED_METADATA.difference(self.metadata)
        if missing and self.validation_status is ValidationStatus.PASSED:
            raise ValueError(
                "dataset metadata is incomplete; validation_status must be needs_review"
            )
        return self


class ModelArtifact(_ArtifactBase):
    artifact_type: Literal["model"] = "model"


class EvaluationArtifact(_ArtifactBase):
    artifact_type: Literal["evaluation"] = "evaluation"


ArtifactRef = Annotated[
    Union[
        PaperArtifact,
        ExtractionArtifact,
        ModelingPlanArtifact,
        StructureSetArtifact,
        CalculationInputArtifact,
        CalculationResultArtifact,
        DatasetArtifact,
        ModelArtifact,
        EvaluationArtifact,
    ],
    Field(discriminator="artifact_type"),
]

ARTIFACT_ADAPTER: TypeAdapter[ArtifactRef] = TypeAdapter(ArtifactRef)


class ExternalResourceRef(BaseModel):
    """A read-only resource supplied by a shared external runtime."""

    model_config = ConfigDict(extra="forbid")

    uri: str = Field(min_length=1)
    resource_type: str = Field(min_length=1)
    version: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    read_only: bool = True

    @model_validator(mode="after")
    def require_read_only(self) -> "ExternalResourceRef":
        if not self.read_only:
            raise ValueError("external resources must be read-only")
        return self
