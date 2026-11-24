"""User-owned MLIP profiles: environment selection and shared calculator arguments.

No backend is imported, installed or evaluated while reading a configuration.
Runtime probes import no models and install nothing.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CONFIG_NAME = "genkai.yaml"
BACKENDS = {"mace": "mace", "uma": "fairchem", "emt": "ase"}
RELAX_DEFAULTS = {"fmax": 0.05, "max_steps": 200, "screen_steps": 20, "relax_steps": 0}


class MlipConfigError(ValueError):
    """An actionable configuration or runtime error for an end user."""


def _path(value: str, base: Path) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    # Do not resolve interpreter symlinks: /venv/bin/python must retain its venv.
    return Path(os.path.abspath(path if path.is_absolute() else base / path))


def python_path(value: str, base: Path) -> Path:
    expanded = os.path.expandvars(value)
    if not any(char in expanded for char in ("/", "\\")):
        found = shutil.which(expanded)
        if found:
            return Path(found).absolute()
    return _path(expanded, base)


@dataclass
class MlipProfile:
    name: str
    backend: str
    python: Path
    model: str | None
    config_path: Path
    device: str = "cuda"
    task: str = "omat"
    dtype: str = "float32"
    checkpoint: str | None = None
    launcher: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    oom_fallback: str | None = None

    @property
    def runtime_dir(self) -> Path:
        identity = hashlib.sha256(str(self.python).encode()).hexdigest()[:10]
        return self.config_path.parent / ".genkai" / "runtimes" / f"{self.name}-{identity}"

    @property
    def prepared_python(self) -> Path:
        return self.runtime_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def runtime_python(self) -> Path:
        stamp = self.runtime_dir / "genkai-runtime.json"
        try:
            record = json.loads(stamp.read_text(encoding="utf-8"))
            if record.get("source_python") == str(self.python) and self.prepared_python.is_file():
                return self.prepared_python
        except (OSError, ValueError):
            pass
        return self.python

    def command(self) -> list[str]:
        return [*self.launcher, str(self.runtime_python())]

    def environment(self, source_root: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.update(self.env)
        if self.backend == "mace" and self.model:
            env["MACE_MODEL"] = self.model
        if self.backend == "uma":
            env["GENKAI_UMA_MODEL"] = self.checkpoint or self.model or "uma-s-1p2"
        env.setdefault("GENKAI_MLIP_DEVICE", self.device)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(source_root), env.get("PYTHONPATH")]))
        env.update(MPLBACKEND="Agg", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        return env

    def public_settings(self) -> dict[str, Any]:
        """Safe provenance: environment values and credentials are never serialized."""
        return {
            "profile": self.name, "config": str(self.config_path), "backend": self.backend,
            "python": str(self.runtime_python()), "source_python": str(self.python),
            "model": self.model, "device": self.device,
            "task": self.task if self.backend == "uma" else None,
            "dtype": self.dtype if self.backend == "mace" else None,
            "checkpoint": self.checkpoint, "settings": dict(self.settings),
        }

    def calculator_args(self, flag: str = "--calculator", style: str = "dash") -> list[str]:
        sep = "_" if style == "underscore" else "-"
        args = [f"{flag}={self.backend}", f"--device={self.device}"]
        if self.backend == "mace":
            args += [f"--mace-model={self.model}", f"--mace-dtype={self.dtype}"]
        elif self.backend == "uma":
            args += [f"--uma{sep}model={self.checkpoint or self.model}", f"--task{sep}name={self.task}"]
        return args


@dataclass
class MlipConfig:
    path: Path
    default: str | None
    profiles: dict[str, MlipProfile]

    def select(self, name: str = "default") -> MlipProfile:
        selected = self.default if name == "default" else name
        if not selected or selected not in self.profiles:
            raise MlipConfigError(
                f"{self.path} 中没有 MLIP 配置 {selected or name!r}；"
                f"可用：{', '.join(self.profiles) or '无'}。请编辑配置，或重新运行 ./install.sh。"
            )
        return self.profiles[selected]


def find_config(source: Path, explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().absolute()
        if not path.is_file():
            raise MlipConfigError(f"MLIP 配置文件不存在：{path}")
        return path
    if os.environ.get("GENKAI_CONFIG"):
        return find_config(source, os.environ["GENKAI_CONFIG"])
    for directory in dict.fromkeys([source.parent, *source.parent.parents, Path.cwd(), *Path.cwd().parents]):
        path = directory / CONFIG_NAME
        if path.is_file():
            return path
    raise MlipConfigError("找不到 genkai.yaml；请先运行 ./install.sh，或用 --config 指定 MLIP 配置文件。")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MlipConfigError(f"{label} 必须是 YAML 键值表。")
    return value


def load_config(path: str | Path) -> MlipConfig:
    path = Path(path).expanduser().absolute()
    try:
        data = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), str(path))
    except (OSError, yaml.YAMLError) as exc:
        raise MlipConfigError(f"无法读取 MLIP 配置 {path}：{exc}") from exc
    unknown = set(data) - {"version", "default", "profiles"}
    if unknown:
        raise MlipConfigError(f"{path} 中有未知配置项：{', '.join(sorted(unknown))}")
    if type(data.get("version", 1)) is not int or data.get("version", 1) != 1:
        raise MlipConfigError("genkai.yaml 的 version 必须为 1。")
    profiles = {}
    for name, value in _mapping(data.get("profiles", {}), "profiles").items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise MlipConfigError(f"无效配置名称 {name!r}；请使用字母、数字、下划线或短横线。")
        entry = _mapping(value, f"profiles.{name}")
        unknown = set(entry) - {"backend", "python", "model", "device", "task", "dtype", "checkpoint", "launcher", "env", "settings", "oom_fallback"}
        if unknown:
            raise MlipConfigError(f"profiles.{name} 中有未知参数：{', '.join(sorted(unknown))}")
        backend = entry.get("backend", name)
        if not isinstance(backend, str) or backend not in BACKENDS:
            raise MlipConfigError(f"{name}.backend 必须为 mace、uma 或 emt。")
        py = entry.get("python")
        if not isinstance(py, str) or not py.strip():
            raise MlipConfigError(f"{name}.python 需要填写已安装 MLIP 的 Python 路径。")
        device, dtype = entry.get("device", "cuda"), entry.get("dtype", "float32")
        if device not in {"cpu", "cuda"}:
            raise MlipConfigError(f"{name}.device 必须为 cpu 或 cuda。")
        if dtype not in {"float32", "float64"}:
            raise MlipConfigError(f"{name}.dtype 必须为 float32 或 float64。")
        model = entry.get("model")
        checkpoint = entry.get("checkpoint")
        if backend == "mace":
            if not isinstance(model, str) or not model.strip():
                raise MlipConfigError(f"{name}.model 需要填写本地 MACE 模型文件。")
            model = str(_path(model, path.parent))
        elif backend == "uma":
            model = model or "uma-s-1p2"
            if not isinstance(model, str):
                raise MlipConfigError(f"{name}.model 必须是 UMA 模型名称。")
            if any(char in model for char in ("/", "\\")) or model.endswith((".pt", ".pth", ".ckpt")):
                checkpoint = str(_path(model, path.parent)) if checkpoint is None else checkpoint
        task = entry.get("task", "omat")
        if not isinstance(task, str) or not task.strip():
            raise MlipConfigError(f"{name}.task 必须是非空的 UMA 任务头名称。")
        if checkpoint is not None:
            if backend != "uma" or not isinstance(checkpoint, str):
                raise MlipConfigError(f"{name}.checkpoint 仅用于 UMA 本地检查点。")
            checkpoint = str(_path(checkpoint, path.parent))
        launcher = entry.get("launcher", [])
        if not isinstance(launcher, list) or not all(isinstance(v, str) and v for v in launcher):
            raise MlipConfigError(f"{name}.launcher 必须是命令列表，例如 ['/path/to/start.sh']。")
        if launcher:
            launcher = [str(python_path(launcher[0], path.parent)), *launcher[1:]]
        env = _mapping(entry.get("env", {}), f"{name}.env")
        if not all(isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and isinstance(v, (str, int, float)) for k, v in env.items()):
            raise MlipConfigError(f"{name}.env 必须是环境变量名与简单值的映射。")
        settings = dict(RELAX_DEFAULTS)
        overrides = _mapping(entry.get("settings", {}), f"{name}.settings")
        if set(overrides) - RELAX_DEFAULTS.keys():
            raise MlipConfigError(f"{name}.settings 仅支持 {', '.join(RELAX_DEFAULTS)}。")
        for key, value in overrides.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key == "fmax" and value == 0):
                raise MlipConfigError(f"{name}.settings.{key} 必须为非负数，fmax 必须大于 0。")
            if key != "fmax" and not isinstance(value, int):
                raise MlipConfigError(f"{name}.settings.{key} 必须为整数。")
            settings[key] = value
        oom_fallback = entry.get("oom_fallback")
        if oom_fallback is not None and (not isinstance(oom_fallback, str) or backend != "uma" or device != "cuda"):
            raise MlipConfigError(f"{name}.oom_fallback 需要填写 CUDA UMA 的回退配置名称。")
        profiles[name] = MlipProfile(
            name=name, backend=backend, python=python_path(py, path.parent), model=model,
            config_path=path, device=device, task=task, dtype=dtype, checkpoint=checkpoint,
            launcher=tuple(launcher), env={k: str(v) for k, v in env.items()}, settings=settings, oom_fallback=oom_fallback,
        )
    for profile in profiles.values():
        if profile.oom_fallback is None:
            continue
        fallback = profiles.get(profile.oom_fallback)
        if (fallback is None or fallback.backend != "uma" or fallback.device != "cuda" or fallback.task != profile.task
                or (fallback.checkpoint or fallback.model) == (profile.checkpoint or profile.model)):
            raise MlipConfigError(f"{profile.name}.oom_fallback 必须指向使用同一任务头和不同模型的 CUDA UMA 配置。")
    default = data.get("default")
    if default is not None and (not isinstance(default, str) or default not in profiles):
        raise MlipConfigError("default 必须是 profiles 中的一个配置名称，或填 null。")
    return MlipConfig(path, default, profiles)


PROBE_CODE = '''
import importlib.util, importlib.metadata, json, sys
modules = ["ase", "numpy", "scipy", "pymatgen", "optuna", "pandas", "pydantic", "yaml", sys.argv[1]]
missing = sorted({name for name in modules if importlib.util.find_spec(name) is None})
result = {"python": sys.version.split()[0], "missing": missing}
if sys.version_info < (3, 11):
    result["error"] = "Python 需要 >= 3.11"
if sys.argv[1] == "fairchem" and not missing:
    from genkai.modeling.surface.mlip.calculators import available_uma_tasks
    result["uma_tasks"] = available_uma_tasks()
for name in ["mace-torch", "fairchem-core", "torch", "ase"]:
    try:
        result[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        pass
print("GENKAI_PROFILE_CHECK=" + json.dumps(result))
'''


def probe_profile(profile: MlipProfile, source_root: Path, *, timeout: float = 90.0) -> dict[str, Any]:
    if not profile.python.is_file():
        raise MlipConfigError(f"配置 {profile.name} 的 Python 不存在：{profile.python}")
    for label, model in (("MACE 模型", profile.model if profile.backend == "mace" else None), ("UMA 检查点", profile.checkpoint)):
        if model and not Path(model).is_file():
            raise MlipConfigError(f"配置 {profile.name} 的{label}不存在：{model}")
    try:
        completed = subprocess.run(
            [*profile.command(), "-c", PROBE_CODE, BACKENDS[profile.backend]],
            env=profile.environment(source_root), capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MlipConfigError(f"无法启动配置 {profile.name} 的 Python（{type(exc).__name__}）；请检查 python/launcher 路径。") from exc
    result = None
    for line in completed.stdout.splitlines():
        if line.startswith("GENKAI_PROFILE_CHECK="):
            try:
                result = json.loads(line.partition("=")[2])
            except ValueError:
                pass
    if completed.returncode or not isinstance(result, dict):
        raise MlipConfigError(f"配置 {profile.name} 的环境检查失败（退出码 {completed.returncode}）；请检查 Python 和 launcher 能否启动。")
    if result.get("error"):
        raise MlipConfigError(f"配置 {profile.name}：{result['error']}")
    if result.get("missing"):
        raise MlipConfigError(
            f"配置 {profile.name} 的环境缺少 {', '.join(result['missing'])}。"
            "请确认已自行安装 MLIP，再运行 ./install.sh 为它准备项目依赖（不会安装 MLIP）。"
        )
    tasks = result.get("uma_tasks")
    if tasks is not None and profile.task not in tasks:
        raise MlipConfigError(f"UMA 任务头 {profile.task!r} 不可用；已安装版本支持：{', '.join(tasks)}。")
    return result


def main(argv: list[str] | None = None) -> int:
    """Developer convenience: run Python arguments in one configured environment."""
    import argparse

    parser = argparse.ArgumentParser(description="使用 genkai.yaml 中配置的 MLIP 环境运行 Python。")
    parser.add_argument("--config", type=Path)
    parser.add_argument("profile")
    parser.add_argument("python_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.python_args:
        parser.error("需要 Python 参数，例如 -m genkai.modeling.surface.screening.sam_search --help")
    try:
        profile = load_config(find_config(Path.cwd() / "job.yaml", args.config)).select(args.profile)
        command = [*profile.command(), *args.python_args]
        import genkai

        source_root = Path(genkai.__file__).resolve().parents[1]  # the directory that contains genkai/
        os.execvpe(command[0], command, profile.environment(source_root))
    except (MlipConfigError, OSError) as exc:
        print(f"无法启动 MLIP 环境：{exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
