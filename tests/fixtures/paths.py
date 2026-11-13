"""Stable paths for deterministic and archived test fixtures."""

from pathlib import Path

FIXTURES_ROOT = Path(__file__).resolve().parent
ARCHIVES_ROOT = FIXTURES_ROOT / "archives"


def fixture_path(*parts: str) -> Path:
    return FIXTURES_ROOT.joinpath(*parts)


def archive_path(*parts: str) -> Path:
    return ARCHIVES_ROOT.joinpath(*parts)
