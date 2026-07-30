"""YAML-frontmatter contracts for stable built-in skills."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from genkai.contracts.validation import ValidationIssue, ValidationReport


ARTIFACT_VERSION = re.compile(r"^[a-z][a-z0-9-]*@[1-9]\d*$")
ALLOWED_MATURITIES = {"stable"}
ALLOWED_DOMAINS = {"literature", "modeling", "compute", "mlip"}


class SkillMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    maturity: str | None = None
    domain: str | None = None
    tools: list[str] = Field(default_factory=list)
    dependent_skills: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)


class SkillContract(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str
    metadata: SkillMetadata
    skill_dir: Path
    evaluations: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} does not begin with YAML frontmatter")
    try:
        raw, _body = text[4:].split("\n---", 1)
    except ValueError as exc:
        raise ValueError(f"{path} has unterminated YAML frontmatter") from exc
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} frontmatter must be a mapping")
    return payload


def load_skill_contract(skill_dir: Path) -> SkillContract:
    skill_dir = Path(skill_dir)
    payload = _frontmatter(skill_dir / "SKILL.md")
    evaluations_path = skill_dir / "evaluations" / "cases.yaml"
    evaluations: dict[str, list[dict[str, Any]]] = {}
    if evaluations_path.is_file():
        loaded = yaml.safe_load(evaluations_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            evaluations = {
                str(key): value if isinstance(value, list) else []
                for key, value in loaded.items()
            }
    return SkillContract(
        name=str(payload.get("name", "")),
        description=str(payload.get("description", "")),
        metadata=SkillMetadata.model_validate(payload.get("metadata") or {}),
        skill_dir=skill_dir,
        evaluations=evaluations,
    )


def validate_skill_contract(
    contract: SkillContract,
    known_skills: set[str],
) -> ValidationReport:
    errors: list[ValidationIssue] = []
    metadata = contract.metadata
    if "dependent_skills" not in metadata.model_fields_set:
        errors.append(
            ValidationIssue(
                code="missing_dependent_skills",
                message="stable skill metadata requires dependent_skills",
            )
        )
    if not metadata.maturity:
        errors.append(
            ValidationIssue(
                code="missing_maturity",
                message="stable skill metadata requires maturity",
            )
        )
    elif metadata.maturity not in ALLOWED_MATURITIES:
        errors.append(
            ValidationIssue(
                code="invalid_maturity",
                message=f"unsupported stable skill maturity: {metadata.maturity}",
            )
        )
    if not metadata.domain:
        errors.append(
            ValidationIssue(
                code="missing_domain",
                message="stable skill metadata requires domain",
            )
        )
    elif metadata.domain not in ALLOWED_DOMAINS:
        errors.append(
            ValidationIssue(
                code="invalid_domain",
                message=f"unsupported stable skill domain: {metadata.domain}",
            )
        )
    for field_name in ("tools", "consumes", "produces", "entrypoints"):
        if field_name not in metadata.model_fields_set:
            errors.append(
                ValidationIssue(
                    code=f"missing_{field_name}",
                    message=f"stable skill metadata requires {field_name}",
                )
            )
        elif not getattr(metadata, field_name):
            errors.append(
                ValidationIssue(
                    code=f"empty_{field_name}",
                    message=f"stable skill metadata requires nonempty {field_name}",
                )
            )
    if not contract.description.startswith("Use when"):
        errors.append(
            ValidationIssue(
                code="invalid_description_prefix",
                message="skill description must start with 'Use when'",
            )
        )
    for dependency in metadata.dependent_skills:
        if dependency not in known_skills:
            errors.append(
                ValidationIssue(
                    code="unknown_skill_dependency",
                    message=f"unknown dependent skill: {dependency}",
                )
            )
    for value in [*metadata.consumes, *metadata.produces]:
        if ARTIFACT_VERSION.fullmatch(value) is None:
            errors.append(
                ValidationIssue(
                    code="invalid_artifact_version",
                    message=f"invalid artifact requirement: {value}",
                )
            )
    for raw_path in metadata.entrypoints:
        path = PurePosixPath(raw_path)
        valid_relative = not path.is_absolute() and ".." not in path.parts
        if not valid_relative or not (contract.skill_dir / raw_path).is_file():
            errors.append(
                ValidationIssue(
                    code="missing_entrypoint",
                    message=f"skill entrypoint does not exist: {raw_path}",
                )
            )
    for category in ("positive", "negative", "boundary"):
        if not contract.evaluations.get(category):
            errors.append(
                ValidationIssue(
                    code="missing_evaluation_category",
                    message=f"skill evaluations require non-empty {category} cases",
                )
            )
    return ValidationReport(errors=errors)
