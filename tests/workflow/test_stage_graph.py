from genkai.workflow.graph import WorkflowGraph, validate_workflow
from genkai.workflow.stage import ArtifactRequirement, StageSpec


def requirement(value: str) -> ArtifactRequirement:
    return ArtifactRequirement.parse(value)


def test_extraction_flows_from_paperread_to_ptomodel() -> None:
    graph = WorkflowGraph(
        stages=[
            StageSpec(
                stage_id="paperread",
                adapter="paperread",
                produces=[requirement("extraction@1")],
            ),
            StageSpec(
                stage_id="ptomodel",
                adapter="ptomodel",
                depends_on=["paperread"],
                consumes=[requirement("extraction@1")],
                produces=[requirement("modeling-plan@1")],
            ),
        ]
    )

    assert validate_workflow(graph).passed is True


def test_dependency_with_wrong_artifact_type_is_reported() -> None:
    graph = WorkflowGraph(
        stages=[
            StageSpec(
                stage_id="surface",
                adapter="surface",
                produces=[requirement("structure-set@1")],
            ),
            StageSpec(
                stage_id="train",
                adapter="deepmd",
                depends_on=["surface"],
                consumes=[requirement("dataset@1")],
            ),
        ]
    )

    report = validate_workflow(graph)

    assert report.passed is False
    assert [issue.code for issue in report.errors] == ["artifact_type_mismatch"]


def test_incompatible_schema_major_is_reported_separately() -> None:
    graph = WorkflowGraph(
        stages=[
            StageSpec(
                stage_id="dataset",
                adapter="dataset",
                produces=[requirement("dataset@1")],
            ),
            StageSpec(
                stage_id="train",
                adapter="deepmd",
                depends_on=["dataset"],
                consumes=[requirement("dataset@2")],
            ),
        ]
    )

    report = validate_workflow(graph)

    assert [issue.code for issue in report.errors] == [
        "schema_version_incompatible"
    ]


def test_cycle_is_reported_before_execution() -> None:
    graph = WorkflowGraph(
        stages=[
            StageSpec(
                stage_id="a",
                adapter="a",
                depends_on=["b"],
                consumes=[requirement("b-output@1")],
                produces=[requirement("a-output@1")],
            ),
            StageSpec(
                stage_id="b",
                adapter="b",
                depends_on=["a"],
                consumes=[requirement("a-output@1")],
                produces=[requirement("b-output@1")],
            ),
        ]
    )

    report = validate_workflow(graph)

    assert "workflow_cycle" in [issue.code for issue in report.errors]
