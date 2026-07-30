from pathlib import Path

from click.testing import CliRunner

from genkai.cli import main
from genkai.mlip.protocol import RunMode
from genkai.workflows.paper_to_mlip import (
    build_paper_to_mlip_graph,
    initialize_paper_to_mlip_run,
    preflight_paper_to_mlip,
)


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "paper_to_mlip"


def test_target_graphs_have_distinct_mlip_routes() -> None:
    mace = build_paper_to_mlip_graph("mace")
    deepmd = build_paper_to_mlip_graph("deepmd")
    uma = build_paper_to_mlip_graph("uma")

    assert mace.stages[-1].adapter == "mace"
    assert str(mace.stages[-1].consumes[0]) == "structure-set@1"
    assert deepmd.stages[-1].adapter == "deepmd"
    assert str(deepmd.stages[-1].consumes[0]) == "dataset@1"
    assert uma.stages[-1].adapter == "uma"
    assert {str(item) for item in uma.stages[-1].consumes} == {
        "dataset@1",
        "model@1",
    }


def test_mock_labels_are_rejected_only_for_production_training(
    tmp_path: Path,
) -> None:
    initialize_paper_to_mlip_run(
        tmp_path,
        FIXTURE_DIR / "minimal_surface_relations.jsonl",
        mock_labels=FIXTURE_DIR / "mock_labels.extxyz",
        base_model_uri="file:///shared/uma/checkpoint.pt",
    )

    production = preflight_paper_to_mlip(
        tmp_path, "uma", RunMode.PRODUCTION
    )
    dry_run = preflight_paper_to_mlip(tmp_path, "uma", RunMode.DRY_RUN)

    assert production.passed is False
    assert "mock_labels_not_trainable" in [
        issue.code for issue in production.errors
    ]
    assert dry_run.passed is True
    assert "mock_labels_not_trainable" in [
        issue.code for issue in dry_run.warnings
    ]


def test_cli_preflight_uses_nonzero_exit_for_mock_production(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    init = runner.invoke(
        main,
        [
            "init",
            str(tmp_path),
            "--relations",
            str(FIXTURE_DIR / "minimal_surface_relations.jsonl"),
            "--mock-labels",
            str(FIXTURE_DIR / "mock_labels.extxyz"),
            "--base-model-uri",
            "file:///shared/uma/checkpoint.pt",
        ],
    )
    production = runner.invoke(
        main,
        [
            "preflight",
            "--run-root",
            str(tmp_path),
            "--target",
            "uma",
            "--mode",
            "production",
        ],
    )

    assert init.exit_code == 0, init.output
    assert production.exit_code != 0
    assert "mock_labels_not_trainable" in production.output
