"""Utility tools for the MatCreator execution agent."""

from __future__ import annotations

import os
from pathlib import Path


def show_plot(plot_path: str) -> dict:
    """Register a generated plot so the UI can display it.

    Call this tool immediately after a plot file has been saved to disk.
    It validates the file exists and returns a structured response that the
    Streamlit UI recognises as a plot result.

    Args:
        plot_path: Absolute (or MATCLAW_WORKSPACE-relative) path to the PNG file.

    Returns:
        dict with ``plot_path`` (resolved absolute path) on success, or an
        ``error`` key if the file cannot be found.
    """
    # Resolve relative paths against MATCLAW_WORKSPACE
    p = Path(plot_path)
    if not p.is_absolute():
        ws_root = os.environ.get("MATCLAW_WORKSPACE") or str(
            Path(__file__).parent / ".workspace"
        )
        p = Path(ws_root) / p

    p = p.resolve()

    if not p.exists():
        return {"error": f"Plot file not found: {p}"}

    if not p.is_file():
        return {"error": f"Path is not a file: {p}"}

    return {"plot_path": str(p)}


def show_structure(structure_path: str) -> dict:
    """Register a generated structure file so the UI can display it.

    Call this tool immediately after a structure file has been saved to disk.
    It validates the file exists and returns a structured response that the
    Streamlit UI recognises as a structure result.

    Args:
        structure_path: Absolute (or MATCLAW_WORKSPACE-relative) path to the
            structure file (e.g. CIF, extXYZ, VASP POSCAR).

    Returns:
        dict with ``structure_path`` (resolved absolute path) on success, or an
        ``error`` key if the file cannot be found.
    """
    p = Path(structure_path)
    if not p.is_absolute():
        ws_root = os.environ.get("MATCLAW_WORKSPACE") or str(
            Path(__file__).parent / ".workspace"
        )
        p = Path(ws_root) / p

    p = p.resolve()

    if not p.exists():
        return {"error": f"Structure file not found: {p}"}

    if not p.is_file():
        return {"error": f"Path is not a file: {p}"}

    return {"structure_path": str(p)}


def show_artifact(artifact_path: str) -> dict:
    """Register an important artifact file so the UI can display and download it.

    Use this tool for files that are neither plots nor structure files, such as
    trained model checkpoints.

    Call this tool immediately after the artifact file has been written to disk.

    Args:
        artifact_path: Absolute (or MATCLAW_WORKSPACE-relative) path to the
            artifact file.

    Returns:
        dict with ``artifact_path`` (resolved absolute path) on success, or an
        ``error`` key if the file cannot be found.
    """
    p = Path(artifact_path)
    if not p.is_absolute():
        ws_root = os.environ.get("MATCLAW_WORKSPACE") or str(
            Path(__file__).parent / ".workspace"
        )
        p = Path(ws_root) / p

    p = p.resolve()

    if not p.exists():
        return {"error": f"Artifact file not found: {p}"}

    if not p.is_file():
        return {"error": f"Path is not a file: {p}"}

    return {"artifact_path": str(p)}
