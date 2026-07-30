from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.Agent.agents.execution_agent.step_executor import StepExecutorResult
from agents.Agent.agents.execution_agent.step_executor_runner import (
    _hydrate_manifest_artifacts,
)
from agents.Agent.agents.thinking_agent.planning import ExecutionGraph
from genkai.contracts.artifacts import StructureSetArtifact
from genkai.contracts.run import RunManifest
from genkai.workflow.store import save_manifest


def _node(node_id: str, skill: str) -> dict:
    return {
        "node_id": node_id,
        "label": node_id,
        "action": f"execute {node_id}",
        "suggested_skills": [skill],
    }


def test_legacy_graph_without_artifact_fields_still_parses() -> None:
    graph = ExecutionGraph(
        nodes={
            "read": _node("read", "paperread"),
            "plan": _node("plan", "ptomodel"),
        },
        edges=[["read", "plan"]],
    )

    assert graph.nodes["read"].consumes == []
    assert graph.nodes["plan"].produces == []


def test_artifact_aware_graph_rejects_uma_consuming_structure_set() -> None:
    surface = _node("surface", "surface-modeling")
    surface["produces"] = ["structure-set@1"]
    uma = _node("uma", "uma")
    uma["consumes"] = ["dataset@1", "model@1"]

    with pytest.raises(ValidationError, match="artifact_type_mismatch"):
        ExecutionGraph(
            nodes={"surface": surface, "uma": uma},
            edges=[["surface", "uma"]],
        )


def test_executor_result_reads_artifact_ids_from_manifest(tmp_path: Path) -> None:
    manifest = RunManifest(run_id="agent-run")
    manifest.register_artifact(
        StructureSetArtifact(
            artifact_id="structure-1",
            path="artifacts/structures.extxyz",
            sha256="d" * 64,
            producer="test",
        )
    )
    manifest_path = save_manifest(tmp_path, manifest)
    result = StepExecutorResult(
        status="success",
        concise_summary="created structures",
        artifacts=[str(tmp_path / "legacy-output.cif")],
        manifest_path=str(manifest_path),
    )

    hydrated = _hydrate_manifest_artifacts(result)

    assert hydrated.artifacts == [str(tmp_path / "legacy-output.cif")]
    assert hydrated.artifact_ids == ["structure-1"]
