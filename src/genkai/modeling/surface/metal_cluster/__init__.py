"""Compatibility path: this package moved to ``genkai.modeling.surface.builders.metal_cluster``.

Importing this package or one of its submodules (``...metal_cluster.fcc`` and so on) returns the
moved modules themselves. New code imports the new path.
"""

import sys
from importlib import import_module

_NEW = "genkai.modeling.surface.builders.metal_cluster"
for _name in ("bcc", "cluster_builder", "fcc", "hcp", "surface_cluster_builder"):
    sys.modules[f"{__name__}.{_name}"] = import_module(f"{_NEW}.{_name}")
sys.modules[__name__] = import_module(_NEW)
