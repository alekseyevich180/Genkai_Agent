"""Compatibility path: this module moved to ``genkai.modeling.surface.builders.substrate``.

``import genkai.modeling.surface.substrate`` returns the moved module itself (one module object,
so attributes and monkeypatches are shared). New code imports the new path.
"""

import sys
from importlib import import_module

_module = import_module("genkai.modeling.surface.builders.substrate")
sys.modules[__name__] = _module
