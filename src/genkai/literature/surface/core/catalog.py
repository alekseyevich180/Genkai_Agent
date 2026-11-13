from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SurfaceToolSpec:
    name: str
    category: str
    module: str
    function: str
    purpose: str


SURFACE_TOOL_SPECS: list[SurfaceToolSpec] = [
    SurfaceToolSpec(
        name="ingest_pdf",
        category="ingestion",
        module="genkai.literature.surface.extraction.ingest_pdf",
        function="ingest_pdf",
        purpose="Convert PDF text into section JSON and routed condition/relation inputs.",
    ),
    SurfaceToolSpec(
        name="extract_surface_conditions",
        category="extraction",
        module="genkai.literature.surface.extraction.extract_surface_conditions",
        function="extract_conditions",
        purpose="Extract paper conditions into a structured surface table.",
    ),
    SurfaceToolSpec(
        name="extract_surface_relations",
        category="extraction",
        module="genkai.literature.surface.extraction.extract_surface_relations",
        function="extract_relations",
        purpose="Extract materials, surfaces, sites, and reaction relations into JSONL.",
    ),
    SurfaceToolSpec(
        name="standardize_surface_time",
        category="normalization",
        module="genkai.literature.surface.extraction.standardize_surface_time",
        function="standardize_time",
        purpose="Normalize reaction and treatment times into a standardized table.",
    ),
    SurfaceToolSpec(
        name="ptomodel",
        category="planning",
        module="genkai.modeling.ptomodel",
        function="build_modeling_plan",
        purpose="Bridge extracted surface information into modeling-task inputs.",
    ),
    SurfaceToolSpec(
        name="run_surface_pipeline",
        category="workflow",
        module="genkai.workflows.surface_paper",
        function="initialize_surface_paper_run",
        purpose="Run literature extraction and initialize an artifact workflow.",
    ),
    SurfaceToolSpec(
        name="collect_experience",
        category="experience",
        module="genkai.literature.surface.experience.collect_experience",
        function="collect_experience",
        purpose="Aggregate known-useful and unknown terms into reusable material-class experience.",
    ),
    SurfaceToolSpec(
        name="build_surface_parameter_registry",
        category="registry",
        module="genkai.literature.surface.experience.parameter_registry",
        function="build_surface_parameter_registry",
        purpose="Rebuild the reusable parameter vocabulary from canonical material-class store.",
    ),
    SurfaceToolSpec(
        name="summarize_surface_outputs",
        category="reporting",
        module="genkai.literature.surface.extraction.summarize_surface_outputs",
        function="write_summary",
        purpose="Write a human-readable summary of conditions and relations.",
    ),
]


SURFACE_TOOL_CATEGORIES = [
    "ingestion",
    "extraction",
    "normalization",
    "planning",
    "workflow",
    "experience",
    "registry",
    "reporting",
]


def list_surface_tools(category: str | None = None) -> list[SurfaceToolSpec]:
    if not category:
        return list(SURFACE_TOOL_SPECS)
    normalized = category.strip().casefold()
    return [spec for spec in SURFACE_TOOL_SPECS if spec.category.casefold() == normalized]


def render_surface_tool_catalog(category: str | None = None) -> str:
    specs = list_surface_tools(category)
    lines = ["Surface tooling catalog", ""]
    for group in SURFACE_TOOL_CATEGORIES:
        grouped = [spec for spec in specs if spec.category == group]
        if not grouped:
            continue
        lines.append(f"## {group}")
        lines.append("")
        for spec in grouped:
            lines.append(f"- {spec.name}: {spec.purpose}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
