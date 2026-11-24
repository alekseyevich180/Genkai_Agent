"""Configuration contracts; no MLIP weights are imported or evaluated."""

import json
import os
from pathlib import Path
import sys

import pytest
import yaml

from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.mlip.mlip_config import MlipConfigError, find_config, load_config, probe_profile

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_file(tmp_path):
    (tmp_path / "mace.model").touch()
    path = tmp_path / "genkai.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1, "default": "mace_gpu", "profiles": {
            "mace_gpu": {"backend": "mace", "python": sys.executable, "model": "mace.model", "device": "cpu", "dtype": "float64"},
            "uma": {"backend": "uma", "python": sys.executable, "model": "uma-s-1p2", "task": "omat", "device": "cpu"},
        },
    }), encoding="utf-8")
    return path


def test_config_resolves_paths_and_defaults(config_file):
    config = load_config(config_file)
    profile = config.select()
    assert profile.name == "mace_gpu"
    assert profile.model == str(config_file.parent / "mace.model")
    assert profile.python == Path(sys.executable).absolute()
    assert profile.calculator_args() == ["--calculator=mace", "--device=cpu", f"--mace-model={profile.model}", "--mace-dtype=float64"]
    assert "--uma_model=uma-s-1p2" in config.select("uma").calculator_args(style="underscore")


def test_interpreter_symlinks_preserve_the_virtual_environment(config_file, tmp_path):
    executable = tmp_path / "venv/bin/python"
    executable.parent.mkdir(parents=True)
    executable.symlink_to(sys.executable)
    data = yaml.safe_load(config_file.read_text())
    data["profiles"]["mace_gpu"]["python"] = "venv/bin/python"
    config_file.write_text(yaml.safe_dump(data))
    profile = load_config(config_file).select()
    assert profile.python == executable
    assert profile.python != executable.resolve()


@pytest.mark.parametrize("key,value,message", [
    ("device", "gpu", "device"), ("dtype", "float16", "dtype"),
    ("backend", "misspelled", "backend"), ("pyton", "python", "未知"),
    ("backend", ["mace"], "backend"),
    ("settings", {"max_steps": -1}, "max_steps"),
    ("settings", {"fmax": float("nan")}, "fmax"),
    ("launcher", "bash start.sh", "launcher"),
])
def test_invalid_config_reports_the_field(config_file, key, value, message):
    data = yaml.safe_load(config_file.read_text())
    data["profiles"]["mace_gpu"][key] = value
    config_file.write_text(yaml.safe_dump(data))
    with pytest.raises(MlipConfigError, match=message):
        load_config(config_file)


def test_config_discovery_and_explicit_override(config_file, tmp_path, monkeypatch):
    monkeypatch.delenv("GENKAI_CONFIG", raising=False)
    task = tmp_path / "tasks/job.yaml"
    assert find_config(task) == config_file
    override = tmp_path / "other.yaml"
    override.write_text(config_file.read_text())
    monkeypatch.setenv("GENKAI_CONFIG", str(config_file))
    assert find_config(task, override) == override


def test_profile_does_not_export_environment_values_into_provenance(config_file):
    data = yaml.safe_load(config_file.read_text())
    data["profiles"]["mace_gpu"]["env"] = {"HF_TOKEN": "not-a-real-token"}
    config_file.write_text(yaml.safe_dump(data))
    settings = load_config(config_file).select().public_settings()
    assert "not-a-real-token" not in json.dumps(settings)
    assert "HF_TOKEN" not in json.dumps(settings)


def test_probe_checks_availability_without_importing_the_backend(config_file, tmp_path):
    # find_spec must see the backend without importing its code or loading a model.
    (tmp_path / "mace.py").write_text("raise RuntimeError('a probe must never import this backend')\n")
    result = probe_profile(load_config(config_file).select(), tmp_path)
    assert result["missing"] == []
    assert result["python"]


def test_missing_model_fails_before_starting_a_worker(config_file, tmp_path):
    (tmp_path / "mace.model").unlink()
    with pytest.raises(MlipConfigError, match="模型不存在"):
        probe_profile(load_config(config_file).select(), tmp_path)


@pytest.mark.parametrize("message,retry", [("torch.OutOfMemoryError: CUDA out of memory.", True), ("ValueError: invalid geometry", False)])
def test_uma_cuda_oom_restarts_job_with_configured_fallback(config_file, tmp_path, monkeypatch, message, retry):
    data = yaml.safe_load(config_file.read_text())
    medium = data["profiles"]["uma"]
    medium.update(model="uma-m-1p1", device="cuda", oom_fallback="small")
    data["profiles"]["small"] = {**medium, "model": "uma-s-1p1"}
    del data["profiles"]["small"]["oom_fallback"]
    config_file.write_text(yaml.safe_dump(data))
    source = tmp_path / "job.yaml"
    source.write_text(yaml.safe_dump({"method": "amorphous_surfaces", "mlip": "uma",
                                    "amorphous": str(ROOT / "tests/amorphous/TiO2.vasp"), "output": "result"}))
    job, = jobs.load_job_file(source)
    attempts = []

    class Worker:
        def __init__(self, command, cwd, **kwargs):
            attempts.append(command)
            self.stdout = [message + "\n"] if len(attempts) == 1 else ["success\n"]
            self.exit_code = 1 if len(attempts) == 1 else 0
            if self.exit_code:
                (cwd / "partial.extxyz").touch()
            else:
                assert not (cwd / "partial.extxyz").exists()

        def wait(self):
            return self.exit_code

    monkeypatch.setattr(jobs, "probe_profile", lambda *args: {})
    monkeypatch.setattr(jobs.subprocess, "Popen", Worker)
    monkeypatch.setattr(jobs, "_check_outputs", lambda *args, **kwargs: ("PASS", [], [], []))
    result = jobs.run_job(job, quiet=True)
    assert "--uma-model=uma-m-1p1" in attempts[0]
    if retry:
        assert result.status == "PASS" and len(attempts) == 2
        assert "--uma-model=uma-s-1p1" in attempts[1]
        manifest = json.loads(result.manifest.read_text())
        assert manifest["metadata"]["mlip"]["model"] == "uma-s-1p1"
        assert manifest["metadata"]["oom_fallback"]["requested_model"] == "uma-m-1p1"
        old_log = Path(manifest["metadata"]["oom_fallback"]["first_log"])
        assert message in old_log.read_text() and (old_log.parent / "partial.extxyz").exists()
    else:
        assert result.status == "FAIL" and len(attempts) == 1


@pytest.mark.parametrize("method", ["slab", "vacancy", "adsorbate", "sam_search", "amorphous_surfaces", "amorphous_interface", "cluster_search"])
def test_one_profile_switch_updates_every_energy_entrypoint(config_file, tmp_path, method):
    from genkai.modeling.surface.app.setup import write_tasks

    write_tasks(ROOT, config_file)
    source = tmp_path / "tasks" / f"{method}.yaml"
    document = yaml.safe_load(source.read_text())
    document["mlip"] = "mace_gpu"
    source.write_text(yaml.safe_dump(document))
    [mace] = jobs.load_job_file(source)
    mace_args = jobs.build_argv(mace)
    assert f"{mace.method.calculator_flag}=mace" in mace_args
    assert "--mace-dtype=float64" in mace_args
    if method in {"slab", "vacancy", "adsorbate"}:
        assert "--calculator=none" not in mace_args
        assert "--max-steps=0" not in mace_args
    document["mlip"] = "uma"
    source.write_text(yaml.safe_dump(document))
    [uma] = jobs.load_job_file(source)
    uma_args = jobs.build_argv(uma)
    assert f"{uma.method.calculator_flag}=uma" in uma_args
    assert not any(arg.startswith("--mace-") for arg in uma_args)
    assert uma.profile.command()[0] == sys.executable


def test_task_numeric_settings_override_profile_defaults(config_file, tmp_path):
    task = tmp_path / "job.yaml"
    task.write_text(f"method: vacancy\ninput: input.cif\nmlip: mace_gpu\nmax_steps: 7\nfmax: 0.1\n")
    [job] = jobs.load_job_file(task, config_path=config_file)
    args = jobs.build_argv(job)
    assert args.count("--max-steps=7") == 1
    assert "--max-steps=200" not in args and "--max-steps=0" not in args
    assert args.count("--fmax=0.1") == 1


@pytest.mark.parametrize("method", ["adsorbate", "sam_search", "amorphous_interface", "cluster_search"])
def test_search_sampler_default_and_override(config_file, tmp_path, method):
    from genkai.modeling.surface.app.setup import write_tasks

    write_tasks(ROOT, config_file)
    source = tmp_path / "tasks" / f"{method}.yaml"
    document = yaml.safe_load(source.read_text())
    document.pop("sampler", None)
    source.write_text(yaml.safe_dump(document))
    [job] = jobs.load_job_file(source)
    assert job.values["sampler"] == "periodic_gp"
    assert "--sampler=periodic_gp" in jobs.build_argv(job)

    document["sampler"] = "tpe"
    source.write_text(yaml.safe_dump(document))
    [job] = jobs.load_job_file(source)
    assert job.values["sampler"] == "tpe"
    assert "--sampler=tpe" in jobs.build_argv(job)


def test_bool_task_flags_and_invalid_profile_are_actionable(config_file, tmp_path):
    task = tmp_path / "job.yaml"
    task.write_text("method: amorphous_surfaces\namorphous: bulk.vasp\nmlip: mace_gpu\nno_cell_relax: false\nfix_bottom: true\n")
    [job] = jobs.load_job_file(task)
    assert "--fix-bottom" in jobs.build_argv(job)
    assert "--no-cell-relax" not in jobs.build_argv(job)
    task.write_text(task.read_text().replace("mace_gpu", "typo"))
    with pytest.raises(jobs.JobFileError, match="可用"):
        jobs.load_job_file(task)
