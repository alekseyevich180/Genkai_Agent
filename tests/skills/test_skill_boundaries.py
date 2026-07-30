from pathlib import Path

import pytest

from genkai.skills.contract import load_skill_contract, validate_skill_contract


BASE_METADATA = """
  maturity: stable
  domain: mlip
  tools: [run_skill_script]
  dependent_skills: []
  consumes: [dataset@1]
  produces: [model@1]
  entrypoints: [scripts/run.py]
"""


def _write_skill(
    root: Path,
    *,
    description: str = "Use when a validated dataset needs model training.",
    metadata: str = BASE_METADATA,
    create_entrypoint: bool = True,
) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        f"---\nname: sample\ndescription: {description}\nmetadata:\n{metadata}---\n\n# Sample\n",
        encoding="utf-8",
    )
    (root / "evaluations").mkdir()
    (root / "evaluations" / "cases.yaml").write_text(
        "positive: [{prompt: train this model}]\n"
        "negative: [{prompt: summarize a paper}]\n"
        "boundary: [{prompt: use MACE inference instead}]\n",
        encoding="utf-8",
    )
    if create_entrypoint:
        (root / "scripts").mkdir()
        (root / "scripts" / "run.py").write_text("", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("metadata", "description", "entrypoint", "known", "error_code"),
    [
        (
            BASE_METADATA.replace("  maturity: stable\n", ""),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "missing_maturity",
        ),
        (
            BASE_METADATA.replace(
                "  dependent_skills: []", "  dependent_skills: [unknown]"
            ),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "unknown_skill_dependency",
        ),
        (
            BASE_METADATA.replace("dataset@1", "dataset-v1"),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "invalid_artifact_version",
        ),
        (
            BASE_METADATA,
            "Use when a validated dataset needs model training.",
            False,
            {"sample"},
            "missing_entrypoint",
        ),
        (
            BASE_METADATA,
            "Train a model from a dataset.",
            True,
            {"sample"},
            "invalid_description_prefix",
        ),
        (
            BASE_METADATA.replace("  tools: [run_skill_script]\n", ""),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "missing_tools",
        ),
        (
            BASE_METADATA.replace(
                "  tools: [run_skill_script]", "  tools: []"
            ),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "empty_tools",
        ),
        (
            BASE_METADATA.replace("  dependent_skills: []\n", ""),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "missing_dependent_skills",
        ),
        (
            BASE_METADATA.replace("  consumes: [dataset@1]\n", ""),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "missing_consumes",
        ),
        (
            BASE_METADATA.replace("  produces: [model@1]\n", ""),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "missing_produces",
        ),
        (
            BASE_METADATA.replace("  entrypoints: [scripts/run.py]\n", ""),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "missing_entrypoints",
        ),
        (
            BASE_METADATA.replace("stable", "experimental"),
            "Use when a validated dataset needs model training.",
            True,
            {"sample"},
            "invalid_maturity",
        ),
    ],
)
def test_contract_failures_have_distinct_error_codes(
    tmp_path: Path,
    metadata: str,
    description: str,
    entrypoint: bool,
    known: set[str],
    error_code: str,
) -> None:
    skill_dir = _write_skill(
        tmp_path / "sample",
        metadata=metadata,
        description=description,
        create_entrypoint=entrypoint,
    )

    report = validate_skill_contract(load_skill_contract(skill_dir), known)

    assert error_code in [issue.code for issue in report.errors]
