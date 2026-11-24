"""Compatibility path: this module moved to ``genkai.modeling.surface.mlip.mlip_config``.

``import genkai.modeling.surface.mlip_config`` returns the moved module itself (one module object,
so attributes and monkeypatches are shared),
and ``python -m genkai.modeling.surface.mlip_config`` runs its ``main``. New code imports the new path.
"""

import sys
from importlib import import_module

_module = import_module("genkai.modeling.surface.mlip.mlip_config")

if __name__ == "__main__":
    raise SystemExit(_module.main())
sys.modules[__name__] = _module
