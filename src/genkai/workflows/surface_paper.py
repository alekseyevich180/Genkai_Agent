"""Workflow-level orchestration for surface-paper extraction runs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from genkai.literature.surface.pipeline.runner import (
    run_literature_pipeline,
    run_literature_pipeline_from_pdf,
)
from genkai.workflow.store import load_manifest
from genkai.workflows.paper_to_mlip import (
    ModelingMode,
    _validate_modeling_request,
    initialize_paper_to_mlip_run,
)

if TYPE_CHECKING:
    from genkai.modeling.surface.executor import SurfaceExecutionOverrides


InputFormat = Literal["auto", "json", "pdf"]


def initialize_surface_paper_run(
    input_source: str | Path,
    run_root: str | Path,
    *,
    input_format: InputFormat = "auto",
    model: str | None = None,
    save_raw: bool = False,
    collect_experience_output: bool = False,
    modeling_mode: ModelingMode = "prepare",
    modeling_overrides: SurfaceExecutionOverrides | None = None,
) -> dict[str, str]:
    _validate_modeling_request(modeling_mode, modeling_overrides)
    source = Path(input_source)
    root = Path(run_root)
    selected_format = input_format
    if selected_format == "auto":
        selected_format = "pdf" if source.suffix.lower() == ".pdf" else "json"

    if selected_format == "pdf":
        outputs = run_literature_pipeline_from_pdf(
            str(source),
            str(root),
            model=model,
            save_raw=save_raw,
            collect_experience_output=collect_experience_output,
        )
    else:
        outputs = run_literature_pipeline(
            str(source),
            str(root),
            model=model,
            save_raw=save_raw,
            collect_experience_output=collect_experience_output,
        )

    relations = outputs.get("relations_jsonl")
    if not relations:
        raise ValueError("surface workflow requires relation extraction")
    initialize_paper_to_mlip_run(
        root, Path(relations), conditions_csv=outputs.get("conditions_csv"),
        modeling_mode=modeling_mode, modeling_overrides=modeling_overrides,
    )
    if modeling_mode == "structure-only":
        manifest = load_manifest(root)
        structures = next(
            item for item in reversed(manifest.artifacts)
            if item.artifact_type == "structure-set"
        )
        outputs = {
            **outputs,
            "structures_extxyz": str(root / structures.path),
            "execution_report": str(root / structures.metadata["execution_report"]),
        }
    return {**outputs, "manifest": str(root / "manifest.json")}
