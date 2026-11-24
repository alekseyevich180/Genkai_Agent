"""Stable surface-modeling algorithm ownership.

Layout (dependencies point left: structure_io <- mlip <- builders <- screening <- app)::

    structure_io.py   file conventions and structure checks, shared by everything
    mlip/             calculators, search_sampler, mlip_config
    builders/         slab, materials_project_slab, substrate, sites, vacancy, adsorbate, sam,
                      amorphous_overlayer, amorphous_slab, metal_cluster/
    screening/        sam_search, amorphous_screen, cluster_search
    app/              jobs (genkai-surface), setup (install wizard)
    executor.py       PToModel plan -> structures (uses builders); facade.py prepares commands

The module files directly in this package with the old names (``slab.py``, ``jobs.py``,
``metal_cluster/`` and so on) are compatibility forwarders to the modules above; they hold no
code. ``tests/architecture/test_surface_layout.py`` checks the layering and the forwarders.
"""

from .executor import (
    SurfaceExecutionBlocked,
    SurfaceExecutionOverrides,
    execute_surface_plan,
    resolve_surface_execution,
)
from .facade import build_surface_candidates

__all__ = [
    "SurfaceExecutionBlocked",
    "SurfaceExecutionOverrides",
    "adsorbate",
    "build_surface_candidates",
    "execute_surface_plan",
    "resolve_surface_execution",
    "cluster_search",
    "materials_project_slab",
    "vacancy",
]
