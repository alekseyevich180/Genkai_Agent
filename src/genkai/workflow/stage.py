"""Stage declarations for artifact-aware workflows."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from genkai.contracts.artifacts import ArtifactRef
from genkai.contracts.validation import ValidationReport


_REQUIREMENT = re.compile(r"^(?P<kind>[a-z][a-z0-9-]*)@(?P<major>[1-9]\d*)$")


class ArtifactRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    schema_major: int = Field(ge=1)

    @classmethod
    def parse(cls, value: str) -> "ArtifactRequirement":
        match = _REQUIREMENT.fullmatch(value)
        if match is None:
            raise ValueError(
                "artifact requirement must use '<artifact-type>@<major>'"
            )
        return cls(
            artifact_type=match.group("kind"),
            schema_major=int(match.group("major")),
        )

    def __str__(self) -> str:
        return f"{self.artifact_type}@{self.schema_major}"


class StageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: str = Field(min_length=1)
    adapter: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    consumes: list[ArtifactRequirement] = Field(default_factory=list)
    produces: list[ArtifactRequirement] = Field(default_factory=list)
    allows_mock_inputs: bool = False

    @field_validator("consumes", "produces", mode="before")
    @classmethod
    def parse_requirement_strings(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                ArtifactRequirement.parse(item) if isinstance(item, str) else item
                for item in value
            ]
        return value


class StageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifacts: list[ArtifactRef] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=ValidationReport)
    manifest_path: Path | None = None
    command: list[str] | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class StageAdapter(Protocol):
    def preflight(self) -> ValidationReport:
        """Validate a stage without starting external execution."""
