from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[2]
SCRIPT = (
    ROOT
    / "agents"
    / "Agent"
    / "skills"
    / "ptomodel"
    / "scripts"
    / "ptomodel_tools.py"
)


def test_ptomodel_skill_help_uses_public_genkai_api() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()


def test_ptomodel_skill_builds_minimal_plan_offline(tmp_path: Path) -> None:
    relations = tmp_path / "sample_surface_relations.jsonl"
    relations.write_text(
        json.dumps(
            {
                "id": "ceria-oh",
                "extraction": {
                    "materials": ["CeO2"],
                    "surfaces": ["CeO2(111)"],
                    "facets": ["(111)"],
                    "adsorbates": ["OH"],
                    "modeling_keywords": ["adsorbate"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "build",
            "--relations",
            str(relations),
            "--output-dir",
            str(tmp_path),
            "--stem",
            "sample",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads((tmp_path / "sample_ptomodel.json").read_text())
    assert payload["schema_version"] == "1.0"
    assert len(payload["documents"]) == 1
    assert payload["surface_modeling_parameter_schema"]["tasks"]
