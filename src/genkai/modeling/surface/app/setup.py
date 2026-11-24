"""Prepare end-user configuration and project dependencies around existing MLIPs.

Never install a MLIP, torch, or a model. Each configured backend is inherited
through a separate system-site-packages venv containing Genkai's base dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from ..mlip.mlip_config import BACKENDS, MlipConfigError, MlipProfile, load_config, probe_profile, python_path


CONFIG_HEADER = """# Genkai：只在这里登记已安装的 MLIP，无需修改任何建模脚本。
# python：已有 MLIP 环境里的 Python；model：MACE 本地模型或 UMA 模型名称。
# default：任务里 mlip: default 使用的配置。任务也可写 mlip: mace 或 mlip: uma。
# 相对路径以本配置文件所在目录为准。访问凭据使用环境变量，不写入本文件。
"""
EMPTY_EXAMPLE = """
# 在自行安装 MLIP 后，参考下面的内容填写 profiles，再运行 ./install.sh --configure-only。
# default: mace
# profiles:
#   mace:
#     backend: mace
#     python: /path/to/mace/env/bin/python
#     model: /path/to/trusted/model.model
#     device: cuda
#     dtype: float32
#     env: {TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD: '1'}
#   uma:
#     backend: uma
#     python: /path/to/uma/env/bin/python
#     model: uma-s-1p2
#     task: omat
#     device: cuda
"""


def project_root() -> Path:
    # Anchored on the genkai package (src/genkai) so moving this module does not change the result.
    import genkai

    return Path(genkai.__file__).resolve().parents[2]


def _ask(label: str, default: str = "") -> str:
    value = input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip()
    return default if not value else value


def discover_profiles() -> dict[str, dict[str, str]]:
    """Best-effort discovery; explicit configuration always takes precedence."""
    home = Path.home()
    candidates = [Path(sys.executable)]
    for key in ("CONDA_PREFIX", "VIRTUAL_ENV"):
        if os.environ.get(key):
            candidates.append(Path(os.environ[key]) / "bin/python")
    for key in ("MACE_PYTHON", "UMA_PYTHON"):
        if os.environ.get(key):
            candidates.append(python_path(os.environ[key], Path.cwd()))
    for root in (home / "miniforge3", home / "miniconda3", home / "anaconda3", home / "softwares/miniforge3"):
        candidates.extend(sorted(root.glob("envs/*/bin/python")))
    for root in (home / ".venvs", home / "softwares"):
        candidates.extend(sorted(root.glob("*/.venv/bin/python")))
        candidates.extend(sorted(root.glob("*/bin/python")))
    found = {}
    code = "import importlib.util,json; print(json.dumps({p: importlib.util.find_spec(p) is not None for p in ['mace','fairchem']}))"
    for candidate in dict.fromkeys(candidates):
        if not candidate.is_file():
            continue
        try:
            result = subprocess.run([str(candidate), "-c", code], capture_output=True, text=True, timeout=10)
            packages = json.loads(result.stdout.strip()) if result.returncode == 0 else {}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
        for backend, module in (("mace", "mace"), ("uma", "fairchem")):
            if packages.get(module) and backend not in found:
                entry = {"backend": backend, "python": str(candidate.absolute())}
                launcher = home / "starts" / f"{backend}.sh"
                if launcher.is_file():
                    entry["launcher"] = [str(launcher)]
                found[backend] = entry
    if "mace" in found:
        model = os.environ.get("MACE_MODEL")
        if not model:
            models = sorted((home / "mace_models").glob("**/*.model"), key=lambda p: ("small" not in p.name, str(p)))
            model = str(models[0]) if models else None
        if model:
            found["mace"]["model"] = model
    return found


def configure(args: argparse.Namespace) -> Path:
    path = args.config.expanduser().absolute()
    existing = path.is_file()
    if existing:
        # Validate before changing anything; retain comments when no explicit updates were requested.
        load_config(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        data = {"version": 1, "default": None, "profiles": {}}
    updates = any(getattr(args, key) is not None for key in ("mace_python", "mace_model", "mace_launcher", "uma_python", "uma_model", "uma_launcher", "default", "device"))
    if existing and not updates:
        print(f"保留已有配置：{path}")
        return path
    discovered = discover_profiles() if not existing else {}
    interactive = not args.non_interactive and sys.stdin.isatty() and not existing
    profiles = data.setdefault("profiles", {})
    for backend in ("mace", "uma"):
        entry = dict(profiles.get(backend, discovered.get(backend, {})))
        requested_python = getattr(args, f"{backend}_python")
        py = requested_python or entry.get("python", "")
        if interactive:
            py = _ask(f"{backend.upper()} 环境的 Python（输入 none 跳过）", py or "none")
        if not py or str(py).lower() == "none":
            if requested_python or getattr(args, f"{backend}_model"):
                raise MlipConfigError(f"请同时提供 --{backend}-python。")
            profiles.pop(backend, None)
            continue
        entry.update(backend=backend, python=str(python_path(str(py), path.parent)))
        model = getattr(args, f"{backend}_model") or entry.get("model", "uma-s-1p2" if backend == "uma" else "")
        if interactive:
            model = _ask(f"{backend.upper()} 的模型" + ("文件" if backend == "mace" else "名称或本地检查点"), str(model))
        if backend == "mace" and not model:
            if requested_python:
                raise MlipConfigError("MACE 需要 --mace-model /path/to/model.model。")
            print("检测到 MACE，但未找到模型；暂不启用，请在 genkai.yaml 中填写模型文件。")
            continue
        entry["model"] = str(model)
        entry["device"] = args.device or entry.get("device", "cuda")
        if backend == "mace":
            entry.setdefault("dtype", "float32")
            # MACE checkpoints are Python model objects; the user chooses a trusted local file.
            entry.setdefault("env", {"TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"})
        else:
            entry.setdefault("task", "omat")
        requested_launcher = getattr(args, f"{backend}_launcher")
        if requested_launcher:
            entry["launcher"] = [str(python_path(requested_launcher, path.parent))]
        profiles[backend] = entry
    default = args.default or data.get("default") or (next(iter(profiles)) if profiles else None)
    if interactive and profiles:
        default = _ask("默认 MLIP 配置（" + ", ".join(profiles) + "）", default or "")
    data["default"] = default
    path.parent.mkdir(parents=True, exist_ok=True)
    text = CONFIG_HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    if not profiles:
        text += EMPTY_EXAMPLE
    # Validate a temporary sibling before replacing an existing user configuration.
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", dir=path.parent, encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        load_config(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"MLIP 配置：{path}")
    return path


def _run(command: list[str], *, env: dict[str, str]) -> None:
    print("+ " + shlex.join(command), flush=True)
    subprocess.run(command, env=env, check=True)


def inherit_site_packages(profile: MlipProfile, env: dict[str, str]) -> None:
    """A venv made from another venv does not inherit the parent's installed MLIP.

    Add the configured source environment explicitly, processing its .pth files
    so editable FAIRChem/MACE installations work as well. Project packages in
    the new environment take precedence over the inherited packages.
    """
    query = "import json,site,sys; print(json.dumps({'sites': site.getsitepackages(), 'paths': sys.path}))"
    source = subprocess.run(
        [*profile.launcher, str(profile.python), "-c", query], env=env,
        check=True, capture_output=True, text=True, timeout=30,
    )
    target = subprocess.run(
        [*profile.launcher, str(profile.prepared_python), "-c", query], env=env,
        check=True, capture_output=True, text=True, timeout=30,
    )
    source_info, target_info = (json.loads(value.stdout.strip().splitlines()[-1]) for value in (source, target))
    own_site = next(Path(value) for value in target_info["sites"] if Path(value).is_relative_to(profile.runtime_dir))
    own_site.mkdir(parents=True, exist_ok=True)
    extra = [value for value in source_info["sites"] if not Path(value).is_relative_to(profile.runtime_dir)]
    (own_site / "_genkai_mlip_environment.pth").write_text(
        "# Inherit the configured MLIP; do not install or copy it.\n"
        + "import site; " + "; ".join(f"site.addsitedir({value!r})" for value in extra) + "\n",
        encoding="utf-8",
    )


def source_constraints(profile: MlipProfile, env: dict[str, str]) -> Path:
    """Preserve the user's working MLIP stack when resolving project dependencies."""
    query = (
        "import importlib.metadata as m,json; "
        "print(json.dumps({d.metadata['Name']: d.version for d in m.distributions() if d.metadata['Name']}))"
    )
    result = subprocess.run(
        [*profile.launcher, str(profile.python), "-c", query], env=env,
        check=True, capture_output=True, text=True, timeout=30,
    )
    versions = json.loads(result.stdout.strip().splitlines()[-1])
    lines = [
        f"{name}=={version}" for name, version in sorted(versions.items())
        if name.lower() != "genkai" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
    ]
    target = profile.runtime_dir / "source-constraints.txt"
    target.write_text("# Existing MLIP environment versions; constraints do not install these packages.\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return target


def prepare_runtime(profile: MlipProfile, root: Path, args: argparse.Namespace) -> None:
    """Inherit an existing backend, install only the project's base dependencies."""
    env = profile.environment(root / "src")
    module = BACKENDS[profile.backend]
    source_check = "import importlib.util,sys; sys.exit(0 if sys.version_info >= (3,11) and importlib.util.find_spec(sys.argv[1]) else 1)"
    try:
        subprocess.run([*profile.launcher, str(profile.python), "-c", source_check, module], env=env, check=True, timeout=30)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise MlipConfigError(f"{profile.name} 的原始环境没有可用的 {profile.backend} 或 Python < 3.11；请自行配置 MLIP，再运行安装脚本。") from exc
    if profile.backend == "mace" and not Path(profile.model or "").is_file():
        raise MlipConfigError(f"MACE 模型文件不存在：{profile.model}")
    installer = args.installer
    if installer == "auto":
        installer = "uv" if shutil.which("uv") else "pip"
    if not profile.prepared_python.is_file():
        profile.runtime_dir.parent.mkdir(parents=True, exist_ok=True)
        if installer == "uv":
            command = ["uv", "venv", "--python", str(profile.python), "--system-site-packages"]
            if args.offline:
                command.append("--offline")
            _run([*command, str(profile.runtime_dir)], env=env)
        else:
            _run([*profile.launcher, str(profile.python), "-m", "venv", "--system-site-packages", str(profile.runtime_dir)], env=env)
    inherit_site_packages(profile, env)
    constraints = source_constraints(profile, env)
    if installer == "uv":
        command = ["uv", "pip", "install", "--python", str(profile.prepared_python)]
        if args.offline:
            command.append("--offline")
    else:
        command = [*profile.launcher, str(profile.prepared_python), "-m", "pip", "install"]
        if args.offline:
            command.append("--no-index")
    if args.no_build_isolation:
        command.append("--no-build-isolation")
    # No optional MLIP extras: never install or upgrade torch, mace-torch or fairchem-core.
    try:
        _run([*command, "--constraint", str(constraints), "-e", str(root)], env=env)
    except subprocess.CalledProcessError as exc:
        raise MlipConfigError(
            f"{profile.name} 的项目依赖准备失败；安装器已保留原 MLIP 的依赖版本。"
            "请检查上方的版本冲突或下载错误；原 MLIP 环境未被修改。"
        ) from exc
    (profile.runtime_dir / "genkai-runtime.json").write_text(
        json.dumps({"source_python": str(profile.python)}, indent=2) + "\n", encoding="utf-8",
    )
    print(f"{profile.name} 项目运行环境已准备；复用已有 {profile.backend}。")


def write_tasks(root: Path, config: Path) -> None:
    from .jobs import METHODS, render_template

    examples = root / "agents/Agent/skills/surface-modeling/examples"
    inputs = {
        "bulk": root / "tests/se4c02105_surface_fullrun/automatic_modeling/sno2_101/bulk_from_materials_project.cif",
        "crystal": root / "tests/se4c02105_surface_fullrun/automatic_modeling/sno2_101/bulk_from_materials_project.cif",
        "surface": examples / "CeO2 (1 1 1).cif", "input": examples / "CeO2 (1 1 1).cif",
        "molecule": examples / "4-acid.vasp", "amorphous": root / "tests/amorphous/TiO2.vasp",
        "cluster": root / "tests/fixtures/archives/generated/s41563-025-02134-9_surface_fullrun/modeling/structures/Ru_hcp_r7.xyz",
    }
    task_dir = config.parent / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    for name in METHODS:
        target = task_dir / f"{name}.yaml"
        if target.exists():
            continue
        text = render_template(name)

        def replace_input(match: re.Match) -> str:
            path = inputs.get(match[1])
            return f"{match[1]}: {json.dumps(str(path), ensure_ascii=False)}" if path and path.is_file() else match[0]

        text = re.sub(r"^(\w+): <[^>]+>", replace_input, text, flags=re.MULTILINE)
        # Explicit config keeps generated tasks portable across the working directory.
        text = text.replace(f"method: {name}\n", f"method: {name}\nconfig: {json.dumps(str(config), ensure_ascii=False)}\n", 1)
        target.write_text(text, encoding="utf-8")
    print(f"可编辑的任务文件：{task_dir}（已有文件不会被覆盖）")


def write_launcher(root: Path, config: Path) -> None:
    target = root / "genkai"
    if target.exists() and "Generated by Genkai" not in target.read_text(encoding="utf-8"):
        print(f"保留已有 {target}；可使用 genkai-surface 命令。")
        return
    target.write_text(
        "#!/usr/bin/env bash\n# Generated by Genkai\nset -euo pipefail\n"
        f"if [[ -z ${{GENKAI_CONFIG:-}} ]]; then export GENKAI_CONFIG={shlex.quote(str(config))}; fi\n"
        f"exec {shlex.quote(sys.executable)} -m genkai.modeling.surface.app.jobs \"$@\"\n",
        encoding="utf-8",
    )
    target.chmod(target.stat().st_mode | 0o111)


def add_setup_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=Path("genkai.yaml"))
    parser.add_argument("--non-interactive", action="store_true", help="使用自动检测和显式参数，不提问")
    for backend in ("mace", "uma"):
        parser.add_argument(f"--{backend}-python")
        parser.add_argument(f"--{backend}-model")
        parser.add_argument(f"--{backend}-launcher")
    parser.add_argument("--default", "--default-mlip", choices=["mace", "uma"], default=None)
    parser.add_argument("--device", choices=["cpu", "cuda"], default=None)
    parser.add_argument("--installer", choices=["auto", "uv", "pip"], default="auto")
    parser.add_argument("--skip-prepare", action="store_true", help="只写配置和任务，不准备项目依赖")
    parser.add_argument("--skip-check", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-build-isolation", action="store_true")


def run_setup(args: argparse.Namespace) -> int:
    root = project_root()
    try:
        path = configure(args)
        config = load_config(path)
        write_launcher(root, path)
        write_tasks(root, path)
        for profile in config.profiles.values():
            if not args.skip_prepare:
                prepare_runtime(profile, root, args)
            if not args.skip_check:
                probe_profile(profile, root / "src")
                print(f"[通过] {profile.name}：{profile.backend} 环境与模型配置可用（未加载模型、未计算能量）。")
        if not config.profiles:
            print("未启用 MLIP：可以直接生成结构；自行安装 MLIP 后填写 genkai.yaml 并重新运行 ./install.sh --configure-only。")
        print("完成。修改 tasks/*.yaml 后运行 ./genkai check tasks/<任务>.yaml，再用 ./genkai run tasks/<任务>.yaml。")
        return 0
    except (MlipConfigError, OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"配置未完成：{exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置已经安装的 MLIP；不安装 MLIP、PyTorch 或模型。")
    add_setup_arguments(parser)
    return run_setup(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
