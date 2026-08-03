"""Stable surface-literature APIs with lazy imports."""

from __future__ import annotations

from importlib import import_module
from typing import Any


_PUBLIC_EXPORTS = {
    "run_surface_extraction": (".artifacts", "run_surface_extraction"),
    "SURFACE_TOOL_CATEGORIES": (".core.catalog", "SURFACE_TOOL_CATEGORIES"),
    "SURFACE_TOOL_SPECS": (".core.catalog", "SURFACE_TOOL_SPECS"),
    "render_surface_tool_catalog": (
        ".core.catalog",
        "render_surface_tool_catalog",
    ),
    "collect_experience": (".experience.collect_experience", "collect_experience"),
    "build_surface_parameter_registry": (
        ".experience.parameter_registry",
        "build_surface_parameter_registry",
    ),
    "load_surface_parameter_registry": (
        ".experience.parameter_registry",
        "load_surface_parameter_registry",
    ),
    "ingest_pdf": (".extraction.ingest_pdf", "ingest_pdf"),
    "ingest_pdf_payloads": (".extraction.ingest_pdf", "ingest_pdf_payloads"),
    "standardize_time": (
        ".extraction.standardize_surface_time",
        "standardize_time",
    ),
    "build_summary_text": (
        ".extraction.summarize_surface_outputs",
        "build_summary_text",
    ),
    "write_summary": (
        ".extraction.summarize_surface_outputs",
        "write_summary",
    ),
}

__all__ = sorted(_PUBLIC_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _PUBLIC_EXPORTS:
        raise AttributeError(name)
    module_name, attribute_name = _PUBLIC_EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
