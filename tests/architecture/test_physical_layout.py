from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_legacy_research_assets_have_an_archive_owner() -> None:
    assert (ROOT / "legacy" / "paperread" / "NERRE").is_dir()
    assert (ROOT / "legacy" / "paperread" / "ReactionSeek").is_dir()


def test_active_source_has_no_legacy_paperread_package() -> None:
    assert not (ROOT / "paperread").exists()
    assert not (ROOT / "paperread" / "NERRE").exists()
    assert not (ROOT / "paperread" / "ReactionSeek").exists()
