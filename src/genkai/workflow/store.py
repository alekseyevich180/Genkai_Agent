"""Atomic persistence for run manifests."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from genkai.contracts.run import RunManifest


MANIFEST_NAME = "manifest.json"


def save_manifest(run_root: Path, manifest: RunManifest) -> Path:
    run_root = Path(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    target = run_root / MANIFEST_NAME
    payload = manifest.model_dump_json(indent=2)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".manifest.",
            suffix=".tmp",
            dir=run_root,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def load_manifest(run_root: Path) -> RunManifest:
    path = Path(run_root) / MANIFEST_NAME
    return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))
