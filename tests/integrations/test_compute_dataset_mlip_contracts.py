import os
import subprocess
import sys
from pathlib import Path

import pytest
import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import write

from genkai.contracts.artifacts import (
    CalculationResultArtifact,
    DatasetArtifact,
    EvidenceLevel,
    ExternalResourceRef,
    ModelArtifact,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.run import RunManifest
from genkai.compute.vasp import prepare_vasp_inputs
from genkai.datasets.ase import audit_dataset_splits, build_dataset
from genkai.mlip.deepmd import DeepMDAdapter
from genkai.mlip.mace import MaceAdapter
from genkai.mlip.protocol import RunMode
from genkai.mlip.uma import UmaAdapter
from genkai.workflow.store import load_manifest, save_manifest


SHA256 = "c" * 64
REQUIRED_DATASET_METADATA = {
    "label_source": "VASP",
    "energy_unit": "eV",
    "force_unit": "eV/angstrom",
    "stress_unit": "eV/angstrom^3",
    "electronic_structure_method": "DFT",
    "functional": "PBE",
    "pseudopotential_family": "PAW",
    "split_strategy": "grouped-by-origin",
    "train_count": 8,
    "validation_count": 2,
    "test_count": 2,
    "cross_split_leakage": 0,
    "lmdb_readback": True,
}


def _structures() -> StructureSetArtifact:
    return StructureSetArtifact(
        artifact_id="structures",
        path="artifacts/structures.extxyz",
        sha256=SHA256,
        producer="surface",
    )


def _dataset(
    *,
    evidence: EvidenceLevel = EvidenceLevel.DFT_CALCULATED,
    **metadata_overrides: object,
) -> DatasetArtifact:
    metadata = {**REQUIRED_DATASET_METADATA, **metadata_overrides}
    return DatasetArtifact(
        artifact_id="dataset",
        path="artifacts/dataset.json",
        sha256=SHA256,
        producer="dataset",
        evidence_level=evidence,
        validation_status=ValidationStatus.PASSED,
        metadata=metadata,
    )


def _base_model() -> ExternalResourceRef:
    return ExternalResourceRef(
        uri="file:///shared/checkpoints/uma.pt",
        resource_type="uma-checkpoint",
        version="1.1",
    )


def test_mlip_adapters_enforce_distinct_roles(tmp_path: Path) -> None:
    mace = MaceAdapter().prepare_inference(_structures(), tmp_path, RunMode.DRY_RUN)
    deepmd = DeepMDAdapter().prepare_training(
        _dataset(), tmp_path, RunMode.PRODUCTION
    )
    uma = UmaAdapter().prepare_finetuning(
        _dataset(), _base_model(), tmp_path, RunMode.PRODUCTION
    )

    assert mace.validation.passed is True
    assert deepmd.validation.passed is True
    assert uma.validation.passed is True
    assert mace.command and "mace" in mace.command[0].lower()
    assert deepmd.command and "deepmd" in deepmd.command[0].lower()
    assert uma.command and "uma" in uma.command[0].lower()


@pytest.mark.parametrize("adapter_name", ["deepmd", "uma"])
def test_training_adapters_reject_mock_labels_in_production(
    adapter_name: str, tmp_path: Path
) -> None:
    dataset = _dataset(evidence=EvidenceLevel.MOCK)
    if adapter_name == "deepmd":
        result = DeepMDAdapter().prepare_training(
            dataset, tmp_path, RunMode.PRODUCTION
        )
    else:
        result = UmaAdapter().prepare_finetuning(
            dataset, _base_model(), tmp_path, RunMode.PRODUCTION
        )

    assert result.validation.passed is False
    assert "mock_labels_not_trainable" in [
        issue.code for issue in result.validation.errors
    ]


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"test_count": 0}, "uma_test_split_required"),
        ({"cross_split_leakage": 1}, "uma_split_leakage"),
        ({"lmdb_readback": False}, "uma_lmdb_readback_required"),
    ],
)
def test_uma_requires_test_split_no_leakage_and_lmdb_readback(
    overrides: dict[str, object], error_code: str, tmp_path: Path
) -> None:
    result = UmaAdapter().prepare_finetuning(
        _dataset(**overrides), _base_model(), tmp_path, RunMode.PRODUCTION
    )

    assert error_code in [issue.code for issue in result.validation.errors]


def test_vasp_help_does_not_import_optional_dpdata(tmp_path: Path) -> None:
    (tmp_path / "dpdata.py").write_text(
        "raise RuntimeError('dpdata imported eagerly')\n", encoding="utf-8"
    )
    script = (
        Path(__file__).parents[2]
        / "agents"
        / "Agent"
        / "skills"
        / "vasp"
        / "scripts"
        / "vasp_tools.py"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "collect_results" in completed.stdout


def _write_labeled_structure(path: Path, distance: float) -> None:
    atoms = Atoms(
        "H2",
        positions=[[0.0, 0.0, 0.0], [distance, 0.0, 0.0]],
        cell=[8.0, 8.0, 8.0],
        pbc=True,
    )
    atoms.calc = SinglePointCalculator(
        atoms,
        energy=-1.0,
        forces=np.zeros((2, 3)),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path, atoms, format="extxyz")


def test_shared_dataset_audit_detects_cross_split_leakage(tmp_path: Path) -> None:
    train = tmp_path / "train" / "data.extxyz"
    val = tmp_path / "val" / "data.extxyz"
    test = tmp_path / "test" / "data.extxyz"
    _write_labeled_structure(train, 0.8)
    _write_labeled_structure(val, 0.9)
    _write_labeled_structure(test, 0.8)

    report = audit_dataset_splits(
        {"train": train.parent, "val": val.parent, "test": test.parent},
        regression_tasks="ef",
    )

    assert report["status"] == "FAIL"
    assert report["cross_split_exact_duplicates"] == 1


def test_vasp_prepare_and_dataset_build_only_prepare_run_artifacts(
    tmp_path: Path,
) -> None:
    structures = _structures()
    manifest = RunManifest(run_id="adapter-run")
    manifest.register_artifact(structures)
    save_manifest(tmp_path, manifest)

    calculation_input = prepare_vasp_inputs(structures, tmp_path)
    mock_result = CalculationResultArtifact(
        artifact_id="mock-result",
        path="stages/04_dft/mock-results.extxyz",
        sha256=SHA256,
        producer="test",
        parent_ids=[calculation_input.artifact_id],
        evidence_level=EvidenceLevel.MOCK,
        metadata={"label_source": "mock"},
    )
    manifest = load_manifest(tmp_path)
    manifest.register_artifact(mock_result)
    save_manifest(tmp_path, manifest)
    dataset = build_dataset(
        mock_result,
        {
            **REQUIRED_DATASET_METADATA,
            "label_source": "mock",
        },
        tmp_path,
    )

    assert calculation_input.execution_state.value == "prepared"
    assert dataset.evidence_level is EvidenceLevel.MOCK
    assert dataset.validation_status is ValidationStatus.NEEDS_REVIEW
    assert (tmp_path / calculation_input.path).is_file()
    assert (tmp_path / dataset.path).is_file()
