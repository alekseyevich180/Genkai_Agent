import ast
from pathlib import Path


ROOT = Path(__file__).parents[2]


def test_paperread_experience_export_is_a_thin_library_wrapper() -> None:
    path = ROOT / "agents/Agent/skills/paperread/scripts/export_surface_experience.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    implementation_defs = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert implementation_defs <= {"main"}
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("genkai.literature.surface.experience")
        for node in tree.body
    )
