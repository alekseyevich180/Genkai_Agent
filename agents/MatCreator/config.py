"""User-level persistent configuration for MatCreator.

Config is stored at ~/.matcreator/config.yaml and controls runtime behaviour
such as which skills are promoted to planning access in the thinking agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path.home() / ".matcreator" / "config.yaml"


def load_config() -> dict[str, Any]:
    """Return the full config dict, or an empty dict if no file exists."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return {}


def save_config(config: dict[str, Any]) -> None:
    """Persist *config* to disk, creating the directory if necessary."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def get_planning_skills() -> list[str]:
    """Return the list of extra skill names promoted to planning access."""
    return load_config().get("planning", {}).get("extra_skills", [])


def get_disabled_skills() -> list[str]:
    """Return the list of skill names disabled for knowledge graph search."""
    return load_config().get("skills", {}).get("disabled", [])
