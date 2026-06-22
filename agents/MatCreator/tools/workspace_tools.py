"""Workspace authoring tools for the thinking_agent.

These tools allow the agent to create and manage skills under the project
workspace directory ($MATCLAW_WORKSPACE or ./.workspace).

Security contract
-----------------
* ``write_workspace_file``  only writes inside the workspace root (path
  traversal is rejected).
* ``run_python`` / ``run_bash`` execute in a subprocess with a 60-second
  timeout.  The agent must always present the code/command to the user and
  obtain explicit approval before calling these tools (enforced by the
  thinking_agent instruction).
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from ..workspace import get_workspace_root, get_session_workdir, workspace_skills_dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_workspace_path(relative: str) -> Path:
    """Resolve *relative* inside the workspace root, refusing path traversal."""
    root = get_workspace_root()
    resolved = (root / relative).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        raise ValueError(
            f"Path '{relative}' resolves outside the workspace root '{root}'."
        )
    return resolved


def _resolve_skill_script_path(
    skills_root: Path, skill_name: str, script_name: str
) -> Path | None:
    """Resolve a script path for flat or nested skill layouts.

    Supported layouts:
    - ``skills/<skill_name>/scripts/<script_name>``
    - ``skills/**/<skill_name>/scripts/<script_name>``
    """
    direct_path = skills_root / skill_name / "scripts" / script_name
    if direct_path.exists():
        return direct_path

    matches: list[Path] = []
    for skill_md in skills_root.rglob("SKILL.md"):
        skill_dir = skill_md.parent
        if skill_dir.name != skill_name:
            continue
        candidate = skill_dir / "scripts" / script_name
        if candidate.exists():
            matches.append(candidate)

    if not matches:
        return None

    return sorted(matches, key=lambda path: path.as_posix())[0]


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------

def write_workspace_file(relative_path: str, content: str) -> str:
    """Write *content* to a file inside the workspace directory.

    Args:
        relative_path: Path relative to the workspace root, e.g.
            ``"skills/my_skill/my_skill.md"`` or ``"guides/project_guide.md"``.
            Must not escape the workspace root.
        content: Full file content to write (overwrites if the file exists).

    Returns:
        Confirmation message with the absolute path that was written.
    """
    target = _safe_workspace_path(relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written: {target}"


def read_workspace_file(relative_path: str) -> str:
    """Read and return the content of a file inside the workspace directory.

    Args:
        relative_path: Path relative to the workspace root.

    Returns:
        File content as a string, or an error message if not found.
    """
    target = _safe_workspace_path(relative_path)
    if not target.exists():
        return f"File not found: {target}"
    return target.read_text(encoding="utf-8")


def list_workspace_skills() -> str:
    """List all skills currently present in the workspace skills directory.

    Returns a formatted string enumerating all discovered ``SKILL.md`` bundles.
    """
    skills_dir = workspace_skills_dir()
    if not skills_dir.exists():
        return "No workspace skills directory found. Run init_workspace first."

    lines: list[str] = []
    for p in sorted(skills_dir.rglob("SKILL.md")):
        rel_dir = p.parent.relative_to(skills_dir.parent)
        depth = len(p.relative_to(skills_dir).parts) - 1
        layout = "nested" if depth > 1 else "subdir"
        lines.append(f"  [{layout}] {p.parent.name}  →  {rel_dir}/")

    if not lines:
        return "Workspace skills directory is empty."
    return "Workspace skills:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# High-level skill scaffolding
# ---------------------------------------------------------------------------

_SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
tools: []
dependent_skills: []
---
{instruction}
"""


def create_skill(
    name: str,
    description: str,
    instruction: str,
) -> str:
    """Scaffold a new skill under ``$WORKSPACE/skills/<name>/SKILL.md``.

    Creates the directory and markdown file.  Does NOT overwrite an existing
    skill — use ``write_workspace_file`` for updates.

    Args:
        name: Unique skill identifier (snake_case, no spaces).
        description: One-sentence description shown to the planner.
        instruction: The full instruction body for the skill (plain Markdown).

    Returns:
        Confirmation message with the path created, or an error if it exists.
    """
    skill_dir = workspace_skills_dir() / name
    skill_file = skill_dir / "SKILL.md"

    from ..skill import get_default_skill_names
    if name in get_default_skill_names():
        return (
            f"Cannot create skill '{name}': a default skill with that name already exists. "
            "Default skills cannot be overridden by workspace skills."
        )

    if skill_file.exists():
        return (
            f"Skill '{name}' already exists at {skill_file}. "
            "Use write_workspace_file to update it."
        )

    skill_dir.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(_SKILL_TEMPLATE).format(
        name=name,
        description=description,
        instruction=instruction.strip(),
    )
    skill_file.write_text(content, encoding="utf-8")
    return f"Skill '{name}' created at {skill_file}"


# ---------------------------------------------------------------------------
# Script execution tools
# ---------------------------------------------------------------------------

_EXEC_TIMEOUT = 3600  # seconds


def run_python(code: str, tool_context: ToolContext) -> str:
    """Execute a Python code snippet and return its stdout/stderr.

    IMPORTANT: Only call this tool after the user has explicitly approved the
    code to be run.  The code runs in a subprocess with a 60-second timeout.

    Args:
        code: Python source code to execute.

    Returns:
        Combined stdout and stderr output, truncated to 4 000 characters.
    """
    cwd = tool_context.state.get("workspace_dir")
    if not cwd:
        session_id = tool_context.state.get("session_id")
        if session_id:
            cwd = str(get_session_workdir(session_id))
    result = subprocess.run(
        ["python", "-c", code],
        capture_output=True,
        text=True,
        timeout=_EXEC_TIMEOUT,
        cwd=cwd,
    )
    output = result.stdout + result.stderr
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"
    return output or "(no output)"


def run_bash(script: str, tool_context: ToolContext) -> str:
    """Execute a bash script snippet and return its stdout/stderr.

    IMPORTANT: Only call this tool after the user has explicitly approved the
    script to be run.  The script runs in a subprocess with a 60-second timeout.

    Args:
        script: Bash script content to execute.

    Returns:
        Combined stdout and stderr output, truncated to 4 000 characters.
    """
    cwd = tool_context.state.get("workspace_dir")
    if not cwd:
        session_id = tool_context.state.get("session_id")
        if session_id:
            cwd = str(get_session_workdir(session_id))
    try:
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            timeout=_EXEC_TIMEOUT,
            cwd=cwd,
        )
        output = result.stdout.decode("utf-8", errors="replace") + result.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        partial_out = (exc.output or b"").decode(errors="replace") if isinstance(exc.output, bytes) else (exc.output or "")
        partial_err = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        output = f"[TimeoutExpired after {_EXEC_TIMEOUT}s]\n" + partial_out + partial_err
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"
    return output or "(no output)"


def run_python_file(relative_path: str) -> str:
    """Execute a Python script that lives inside the workspace directory.

    IMPORTANT: Only call this tool after the user has explicitly approved the
    script.

    Args:
        relative_path: Path relative to the workspace root, e.g.
            ``"skills/my_skill/validate.py"``.

    Returns:
        Combined stdout and stderr output, truncated to 4 000 characters.
    """
    target = _safe_workspace_path(relative_path)
    if not target.exists():
        return f"File not found: {target}"
    result = subprocess.run(
        ["python", str(target)],
        capture_output=True,
        text=True,
        timeout=_EXEC_TIMEOUT,
    )
    output = result.stdout + result.stderr
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"
    return output or "(no output)"


def run_skill_script(
    skill_name: str, script_name: str, args: str, tool_context: ToolContext
) -> str:
    """Execute a script bundled inside a skill's ``scripts/`` directory.

    The script is resolved from either a flat skill layout such as
    ``<workspace>/skills/<skill_name>/scripts/<script_name>`` or a nested skill
    layout such as
    ``<workspace>/skills/<group>/<skill_name>/scripts/<script_name>``.
    It is executed with the current session's working directory as ``cwd``, so
    any relative paths in *args* (e.g. ``--workdir ./train_001``) resolve
    against the session workspace rather than the skill directory.

    Args:
        skill_name: Name of the skill that owns the script (e.g. ``"deepmd"``).
        script_name: Filename inside the skill's ``scripts/`` directory
            (e.g. ``"deepmd_prepare.py"`` or ``"run_job.sh"``).
            The interpreter is chosen automatically from the file extension
            (``.py`` → python, ``.sh``/``.bash`` → bash, ``.js`` → node).
            Executable files with a shebang are run directly.
        args: Command-line arguments to pass to the script as a single string
            (e.g. ``"prepare-training --workdir ./train --train_data data.xyz"``).

    Returns:
        Combined stdout and stderr output, truncated to 4 000 characters.
    """
    from ..workspace import workspace_skills_dir
    from ..skill import _MODULE_SKILLS_ROOT

    script_path = _resolve_skill_script_path(workspace_skills_dir(), skill_name, script_name)
    if script_path is None:
        script_path = _resolve_skill_script_path(_MODULE_SKILLS_ROOT, skill_name, script_name)
    if script_path is None:
        return (
            f"Script not found for skill '{skill_name}': scripts/{script_name}\n"
            f"Searched under: {workspace_skills_dir()} and {_MODULE_SKILLS_ROOT}\n"
            f"Ensure the skill has a scripts/{script_name} file."
        )

    cwd = tool_context.state.get("workspace_dir")
    env = None
    if not cwd:
        session_id = tool_context.state.get("session_id")
        if session_id:
            session_workdir = get_session_workdir(session_id)
            cwd = str(session_workdir)
            env = dict(os.environ)
            env["MATCLAW_SESSION_DIR"] = str(session_workdir)
    if cwd and env is None:
        env = dict(os.environ)
        env["MATCLAW_SESSION_DIR"] = cwd

    _ext_map = {".py": "python", ".sh": "bash", ".bash": "bash", ".js": "node"}
    ext = script_path.suffix.lower()
    if ext in _ext_map:
        cmd = f"{_ext_map[ext]} {script_path} {args}"
    elif os.access(script_path, os.X_OK):
        cmd = f"{script_path} {args}"
    else:
        cmd = f"bash {script_path} {args}"
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            timeout=_EXEC_TIMEOUT,
            cwd=cwd,
            env=env,
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        partial_out = (exc.output or b"").decode(errors="replace") if isinstance(exc.output, bytes) else (exc.output or "")
        partial_err = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        output = f"[TimeoutExpired after {_EXEC_TIMEOUT}s]\n" + partial_out + partial_err
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"
    return output or "(no output)"


# ---------------------------------------------------------------------------
# Workspace initialisation tool (agent-callable)
# ---------------------------------------------------------------------------

def init_workspace_tool() -> str:
    """Initialise the project workspace directory and seed it with built-in defaults.

    Creates ``$MATCLAW_WORKSPACE`` (or ``./.workspace``) if it does not exist,
    then copies the built-in skills and guides into it so the user can customise
    them.  Existing workspace files are never overwritten.

    Returns:
        Status message describing what was created.
    """
    from ..workspace import init_workspace
    from ..skill import refresh_skills
    msg = init_workspace()
    refresh_skills()
    return msg
