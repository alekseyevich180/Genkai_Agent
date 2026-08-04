"""Compatibility wrapper for the Genkai experience export CLI."""

from genkai.literature.surface.experience.export_unknown_terms import *
from genkai.literature.surface.experience.export_unknown_terms import main as _main


if __name__ == "__main__":
    raise SystemExit(_main())
