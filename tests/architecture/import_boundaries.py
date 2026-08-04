"""AST helpers for enforcing Genkai source dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple


class ImportRef(NamedTuple):
    relative_file: str
    module: str
    name: str | None


_SURFACE_HEAVY_ROOTS = {
    "ase",
    "numpy",
    "pandas",
    "scipy",
    "optuna",
    "torch",
    "fairchem",
    "pymatgen",
    "mp_api",
}


def find_skill_heavy_imports(skill_root: Path) -> set[ImportRef]:
    violations: set[ImportRef] = set()
    for path in skill_root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(skill_root).as_posix()
        has_genkai_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for module in names:
                root = module.split(".", 1)[0]
                if root == "genkai":
                    has_genkai_import = True
                if root in _SURFACE_HEAVY_ROOTS:
                    violations.add(ImportRef(relative, module, None))
        if not has_genkai_import:
            violations.add(ImportRef(relative, "missing-genkai-wrapper", None))
    return violations


def _forbidden(module: str) -> bool:
    return module == "paperread" or module.startswith("paperread.") or (
        module == "agents.Agent.skills"
        or module.startswith("agents.Agent.skills.")
    )


def find_forbidden_imports(
    source_root: Path,
    allowlist: set[ImportRef],
) -> set[ImportRef]:
    found: set[ImportRef] = set()
    for path in source_root.rglob("*.py"):
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        relative = path.relative_to(source_root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _forbidden(alias.name):
                        found.add(ImportRef(relative, alias.name, None))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module
                and _forbidden(node.module)
            ):
                for alias in node.names:
                    found.add(ImportRef(relative, node.module, alias.name))
    return found - allowlist
