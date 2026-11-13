#!/usr/bin/env python3
"""Run repeatable repository checks for the Genkai development harness.

The script intentionally depends only on the Python standard library.  It is
therefore usable immediately after the project and pytest have been installed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = (
    "AGENTS.md",
    "README.md",
    "docs/harness-engineering.md",
    "docs/migration.md",
    "docs/artifact-contracts.md",
    "docs/skill-development.md",
    "src/genkai",
    "agents/Agent/skills",
    "tests/architecture",
    "tests/external/README.md",
    ".github/workflows/test.yml",
)

REQUIRED_MARKERS = {
    "unit",
    "contract",
    "integration",
    "compatibility",
    "external",
}

PROFILE_TESTS = {
    "quick": (
        "tests/test_test_tiers.py",
        "tests/architecture",
    ),
    "ci": (
        "tests/test_agent.py",
        "tests/test_test_tiers.py",
        "tests/architecture",
    ),
    "package": (
        "tests/packaging/test_wheel_contents.py",
    ),
    "full": ("tests",),
}

ENTRYPOINT_HELP = (
    ("-m", "genkai.cli", "--help"),
    ("-m", "genkai.cli", "surface", "--help"),
    ("-m", "agent.init.start_agent", "--help"),
)


class HarnessError(RuntimeError):
    """Raised when a static Harness contract is not satisfied."""


def _read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _check_python_version() -> None:
    if sys.version_info < (3, 12):
        raise HarnessError(
            "Genkai requires Python 3.12 or newer; "
            f"current interpreter is {sys.version.split()[0]}"
        )


def _check_required_paths() -> None:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    if missing:
        raise HarnessError("missing required paths: " + ", ".join(missing))


def _load_pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _check_pyproject() -> None:
    config = _load_pyproject()
    project = config.get("project", {})
    if project.get("requires-python") != ">=3.12":
        raise HarnessError("pyproject.toml must declare requires-python = '>=3.12'")

    scripts = project.get("scripts", {})
    expected_scripts = {
        "agent": "agent.init.start_agent:main",
        "genkai-workflow": "genkai.cli:main",
    }
    for name, target in expected_scripts.items():
        if scripts.get(name) != target:
            raise HarnessError(f"console script {name!r} must target {target!r}")

    markers = config.get("tool", {}).get("pytest", {}).get("ini_options", {}).get(
        "markers", []
    )
    marker_names = {marker.split(":", 1)[0].strip() for marker in markers}
    missing_markers = sorted(REQUIRED_MARKERS - marker_names)
    if missing_markers:
        raise HarnessError(
            "pyproject.toml is missing pytest markers: " + ", ".join(missing_markers)
        )


def _check_architecture_layout() -> None:
    if (ROOT / "paperread" / "surface").exists():
        raise HarnessError(
            "paperread/surface must not return as an active owner; use src/genkai"
        )
    if not (ROOT / "legacy" / "paperread").is_dir():
        raise HarnessError("historical paperread assets must remain under legacy/paperread")


def _check_documentation_contract() -> None:
    for relative_path in ("AGENTS.md", "docs/harness-engineering.md"):
        text = _read_text(relative_path)
        for placeholder in ("<填写", "<待填写", "TODO: fill"):
            if placeholder in text:
                raise HarnessError(
                    f"{relative_path} contains unresolved placeholder {placeholder!r}"
                )

    workflow = _read_text(".github/workflows/test.yml")
    if "python scripts/check_harness.py ci" not in workflow:
        raise HarnessError(
            ".github/workflows/test.yml must run the Harness CI profile"
        )


def run_doctor() -> None:
    checks = (
        ("Python version", _check_python_version),
        ("required project paths", _check_required_paths),
        ("pyproject contracts", _check_pyproject),
        ("architecture layout", _check_architecture_layout),
        ("documentation and CI contract", _check_documentation_contract),
    )
    for label, check in checks:
        check()
        print(f"PASS: {label}")


def _subprocess_environment() -> dict[str, str]:
    existing = os.environ.get("PYTHONPATH")
    python_path = os.pathsep.join(
        part for part in (str(ROOT / "src"), str(ROOT), existing) if part
    )
    return {**os.environ, "PYTHONPATH": python_path}


def _run(command: list[str]) -> None:
    print("RUN:", " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_subprocess_environment(),
        check=False,
    )
    if completed.returncode:
        raise HarnessError(
            f"command failed with exit code {completed.returncode}: "
            + " ".join(command)
        )


def run_profile(profile: str) -> None:
    run_doctor()
    if profile == "doctor":
        return

    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            *PROFILE_TESTS[profile],
            "-q",
            "--tb=short",
        ]
    )
    if profile == "ci":
        for arguments in ENTRYPOINT_HELP:
            _run([sys.executable, *arguments])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Genkai Harness checks at the requested risk level."
    )
    parser.add_argument(
        "profile",
        nargs="?",
        default="quick",
        choices=("doctor", "quick", "ci", "package", "full"),
        help=(
            "doctor=static contracts; quick=architecture tests; "
            "ci=quick plus Agent imports and CLI help; package=wheel contract; "
            "full=all default tests (currently has a documented collection blocker)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run_profile(args.profile)
    except (HarnessError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"Harness profile '{args.profile}' passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
