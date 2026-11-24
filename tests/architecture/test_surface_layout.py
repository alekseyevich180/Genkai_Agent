"""Layout of genkai.modeling.surface: subpackage layering and the old-path forwarders.

structure_io <- mlip <- builders <- screening <- app; executor/facade use builders.
The old flat module paths (genkai.modeling.surface.slab, ...) stay importable as forwarders
for scripts written before the split, but no code in the repository imports them.
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURFACE = ROOT / "src" / "genkai" / "modeling" / "surface"
PKG = "genkai.modeling.surface"

MOVED = {
    "calculators": "mlip", "search_sampler": "mlip", "mlip_config": "mlip",
    "slab": "builders", "materials_project_slab": "builders", "substrate": "builders", "sites": "builders",
    "vacancy": "builders", "adsorbate": "builders", "sam": "builders", "amorphous_overlayer": "builders",
    "amorphous_slab": "builders", "metal_cluster": "builders",
    "sam_search": "screening", "amorphous_screen": "screening", "cluster_search": "screening",
    "jobs": "app", "setup": "app",
}
METAL_CLUSTER_MODULES = ("bcc", "cluster_builder", "fcc", "hcp", "surface_cluster_builder")

# Subpackage -> surface-level names it must not import.
FORBIDDEN = {
    "mlip": {"builders", "screening", "app", "executor", "facade"},
    "builders": {"screening", "app", "executor", "facade"},
    "screening": {"app", "executor", "facade"},
    "app": {"executor", "facade"},
}


def _module_name(path: Path) -> str:
    base = ROOT / "src" if path.is_relative_to(ROOT / "src") else ROOT
    parts = list(path.relative_to(base).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: Path) -> set[str]:
    """Absolute names of every module imported by a file (relative imports resolved)."""
    name = _module_name(path)
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.add(module)
            # "from pkg import submodule" imports the submodule too.
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def _surface_child(module: str) -> str | None:
    """First name below genkai.modeling.surface, e.g. 'builders' for '...surface.builders.sam'."""
    if not module.startswith(PKG + "."):
        return None
    return module[len(PKG) + 1:].split(".", 1)[0]


def _is_forwarder(path: Path) -> bool:
    return path.parent == SURFACE and path.stem in MOVED or path.parent == SURFACE / "metal_cluster"


def _code_files() -> list[Path]:
    return [path for path in SURFACE.rglob("*.py") if not _is_forwarder(path)]


@pytest.mark.parametrize("group", sorted(FORBIDDEN))
def test_subpackages_follow_the_layering(group: str) -> None:
    violations = []
    for path in sorted((SURFACE / group).rglob("*.py")):
        for module in _imports(path):
            if _surface_child(module) in FORBIDDEN[group]:
                violations.append(f"{path.relative_to(ROOT).as_posix()} imports {module}")
    assert not violations, "\n".join(violations)


def test_repository_code_never_imports_the_old_paths() -> None:
    roots = [ROOT / "src", ROOT / "agents", ROOT / "scripts", ROOT / "tests"]
    this_file = Path(__file__).resolve()
    violations = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "fixtures" in path.parts or path.resolve() == this_file or _is_forwarder(path):
                continue
            for module in _imports(path):
                # Imports of genkai.modeling.surface itself expand to "...surface.<name>"; only
                # names that are forwarders count.
                if module.startswith(PKG + ".") and _surface_child(module) in MOVED:
                    violations.append(f"{path.relative_to(ROOT).as_posix()} imports {module}")
    assert not violations, "\n".join(violations)


def test_forwarders_hold_no_code() -> None:
    forwarders = [SURFACE / f"{name}.py" for name in MOVED if name != "metal_cluster"]
    forwarders.append(SURFACE / "metal_cluster" / "__init__.py")
    assert sorted(path for path in SURFACE.glob("*.py") if path.stem in MOVED) == sorted(forwarders[:-1])
    for path in forwarders:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
        assert not defined, f"{path.name} must only forward to the moved module"
    # Every real module lives in a subpackage; only shared and plan-execution modules stay on top.
    top_level = sorted(path.stem for path in SURFACE.glob("*.py") if path.stem not in MOVED)
    assert top_level == ["__init__", "executor", "facade", "structure_io"]
    assert all(path.parent != SURFACE or path.stem in top_level for path in _code_files())


@pytest.mark.parametrize("name", sorted(MOVED))
def test_old_paths_resolve_to_the_moved_modules(name: str) -> None:
    old = importlib.import_module(f"{PKG}.{name}")
    new = importlib.import_module(f"{PKG}.{MOVED[name]}.{name}")
    assert old is new
    assert f"/surface/{MOVED[name]}/" in Path(new.__file__).as_posix()


def test_old_metal_cluster_submodules_resolve_to_the_moved_modules() -> None:
    for name in METAL_CLUSTER_MODULES:
        old = importlib.import_module(f"{PKG}.metal_cluster.{name}")
        assert old is importlib.import_module(f"{PKG}.builders.metal_cluster.{name}")
    from genkai.modeling.surface.metal_cluster import surface_cluster_builder  # noqa: F401 - old style

    assert surface_cluster_builder.__name__ == f"{PKG}.builders.metal_cluster.surface_cluster_builder"


def test_old_module_path_still_runs_as_a_command() -> None:
    # ./genkai launchers generated before the split run "python -m genkai.modeling.surface.jobs".
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), os.environ.get("PYTHONPATH", "")]),
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-m", f"{PKG}.jobs", "methods"],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "slab" in result.stdout
