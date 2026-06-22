"""Workspace management for MatClaw — project-local overlay of skills/guides/memory.

The workspace root is resolved in this order:
1. ``MATCLAW_WORKSPACE`` environment variable (absolute or relative to CWD)
2. ``~/.workspace/`` in the user's home directory

On first use, call :func:`init_workspace` to create the directory tree.
Default skills are loaded directly from the module; only custom (user-created)
skills belong in ``$WORKSPACE/skills/``.
"""

from __future__ import annotations

import os
from pathlib import Path
from .constants import _AGENT_PATH



# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def get_workspace_root() -> Path:
    """Return the resolved workspace root path (not guaranteed to exist)."""
    env_val = os.environ.get("MATCLAW_WORKSPACE", "")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return (Path(__file__).parent / ".workspace").resolve()

WORKSPACE_ROOT=get_workspace_root()  # resolved once at module load time for efficiency


def workspace_skills_dir() -> Path:
    return WORKSPACE_ROOT / "skills"


def workspace_guides_dir() -> Path:
    return WORKSPACE_ROOT / "guides"


def workspace_memory_path() -> Path:
    return WORKSPACE_ROOT / "MEMORY.md"


def get_session_workdir(session_id: str) -> Path:
    env_val = os.environ.get("MATCLAW_SESSION_DIR", "")
    if env_val:
        return Path(env_val).expanduser().resolve()
    return WORKSPACE_ROOT / "sessions" / session_id


def init_session_workdir(session_id: str) -> Path:
    d = get_session_workdir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init_workspace(force: bool = False) -> str:
    """Create the workspace directory tree and seed built-in guides and memory.

    Default skills are NOT copied here — they are loaded directly from the
    module at runtime.  Only user-created custom skills belong in the workspace.

    If the workspace already exists this is a no-op unless *force* is True,
    in which case built-in guide files that are missing are re-copied
    (existing workspace files are never overwritten).

    Returns a human-readable status message.
    """
    root = WORKSPACE_ROOT
    skills_dir = workspace_skills_dir()
    guides_dir = workspace_guides_dir()

    skills_dir.mkdir(parents=True, exist_ok=True)
    guides_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []

    # Copy built-in guides → workspace guides (do not overwrite)
    builtin_guides = _AGENT_PATH / "guides"
    for src in sorted(builtin_guides.glob("*.md")):
        dst = guides_dir / src.name
        if not dst.exists() or force:
            import shutil
            shutil.copy2(src, dst)
            copied.append(f"guides/{src.name}")

    # Seed MEMORY.md
    mem = workspace_memory_path()
    if not mem.exists():
        mem.write_text("# Workspace Memory\n\n")
        copied.append("MEMORY.md")

    if copied:
        return f"Workspace initialised at {root}\nSeeded: {', '.join(copied)}"
    return f"Workspace already exists at {root} (nothing overwritten)."
