from pathlib import Path


def test_test_tier_markers_are_registered() -> None:
    config = Path("pyproject.toml").read_text(encoding="utf-8")
    for marker in ("unit:", "contract:", "integration:", "compatibility:", "external:"):
        assert marker in config


def test_external_tests_have_a_dedicated_directory() -> None:
    assert Path("tests/external").is_dir()


def test_legacy_characterization_tests_are_compatibility_tests() -> None:
    assert Path("tests/compatibility/test_paperread_surface.py").is_file()
    assert Path("tests/compatibility/test_surface_mp_workflow.py").is_file()
