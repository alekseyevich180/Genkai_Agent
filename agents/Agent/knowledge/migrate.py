"""One-time migration: reads MEMORY.md and populates the knowledge graph."""

from __future__ import annotations

import logging
import re

from .kdg_memory import add_memory
from .query import _get_kg

logger = logging.getLogger(__name__)


def migrate_memory_md(memory_path: str | None = None) -> dict:
    """Migrate entries from MEMORY.md into the knowledge graph.

    Each bullet line in MEMORY.md is treated as an Insight node. The function
    is idempotent — re-running it skips near-duplicate entries via fuzzy matching.

    Args:
        memory_path: Absolute path to MEMORY.md. Defaults to workspace MEMORY.md.

    Returns:
        Dict with keys: status, nodes_created, skipped, message.
    """
    from ..workspace import WORKSPACE_ROOT

    if memory_path is None:
        path = WORKSPACE_ROOT / "MEMORY.md"
    else:
        from pathlib import Path
        path = Path(memory_path)

    if not path.exists():
        return {
            "status": "skipped",
            "message": f"MEMORY.md not found at {path}",
            "nodes_created": 0,
            "skipped": 0,
        }

    text = path.read_text(encoding="utf-8")
    # Extract bullet list items (- text or * text) and standalone non-empty lines
    entries: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Strip leading bullet markers
        cleaned = re.sub(r"^[-*•]\s+", "", stripped)
        if len(cleaned) >= 10:
            entries.append(cleaned)

    kg = _get_kg()
    memory = kg.memory("legacy-memory-md")
    existing = {entry.content.casefold() for entry in memory.list()}
    created = 0
    skipped = 0

    for entry in entries:
        if entry.casefold() in existing:
            skipped += 1
            continue
        add_memory(
            kg,
            "legacy-memory-md",
            entry,
            tags=["memory-md", "migrated"],
        )
        existing.add(entry.casefold())
        created += 1

    logger.info("Migration: %d created, %d skipped", created, skipped)
    return {
        "status": "ok",
        "nodes_created": created,
        "skipped": skipped,
        "message": (
            f"Migrated MEMORY.md: {created} working-memory entries, "
            f"{skipped} skipped (near-duplicates)."
        ),
    }
