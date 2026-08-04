import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from google.adk.skills import load_skill_from_dir


ROOT = Path(__file__).parents[2]


def test_wheel_contains_every_tracked_skill_and_nested_asset(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(dist),
            str(ROOT),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    wheel = next(dist.glob("genkai-*.whl"))
    extracted = tmp_path / "wheel"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(extracted)

    source_skills = {
        path.relative_to(ROOT / "agents" / "Agent" / "skills")
        for path in (ROOT / "agents" / "Agent" / "skills").rglob("SKILL.md")
    }
    wheel_root = extracted / "agents" / "Agent" / "skills"
    wheel_skills = {
        path.relative_to(wheel_root)
        for path in wheel_root.rglob("SKILL.md")
    }
    assert wheel_skills == source_skills
    assert (
        wheel_root
        / "uma"
        / "assets"
        / "fairchem-core-2.21.0"
        / "configs"
        / "uma"
        / "finetune"
        / "uma_sm_finetune_template.yaml"
    ).is_file()
    for skill_file in sorted(wheel_root.rglob("SKILL.md")):
        assert load_skill_from_dir(skill_file.parent).name

    source_material_classes = {
        path.name
        for path in (
            ROOT
            / "src"
            / "genkai"
            / "literature"
            / "surface"
            / "experience"
            / "material_classes"
        ).glob("*.json")
    }
    wheel_material_classes = {
        path.name
        for path in (
            extracted
            / "genkai"
            / "literature"
            / "surface"
            / "experience"
            / "material_classes"
        ).glob("*.json")
    }
    assert len(source_material_classes) == 20
    assert wheel_material_classes == source_material_classes
    for name in wheel_material_classes:
        assert (
            extracted
            / "genkai"
            / "literature"
            / "surface"
            / "experience"
            / "material_classes"
            / name
        ).read_text(encoding="utf-8").strip()

    source_task_schema = (
        ROOT
        / "src"
        / "genkai"
        / "modeling"
        / "schema"
        / "task_parameter_schema.json"
    )
    wheel_task_schema = (
        extracted
        / "genkai"
        / "modeling"
        / "schema"
        / "task_parameter_schema.json"
    )
    assert wheel_task_schema.read_bytes() == source_task_schema.read_bytes()
    assert set(json.loads(wheel_task_schema.read_text())["tasks"]) == {
        "vacancy_landscape",
        "adsorbate_landscape",
        "surface_cluster_builder",
        "surface_cluster_mlip_search",
    }

    environment = {**os.environ, "PYTHONPATH": str(extracted)}
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("LLM_API_KEY", None)
    schema_load = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "import genkai.modeling.ptomodel as module; "
                "registry = module._load_surface_modeling_parameter_schema(); "
                "print(json.dumps({'module': module.__file__, "
                "'schema_path': registry['schema_path'], "
                "'tasks': sorted(registry['tasks'])}))"
            ),
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert schema_load.returncode == 0, schema_load.stderr
    loaded_schema = json.loads(schema_load.stdout)
    assert Path(loaded_schema["module"]).is_relative_to(extracted)
    assert loaded_schema["schema_path"] == (
        "genkai.modeling.schema:task_parameter_schema.json"
    )
    assert loaded_schema["tasks"] == [
        "adsorbate_landscape",
        "surface_cluster_builder",
        "surface_cluster_mlip_search",
        "vacancy_landscape",
    ]
    for module in ("genkai.cli", "agent.init.start_agent"):
        help_result = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            cwd=tmp_path,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stderr
        assert "help" in help_result.stdout.lower()
    surface_help = subprocess.run(
        [sys.executable, "-m", "genkai.cli", "surface", "--help"],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert surface_help.returncode == 0, surface_help.stderr
    assert "list-tools" in surface_help.stdout
