from pathlib import Path

from tests.architecture.import_boundaries import ImportRef, find_forbidden_imports


ROOT = Path(__file__).parents[2]


def test_forbidden_imports_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "src" / "genkai"
    source.mkdir(parents=True)
    (source / "bad.py").write_text(
        "from paperread.surface.core import common\n"
        "import agents.Agent.skills.mace.scripts\n",
        encoding="utf-8",
    )

    violations = find_forbidden_imports(source, set())

    assert ImportRef("bad.py", "paperread.surface.core", "common") in violations
    assert (
        ImportRef("bad.py", "agents.Agent.skills.mace.scripts", None)
        in violations
    )


def test_exact_allowlist_removes_only_the_named_import(tmp_path: Path) -> None:
    source = tmp_path / "src" / "genkai"
    source.mkdir(parents=True)
    (source / "legacy.py").write_text(
        "from paperread.surface.modeling.ptomodel import "
        "build_ptomodel_payload, generate_ptomodel_output\n",
        encoding="utf-8",
    )
    allowed = {
        ImportRef(
            "legacy.py",
            "paperread.surface.modeling.ptomodel",
            "build_ptomodel_payload",
        )
    }

    violations = find_forbidden_imports(source, allowed)

    assert violations == {
        ImportRef(
            "legacy.py",
            "paperread.surface.modeling.ptomodel",
            "generate_ptomodel_output",
        )
    }


def test_genkai_reverse_imports_match_task12_allowlist() -> None:
    allowed = {
        ImportRef(
            "modeling/ptomodel.py",
            "paperread.surface.modeling.job_bundle",
            "build_modeling_checklist",
        ),
        ImportRef(
            "modeling/ptomodel.py",
            "paperread.surface.modeling.ptomodel",
            "build_ptomodel_payload",
        ),
    }

    assert find_forbidden_imports(ROOT / "src" / "genkai", allowed) == set()


def test_legacy_surface_literature_paths_are_absent() -> None:
    for relative in (
        "paperread/surface/core",
        "paperread/surface/extraction",
        "paperread/surface/experience",
        "paperread/surface/pipeline",
        "paperread/surface/cli.py",
        "paperread/surface/__main__.py",
        "paperread/surface/__init__.py",
    ):
        assert not (ROOT / relative).exists(), relative
