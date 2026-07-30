import json
from pathlib import Path

import pytest

from genkai.contracts.artifacts import StructureSetArtifact
from genkai.contracts.run import RunManifest, StageRecord
from genkai.workflow.store import load_manifest, save_manifest


SHA256 = "b" * 64


def _artifact(artifact_id: str, parent_ids: list[str] | None = None):
    return StructureSetArtifact(
        artifact_id=artifact_id,
        path=f"artifacts/{artifact_id}.extxyz",
        sha256=SHA256,
        producer="surface-modeling",
        parent_ids=parent_ids or [],
    )


def test_manifest_round_trip_tracks_stages_and_registered_artifacts(
    tmp_path: Path,
) -> None:
    manifest = RunManifest(run_id="run-001")
    manifest.append_stage(StageRecord(stage_id="surface", adapter="surface"))
    manifest.register_artifact(_artifact("parent"))
    manifest.register_artifact(_artifact("child", ["parent"]))

    path = save_manifest(tmp_path, manifest)
    restored = load_manifest(tmp_path)

    assert path == tmp_path / "manifest.json"
    assert restored.run_id == "run-001"
    assert restored.stages[0].stage_id == "surface"
    assert [item.artifact_id for item in restored.artifacts] == ["parent", "child"]


def test_manifest_rejects_unknown_parent_artifact() -> None:
    manifest = RunManifest(run_id="run-001")

    with pytest.raises(ValueError, match="unknown parent artifact"):
        manifest.register_artifact(_artifact("child", ["missing"]))


def test_interrupted_atomic_save_preserves_original_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = RunManifest(run_id="original")
    save_manifest(tmp_path, original)
    original_json = json.loads((tmp_path / "manifest.json").read_text())

    replacement = RunManifest(run_id="replacement")

    def interrupt_replace(self: Path, target: Path) -> Path:
        raise OSError("simulated interruption")

    monkeypatch.setattr(Path, "replace", interrupt_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        save_manifest(tmp_path, replacement)

    assert json.loads((tmp_path / "manifest.json").read_text()) == original_json
    assert list(tmp_path.glob(".manifest.*.tmp")) == []
