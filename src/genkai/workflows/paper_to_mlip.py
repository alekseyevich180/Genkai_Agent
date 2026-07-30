"""Offline reference workflow from saved paper extraction to MLIP preflight."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Literal

from genkai.compute.vasp import prepare_vasp_inputs
from genkai.contracts.artifacts import (
    CalculationResultArtifact,
    DatasetArtifact,
    EvidenceLevel,
    ExecutionState,
    ExternalResourceRef,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.run import StageRecord
from genkai.contracts.validation import ValidationIssue, ValidationReport
from genkai.datasets.ase import build_dataset
from genkai.mlip.deepmd import DeepMDAdapter
from genkai.mlip.mace import MaceAdapter
from genkai.mlip.protocol import RunMode
from genkai.mlip.uma import UmaAdapter
from genkai.workflow.graph import WorkflowGraph, validate_workflow
from genkai.workflow.stage import ArtifactRequirement, StageSpec
from genkai.workflow.store import load_manifest, save_manifest


Target = Literal["mace", "deepmd", "uma"]


def _requirement(value: str) -> ArtifactRequirement:
    return ArtifactRequirement.parse(value)


def build_paper_to_mlip_graph(target: Target) -> WorkflowGraph:
    stages = [
        StageSpec(
            stage_id="paperread",
            adapter="paperread",
            produces=["extraction@1"],
        ),
        StageSpec(
            stage_id="ptomodel",
            adapter="ptomodel",
            depends_on=["paperread"],
            consumes=["extraction@1"],
            produces=["modeling-plan@1"],
        ),
        StageSpec(
            stage_id="surface",
            adapter="surface",
            depends_on=["ptomodel"],
            consumes=["modeling-plan@1"],
            produces=["structure-set@1"],
        ),
    ]
    if target == "mace":
        stages.append(
            StageSpec(
                stage_id="mace",
                adapter="mace",
                depends_on=["surface"],
                consumes=["structure-set@1"],
                produces=["calculation-result@1"],
                allows_mock_inputs=True,
            )
        )
        return WorkflowGraph(stages=stages)

    stages.extend(
        [
            StageSpec(
                stage_id="vasp-prepare",
                adapter="vasp",
                depends_on=["surface"],
                consumes=["structure-set@1"],
                produces=["calculation-input@1"],
            ),
            StageSpec(
                stage_id="vasp-collect",
                adapter="vasp",
                depends_on=["vasp-prepare"],
                consumes=["calculation-input@1"],
                produces=["calculation-result@1"],
            ),
            StageSpec(
                stage_id="dataset",
                adapter="dataset",
                depends_on=["vasp-collect"],
                consumes=["calculation-result@1"],
                produces=["dataset@1"],
            ),
        ]
    )
    if target == "deepmd":
        stages.append(
            StageSpec(
                stage_id="deepmd",
                adapter="deepmd",
                depends_on=["dataset"],
                consumes=["dataset@1"],
                produces=["model@1"],
            )
        )
        return WorkflowGraph(stages=stages)

    stages.append(
        StageSpec(
            stage_id="uma",
            adapter="uma",
            depends_on=["dataset"],
            consumes=["dataset@1", "model@1"],
            produces=["model@1", "evaluation@1"],
        )
    )
    return WorkflowGraph(stages=stages, inputs=[_requirement("model@1")])


def initialize_paper_to_mlip_run(
    run_root: str | Path,
    relations: str | Path,
    *,
    mock_labels: str | Path | None = None,
    base_model_uri: str | None = None,
) -> None:
    from genkai.literature.surface import run_surface_extraction
    from genkai.modeling.ptomodel import build_modeling_plan
    from genkai.modeling.surface import build_surface_candidates

    root = Path(run_root)
    extraction = run_surface_extraction(relations, root)
    plan = build_modeling_plan(extraction, root)
    structures = build_surface_candidates(plan, root, mode="dry-run")
    if mock_labels is not None:
        calculation_input = prepare_vasp_inputs(structures, root)
        result_path = root / "stages" / "04_dft" / "mock-results.extxyz"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(mock_labels, result_path)
        manifest = load_manifest(root)
        mock_result = CalculationResultArtifact(
            artifact_id=f"{manifest.run_id}:mock-result",
            path=result_path.relative_to(root),
            sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
            producer="genkai.workflows.paper_to_mlip",
            parent_ids=[calculation_input.artifact_id],
            execution_state=ExecutionState.SUCCEEDED,
            evidence_level=EvidenceLevel.MOCK,
            validation_status=ValidationStatus.NEEDS_REVIEW,
            metadata={"label_source": "mock fixture"},
        )
        manifest.register_artifact(mock_result)
        manifest.append_stage(
            StageRecord(
                stage_id="04_dft_mock",
                adapter="genkai.workflows.paper_to_mlip",
                execution_state=ExecutionState.SUCCEEDED,
                input_artifact_ids=[calculation_input.artifact_id],
                output_artifact_ids=[mock_result.artifact_id],
            )
        )
        save_manifest(root, manifest)
        build_dataset(
            mock_result,
            {
                "label_source": "mock",
                "energy_unit": "eV",
                "force_unit": "eV/angstrom",
                "stress_unit": "eV/angstrom^3",
                "electronic_structure_method": "mock",
                "functional": "not_applicable",
                "pseudopotential_family": "not_applicable",
                "split_strategy": "fixture",
                "train_count": 1,
                "validation_count": 1,
                "test_count": 1,
                "cross_split_leakage": 0,
                "lmdb_readback": True,
            },
            root,
        )
    if base_model_uri:
        manifest = load_manifest(root)
        manifest.metadata["base_model_uri"] = base_model_uri
        save_manifest(root, manifest)


def _latest(manifest, artifact_type: str):
    return next(
        (
            artifact
            for artifact in reversed(manifest.artifacts)
            if artifact.artifact_type == artifact_type
        ),
        None,
    )


def preflight_paper_to_mlip(
    run_root: str | Path,
    target: Target,
    mode: RunMode,
) -> ValidationReport:
    graph_report = validate_workflow(build_paper_to_mlip_graph(target))
    errors = list(graph_report.errors)
    warnings = list(graph_report.warnings)
    checks = list(graph_report.checks)
    manifest = load_manifest(Path(run_root))

    result = None
    if target == "mace":
        structures = _latest(manifest, "structure-set")
        if isinstance(structures, StructureSetArtifact):
            result = MaceAdapter().prepare_inference(structures, Path(run_root), mode)
        else:
            errors.append(
                ValidationIssue(
                    code="structure_set_required",
                    message="MACE preflight requires a structure-set artifact",
                )
            )
    else:
        dataset = _latest(manifest, "dataset")
        if not isinstance(dataset, DatasetArtifact):
            errors.append(
                ValidationIssue(
                    code="dataset_required",
                    message=f"{target} preflight requires a dataset artifact",
                )
            )
        elif target == "deepmd":
            result = DeepMDAdapter().prepare_training(dataset, Path(run_root), mode)
        else:
            uri = manifest.metadata.get("base_model_uri")
            if not isinstance(uri, str) or not uri:
                errors.append(
                    ValidationIssue(
                        code="uma_base_model_required",
                        message="UMA preflight requires a base model URI",
                    )
                )
            else:
                result = UmaAdapter().prepare_finetuning(
                    dataset,
                    ExternalResourceRef(
                        uri=uri,
                        resource_type="uma-checkpoint",
                    ),
                    Path(run_root),
                    mode,
                )
    if result is not None:
        errors.extend(result.validation.errors)
        warnings.extend(result.validation.warnings)
        checks.extend(result.validation.checks)
    report = ValidationReport(errors=errors, warnings=warnings, checks=checks)
    stage_id = f"06_{target}_preflight_{mode.value.replace('-', '_')}"
    manifest.stages = [
        stage for stage in manifest.stages if stage.stage_id != stage_id
    ]
    input_ids = []
    if target == "mace":
        structures = _latest(manifest, "structure-set")
        if structures is not None:
            input_ids.append(structures.artifact_id)
    else:
        dataset = _latest(manifest, "dataset")
        if dataset is not None:
            input_ids.append(dataset.artifact_id)
    manifest.append_stage(
        StageRecord(
            stage_id=stage_id,
            adapter=f"genkai.mlip.{target}",
            execution_state=(
                ExecutionState.PREPARED
                if report.passed
                else ExecutionState.BLOCKED
            ),
            input_artifact_ids=input_ids,
            validation=report,
            metadata={
                "mode": mode.value,
                "external_execution_started": False,
            },
        )
    )
    save_manifest(Path(run_root), manifest)
    return report
