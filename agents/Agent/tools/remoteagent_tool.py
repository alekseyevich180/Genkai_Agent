"""Helpers for loading remote A2A sub-agents from YAML configuration."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent


logger = logging.getLogger(__name__)


def _default_config_path() -> Path:
    """Return the default remote-agent config path."""
    return (Path(__file__).resolve().parent.parent / "agents" / "subagent.yaml")


def _read_config(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load the YAML config file for remote A2A agents."""
    path = Path(config_path).expanduser().resolve() if config_path else _default_config_path()
    if not path.exists():
        logger.warning("Remote agent config not found: %s", path)
        return {"agents": []}

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Remote agent config must be a mapping: {path}")
    return data


def _build_remote_agent(agent_cfg: dict[str, Any]) -> RemoteA2aAgent:
    """Create one RemoteA2aAgent from a validated YAML item."""
    name = str(agent_cfg["name"]).strip()
    description = str(agent_cfg.get("description", "")).strip()
    agent_card = str(
        agent_cfg.get("agent_card") or agent_cfg.get("agent_card_url") or ""
    ).strip()
    if not name:
        raise ValueError("Remote agent config is missing a non-empty 'name'.")
    if not agent_card:
        raise ValueError(
            f"Remote agent '{name}' is missing 'agent_card' or 'agent_card_url'."
        )

    return RemoteA2aAgent(
        name=name,
        description=description,
        agent_card=agent_card
    )


def load_remote_a2a_agents(
    config_path: str | os.PathLike[str] | None = None,
) -> list[RemoteA2aAgent]:
    """Load enabled remote A2A agents from YAML configuration.

    Expected YAML shape:

    ```yaml
    agents:
      - name: atom_sculptor
        description: Remote AtomSculptor orchestrator
        agent_card_url: http://127.0.0.1:8001/.well-known/agent-card.json
        enabled: true
        use_legacy: false
    ```
    """
    data = _read_config(config_path)
    items = data.get("agents", [])
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError("Remote agent config field 'agents' must be a list.")

    remote_agents: list[RemoteA2aAgent] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning("Skipping remote agent entry %d: expected a mapping.", index)
            continue
        if not item.get("enabled", True):
            continue
        try:
            remote_agents.append(_build_remote_agent(item))
        except Exception as exc:
            logger.warning("Skipping invalid remote agent entry %d: %s", index, exc)

    logger.info("Loaded %d remote A2A agents.", len(remote_agents))
    return remote_agents
