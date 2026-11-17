"""Stable facade for replaying saved surface-paper extraction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from genkai.contracts.artifacts import (
    EvidenceLevel,
    ExecutionState,
    ExtractionArtifact,
    PaperArtifact,
    ValidationStatus,
)
from genkai.contracts.run import RunManifest, StageRecord
from genkai.literature.surface.core.records import read_relation_records
from genkai.workflow.store import load_manifest, save_manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(run_root: Path) -> RunManifest:
    path = run_root / "manifest.json"
    return load_manifest(run_root) if path.exists() else RunManifest(run_id=run_root.name)


def run_surface_extraction(
    request: str | Path,
    run_root: str | Path,
    *,
    conditions_csv: str | Path | None = None,
) -> ExtractionArtifact:
    """Replay a saved relations JSONL file into a versioned run.

    Network-backed extraction is exposed by ``genkai.literature.surface``;
    this artifact facade deliberately requires a saved input for deterministic
    workflow replay. Legacy pretty JSON is normalized to JSONL. An optional
    condition table is snapshotted with a run-relative path and SHA-256 in the
    extraction metadata, so later planning does not depend on the input file.
    """

    source = Path(request)
    if not source.is_file():
        raise FileNotFoundError(source)
    records = read_relation_records(source)
    if not records:
        raise ValueError("saved surface extraction contains no records")
    source_hash = _sha256(source)
    conditions_data = (
        Path(conditions_csv).read_bytes() if conditions_csv is not None else None
    )

    root = Path(run_root)
    extraction_path = root / "stages" / "01_paperread" / "extraction.jsonl"
    extraction_path.parent.mkdir(parents=True, exist_ok=True)
    extraction_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    metadata: dict[str, Any] = {
        "record_count": len(records), "source_sha256": source_hash,
    }
    if conditions_data is not None:
        conditions_path = extraction_path.with_name("conditions.csv")
        conditions_path.write_bytes(conditions_data)
        metadata["conditions_table"] = {
            "path": conditions_path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(conditions_data).hexdigest(),
            "source_uri": str(conditions_csv),
        }

    article_path = root / "article.json"
    article_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source": str(source),
                "title": records[0].get("title"),
                "surface_relations": [
                    record.get("extraction", record) for record in records
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest = _manifest(root)
    paper = PaperArtifact(
        artifact_id=f"{manifest.run_id}:paper",
        path=article_path.relative_to(root),
        sha256=_sha256(article_path),
        producer="genkai.literature.surface",
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.PAPER_EXTRACTED,
        validation_status=ValidationStatus.PASSED,
        metadata={"source_uri": str(source)},
    )
    extraction = ExtractionArtifact(
        artifact_id=f"{manifest.run_id}:extraction",
        path=extraction_path.relative_to(root),
        sha256=_sha256(extraction_path),
        producer="genkai.literature.surface",
        parent_ids=[paper.artifact_id],
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.PAPER_EXTRACTED,
        validation_status=ValidationStatus.PASSED,
        metadata=metadata,
    )
    manifest.register_artifact(paper)
    manifest.register_artifact(extraction)
    manifest.append_stage(
        StageRecord(
            stage_id="01_paperread",
            adapter="genkai.literature.surface",
            execution_state=ExecutionState.SUCCEEDED,
            output_artifact_ids=[paper.artifact_id, extraction.artifact_id],
        )
    )
    save_manifest(root, manifest)
    return extraction
