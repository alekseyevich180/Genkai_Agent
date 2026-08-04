"""External compute adapter boundaries."""

from .vasp import collect_vasp_results, prepare_vasp_inputs

__all__ = ["collect_vasp_results", "prepare_vasp_inputs"]
