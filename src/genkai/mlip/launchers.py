"""Dependency-free launcher contracts shared by MLIP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class LauncherContract:
    name: str
    environment_variable: str
    role: str
    required_markers: tuple[str, ...]


LAUNCHER_CONTRACTS: Mapping[str, LauncherContract] = MappingProxyType(
    {
        "mace": LauncherContract(
            "mace",
            "GENKAI_MACE_LAUNCHER",
            "inference",
            ("MACE_WORK_DIR", "MACE_PYTHON_ARGS", "MACE_DRY_RUN"),
        ),
        "deepmd": LauncherContract(
            "deepmd",
            "GENKAI_DEEPMD_LAUNCHER",
            "training",
            (
                "DEEPMD_WORK_DIR",
                "DEEPMD_ARGS",
                "DEEPMD_REQUIRED_PATHS",
                "DEEPMD_DRY_RUN",
            ),
        ),
        "uma": LauncherContract(
            "uma",
            "GENKAI_UMA_LAUNCHER",
            "finetuning",
            (
                "UMA_FINETUNE_WORK_DIR",
                "UMA_FINETUNE_CONFIG",
                "UMA_FINETUNE_DRY_RUN",
                "UMA_FINETUNE_BASE_MODEL_PATH",
                "UMA_FINETUNE_BASE_MODEL_SHA256",
            ),
        ),
    }
)


def get_launcher_contract(name: str) -> LauncherContract:
    """Return a known contract and fail closed for unknown adapter roles."""

    return LAUNCHER_CONTRACTS[name]


__all__ = ["LAUNCHER_CONTRACTS", "LauncherContract", "get_launcher_contract"]
