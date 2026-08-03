from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[2]
SCRIPTS = ROOT / "agents" / "Agent" / "skills" / "paperread" / "scripts"


@pytest.mark.parametrize(
    "script_name",
    (
        "paperread_tools.py",
        "export_surface_experience.py",
        "build_surface_parameter_registry.py",
    ),
)
def test_paperread_skill_entrypoint_help_uses_current_library(
    script_name: str,
) -> None:
    env = os.environ.copy()
    env.pop("LLM_API_KEY", None)
    env.pop("OPENAI_API_KEY", None)

    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script_name), "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()


def test_paperread_skill_initializes_experience_under_current_layout(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "paperread_tools.py"),
            "init-material-classes",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    material_classes = (
        tmp_path
        / "src/genkai/literature/surface/experience/material_classes"
    )
    assert len(list(material_classes.glob("*.json"))) == 20
    assert not (tmp_path / "paperread/surface/experience").exists()
