from genkai.modeling.surface import materials_project_slab as _impl
from genkai.modeling.surface.materials_project_slab import *
from genkai.modeling.surface.materials_project_slab import _select_bulk_document
from genkai.modeling.surface.materials_project_slab import main as _main


def download_stable_surface(*args, **kwargs):
    """Compatibility shim preserving monkeypatching on the legacy Skill path."""
    original = _impl.fetch_bulk_structure
    _impl.fetch_bulk_structure = fetch_bulk_structure
    try:
        return _impl.download_stable_surface(*args, **kwargs)
    finally:
        _impl.fetch_bulk_structure = original


if __name__ == "__main__":
    raise SystemExit(_main())
