"""End-user setup and task execution; no MLIP installation or model evaluation."""

import io
import json
import importlib.metadata
from pathlib import Path
import subprocess
import sys

import pytest
import yaml
from ase.build import bulk
from ase.io import write

from genkai.modeling.surface import jobs, setup
from genkai.modeling.surface.mlip_config import load_config

ROOT = Path(__file__).resolve().parents[2]


def _setup_args(path, *extra):
    parser = setup.argparse.ArgumentParser()
    setup.add_setup_arguments(parser)
    return parser.parse_args(["--config", str(path), "--non-interactive", *extra])


def test_setup_without_mlip_writes_a_useful_template_and_preserves_it(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "discover_profiles", lambda: {})
    path = tmp_path / "genkai.yaml"
    setup.configure(_setup_args(path))
    assert load_config(path).profiles == {}
    assert "python: /path/to/mace/env/bin/python" in path.read_text()
    original = path.read_bytes()
    setup.configure(_setup_args(path))
    assert path.read_bytes() == original
    setup.write_tasks(ROOT, path)
    task = tmp_path / "tasks/sam_search.yaml"
    task.write_text("custom user task\n")
    setup.write_tasks(ROOT, path)
    assert task.read_text() == "custom user task\n"


def test_preparing_a_runtime_installs_only_project_dependencies(tmp_path, monkeypatch):
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"default": "emt", "profiles": {"emt": {"python": sys.executable}}}))
    profile = load_config(config).select()
    commands = []

    def record(command, **kwargs):
        commands.append(command)
        profile.prepared_python.parent.mkdir(parents=True, exist_ok=True)
        profile.prepared_python.touch()

    monkeypatch.setattr(setup, "_run", record)
    monkeypatch.setattr(setup, "inherit_site_packages", lambda *a: None)
    monkeypatch.setattr(setup, "source_constraints", lambda *a: tmp_path / "constraints.txt")
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0))
    setup.prepare_runtime(profile, ROOT, _setup_args(config, "--installer", "uv"))
    assert "--system-site-packages" in commands[0]
    assert commands[1][-2:] == ["-e", str(ROOT)]
    assert "--constraint" in commands[1]
    for command in commands:
        assert not any(value in {"torch", "mace-torch", "fairchem-core"} or "[mlip" in value or "[mace" in value for value in command)
    assert profile.runtime_python() == profile.prepared_python


def test_runtime_constraints_preserve_source_versions_without_pinning_genkai(tmp_path):
    from genkai.modeling.surface.mlip_config import MlipProfile

    profile = MlipProfile("test", "emt", Path(sys.executable), None, tmp_path / "genkai.yaml")
    profile.runtime_dir.mkdir(parents=True)
    constraints = setup.source_constraints(profile, dict(__import__("os").environ)).read_text()
    assert f"numpy=={importlib.metadata.version('numpy')}\n" in constraints
    assert not any(line.lower().startswith("genkai==") for line in constraints.splitlines())


def test_nested_venv_inherits_editable_backend_without_installation(tmp_path):
    from genkai.modeling.surface.mlip_config import MlipProfile

    source_dir = tmp_path / "source"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(source_dir)], check=True)
    source_python = source_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    editable = tmp_path / "editable_backend"
    editable.mkdir()
    (editable / "genkai_test_backend.py").write_text("value = 'inherited without installing'\n")
    query_site = "import site; print(site.getsitepackages()[0])"
    source_site = Path(subprocess.check_output([str(source_python), "-c", query_site], text=True).strip())
    (source_site / "editable_backend.pth").write_text(str(editable) + "\n")
    profile = MlipProfile("test", "emt", source_python, None, tmp_path / "genkai.yaml")
    subprocess.run([str(source_python), "-m", "venv", "--without-pip", "--system-site-packages", str(profile.runtime_dir)], check=True)
    setup.inherit_site_packages(profile, dict(__import__("os").environ))
    setup.inherit_site_packages(profile, dict(__import__("os").environ))  # rerunning setup must retain it
    result = subprocess.check_output([
        str(profile.prepared_python), "-c", "import genkai_test_backend; print(genkai_test_backend.value)",
    ], text=True)
    assert result.strip() == "inherited without installing"


def test_installer_dry_run_never_installs_a_backend(tmp_path):
    completed = subprocess.run([
        "bash", str(ROOT / "install.sh"), "--dry-run", "--non-interactive", "--installer", "pip",
        "--python", sys.executable, "--venv", str(tmp_path / "venv"), "--mlip",
        "--mace-python", sys.executable, "--mace-model", str(tmp_path / "model.model"),
    ], text=True, capture_output=True, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    commands = [line for line in completed.stderr.splitlines() if line.startswith("+")]
    assert any("genkai.modeling.surface.setup" in line for line in commands)
    assert not any("install torch" in line or "[test,mlip]" in line or "[mace]" in line for line in commands)
    assert not (tmp_path / "venv").exists()


def test_unified_yaml_runs_in_the_selected_environment_and_records_empirical_evidence(tmp_path, capsys):
    # EMT supplies a genuine offline ASE result, explicitly marked empirical, not MLIP.
    crystal = tmp_path / "Cu.cif"
    write(crystal, bulk("Cu", "fcc", a=3.61, cubic=True))
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "test_emt", "profiles": {
        "test_emt": {"backend": "emt", "python": sys.executable, "device": "cpu"},
    }}))
    task = tmp_path / "job.yaml"
    task.write_text("method: slab\nmlip: default\nbulk: Cu.cif\nfacet: '111'\nmin_slab_size: 5\nmin_lateral_size: 4\n")
    assert jobs.main(["check", str(task)]) == 0
    assert jobs.main(["run", "--quiet", str(task)]) == 0
    manifest = json.loads((tmp_path / "runs/job/manifest.json").read_text())
    assert manifest["metadata"]["energies_available"] is True
    assert manifest["metadata"]["calculator"] == "emt"
    assert manifest["metadata"]["mlip"]["profile"] == "test_emt"
    assert manifest["artifacts"][0]["evidence_level"] == "empirical_potential"
    assert manifest["stages"][0]["metadata"]["command"][0] == sys.executable
    assert "没有计算能量" not in capsys.readouterr().out


def test_missing_runtime_is_reported_before_creating_output(tmp_path):
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"default": "test", "profiles": {
        "test": {"backend": "emt", "python": str(tmp_path / "absent-python")},
    }}))
    task = tmp_path / "job.yaml"
    task.write_text("method: slab\nmlip: default\nbulk: existing.cif\nfacet: '111'\n")
    (tmp_path / "existing.cif").touch()
    out = io.StringIO()
    assert jobs.command_check([task], out) == 2
    assert "Python 不存在" in out.getvalue()
    [job] = jobs.load_job_file(task)
    assert jobs.run_job(job).status == "FAIL"
    assert not job.output.exists()
