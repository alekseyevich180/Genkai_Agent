"""Provenance records for reproducible scientific artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """How an artifact was produced, without embedding large payloads."""

    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    software: str | None = None
    software_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
