import os
import subprocess
import sys
import types
from pathlib import Path

import pytest
import numpy as np
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator
from ase.io import write

from genkai.contracts.artifacts import (
    CalculationResultArtifact,
    CalculationInputArtifact,
    DatasetArtifact,
    EvidenceLevel,
    ExecutionState,
    ExternalResourceRef,
    ModelArtifact,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.run import RunManifest
from genkai.compute.vasp import collect_vasp_results, prepare_vasp_inputs
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
ROOT = Path(__file__).parents[2]


def _structures(
    *,
    sha256: str = SHA256,
    validation_status: ValidationStatus = ValidationStatus.PASSED,
    structure_count: int = 1,
) -> StructureSetArtifact:
    return StructureSetArtifact(
        artifact_id="structures",
        path="artifacts/structures.extxyz",
        sha256=sha256,
        producer="surface",
        execution_state=ExecutionState.SUCCEEDED,
        validation_status=validation_status,
        metadata={"structure_count": structure_count},
    )


def _dataset(
    *,
    evidence: EvidenceLevel = EvidenceLevel.DFT_CALCULATED,
    sha256: str = SHA256,
    validation_status: ValidationStatus = ValidationStatus.PASSED,
    **metadata_overrides: object,
) -> DatasetArtifact:
    metadata = {**REQUIRED_DATASET_METADATA, **metadata_overrides}
    return DatasetArtifact(
        artifact_id="dataset",
        path="artifacts/dataset.json",
        sha256=sha256,
        producer="dataset",
        evidence_level=evidence,
        execution_state=ExecutionState.SUCCEEDED,
        validation_status=validation_status,
        metadata=metadata,
    )


def _base_model(root: Path | None = None) -> ExternalResourceRef:
    if root is None:
        return ExternalResourceRef(
            uri="file:///shared/checkpoints/uma.pt",
            resource_type="uma-checkpoint",
            version="1.1",
        )
    sha256 = _write_artifact(root, "checkpoints/uma.pt", "checkpoint\n")
    return ExternalResourceRef(
        uri=(root / "checkpoints" / "uma.pt").resolve().as_uri(),
        resource_type="uma-checkpoint",
        version="1.1",
        sha256=sha256,
    )


def _write_artifact(root: Path, relative: str, content: str = "data\n") -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _executable(root: Path, name: str) -> Path:
    path = root / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _launcher(root: Path, name: str, *markers: str) -> Path:
    path = root / "bin" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n" + "\n".join(f"# {marker}" for marker in markers) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_mlip_adapters_enforce_distinct_roles(tmp_path: Path) -> None:
    structure_path = tmp_path / "artifacts/structures.extxyz"
    _write_labeled_structure(structure_path, 0.8)
    import hashlib

    structures = _structures(
        sha256=hashlib.sha256(structure_path.read_bytes()).hexdigest()
    )
    split_inventory = []
    for split in ("train", "validation", "test"):
        relative = f"splits/{split}/data.extxyz"
        split_inventory.append(
            {
                "kind": "source",
                "split": split,
                "path": relative,
                "sha256": _write_artifact(tmp_path, relative, f"{split}\n"),
            }
        )
    config_sha = _write_artifact(
        tmp_path, "config/uma.yaml", "base_model_name: uma-s-1p1\n"
    )
    deepmd_sha = _write_artifact(tmp_path, "config/deepmd.json", "{}\n")
    dataset = _dataset(
        sha256=_write_artifact(tmp_path, "artifacts/dataset.json"),
        audit_status="PASS",
        split_inventory=split_inventory,
        uma_config_path="config/uma.yaml",
        uma_config_sha256=config_sha,
        deepmd_input_path="config/deepmd.json",
        deepmd_input_sha256=deepmd_sha,
    )
    mace = MaceAdapter(
        _launcher(
            tmp_path,
            "mace",
            "MACE_WORK_DIR",
            "MACE_PYTHON_ARGS",
            "MACE_DRY_RUN",
        )
    ).prepare_inference(
        structures, tmp_path, RunMode.PRODUCTION
    )
    deepmd = DeepMDAdapter(
        _launcher(
            tmp_path,
            "deepmd",
            "DEEPMD_WORK_DIR",
            "DEEPMD_ARGS",
            "DEEPMD_REQUIRED_PATHS",
            "DEEPMD_DRY_RUN",
        )
    ).prepare_training(
        dataset, tmp_path, RunMode.PRODUCTION
    )
    uma_dataset = dataset.model_copy(
        update={"metadata": {**dataset.metadata, "lmdb_readback": True}}
    )
    uma = UmaAdapter(
        _launcher(
            tmp_path,
            "uma",
            "UMA_FINETUNE_WORK_DIR",
            "UMA_FINETUNE_CONFIG",
            "UMA_FINETUNE_DRY_RUN",
            "UMA_FINETUNE_BASE_MODEL_PATH",
            "UMA_FINETUNE_BASE_MODEL_SHA256",
        )
    ).prepare_finetuning(
        uma_dataset, _base_model(tmp_path), tmp_path, RunMode.DRY_RUN
    )

    assert mace.validation.passed is True
    assert deepmd.validation.passed is True
    assert uma.validation.passed is True
    assert mace.command and mace.environment["MACE_PYTHON_ARGS"]
    assert "--input " in mace.environment["MACE_PYTHON_ARGS"]
    assert "--structures" not in mace.environment["MACE_PYTHON_ARGS"]
    assert deepmd.command and deepmd.environment["DEEPMD_REQUIRED_PATHS"]
    assert uma.command and uma.environment["UMA_FINETUNE_CONFIG"]
    assert uma.environment["UMA_FINETUNE_BASE_MODEL_PATH"].endswith("uma.pt")


def test_adapter_specs_pass_established_launcher_dry_runs(tmp_path: Path) -> None:
    structure_path = tmp_path / "artifacts/structures.extxyz"
    _write_labeled_structure(structure_path, 0.8)
    import hashlib

    structures = _structures(
        sha256=hashlib.sha256(structure_path.read_bytes()).hexdigest()
    )
    inventory = []
    for split in ("train", "validation", "test"):
        relative = f"splits/{split}/data.extxyz"
        inventory.append(
            {
                "kind": "source",
                "split": split,
                "path": relative,
                "sha256": _write_artifact(tmp_path, relative, f"{split}\n"),
            }
        )
    deepmd_sha = _write_artifact(tmp_path, "config/deepmd.json", "{}\n")
    uma_sha = _write_artifact(tmp_path, "config/uma.yaml", "{}\n")
    dataset = _dataset(
        sha256=_write_artifact(tmp_path, "artifacts/dataset.json"),
        audit_status="PASS",
        split_inventory=inventory,
        deepmd_input_path="config/deepmd.json",
        deepmd_input_sha256=deepmd_sha,
        uma_config_path="config/uma.yaml",
        uma_config_sha256=uma_sha,
    )
    launchers = {
        "mace": ROOT
        / "agents/Agent/skills/mace/scripts/submit_mace_calculation.sh",
        "deepmd": ROOT
        / "agents/Agent/skills/deepmd/scripts/submit_deepmd_training.sh",
        "uma": ROOT
        / "agents/Agent/skills/uma/scripts/submit_uma_finetuning.sh",
    }
    stages = {
        "mace": MaceAdapter(launchers["mace"]).prepare_inference(
            structures, tmp_path, RunMode.DRY_RUN
        ),
        "deepmd": DeepMDAdapter(launchers["deepmd"]).prepare_training(
            dataset, tmp_path, RunMode.DRY_RUN
        ),
        "uma": UmaAdapter(launchers["uma"]).prepare_finetuning(
            dataset, _base_model(tmp_path), tmp_path, RunMode.DRY_RUN
        ),
    }

    mace_runtime = tmp_path / "runtime-mace"
    mace_python = _executable(mace_runtime, ".venv/bin/python")
    mace_script = tmp_path / "mace_task.py"
    mace_script.write_text("", encoding="utf-8")
    deepmd_runtime = tmp_path / "runtime-deepmd"
    deepmd_training = tmp_path / "training-deepmd"
    deepmd_training.mkdir()
    deepmd_activate = deepmd_runtime / "dp_venv/bin/activate"
    deepmd_activate.parent.mkdir(parents=True)
    deepmd_activate.write_text("", encoding="utf-8")
    deepmd_bin = _executable(deepmd_runtime, "dp_venv/bin/dp")
    uma_runtime = tmp_path / "runtime-uma"
    uma_python = _executable(uma_runtime, ".venv_uma/bin/python")
    uma_fairchem = _executable(uma_runtime, ".venv_uma/bin/fairchem")
    overrides = {
        "mace": {
            "MACE_RUNTIME_DIR": str(mace_runtime),
            "MACE_PYTHON_BIN": str(mace_python),
            "MACE_PYTHON_SCRIPT": str(mace_script),
            "MACE_DEVICE": "cpu",
        },
        "deepmd": {
            "DEEPMD_RUNTIME_DIR": str(deepmd_runtime),
            "DEEPMD_TRAINING_ROOT": str(deepmd_training),
            "DEEPMD_BIN": str(deepmd_bin),
        },
        "uma": {
            "UMA_RUNTIME_DIR": str(uma_runtime),
            "UMA_PYTHON_BIN": str(uma_python),
            "UMA_FINETUNE_BIN": str(uma_fairchem),
            "UMA_FINETUNE_DEVICE": "cpu",
        },
    }
    for name, stage in stages.items():
        assert stage.command is not None
        completed = subprocess.run(
            stage.command,
            cwd=tmp_path,
            env={**os.environ, **stage.environment, **overrides[name]},
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "DRY RUN PASS" in completed.stdout
        if name == "uma":
            assert str(tmp_path / "checkpoints/uma.pt") in completed.stdout


@pytest.mark.parametrize("adapter_name", ["mace", "deepmd", "uma"])
def test_production_adapters_reject_missing_artifacts(
    adapter_name: str, tmp_path: Path
) -> None:
    if adapter_name == "mace":
        result = MaceAdapter(_executable(tmp_path, "mace")).prepare_inference(
            _structures(), tmp_path, RunMode.PRODUCTION
        )
    elif adapter_name == "deepmd":
        result = DeepMDAdapter(_executable(tmp_path, "deepmd")).prepare_training(
            _dataset(audit_status="PASS"), tmp_path, RunMode.PRODUCTION
        )
    else:
        result = UmaAdapter(_executable(tmp_path, "uma")).prepare_finetuning(
            _dataset(audit_status="PASS"),
            _base_model(),
            tmp_path,
            RunMode.PRODUCTION,
        )

    assert "artifact_file_missing" in [
        issue.code for issue in result.validation.errors
    ]


def test_mace_production_rejects_unvalidated_or_empty_structures(
    tmp_path: Path,
) -> None:
    sha256 = _write_artifact(tmp_path, "artifacts/structures.extxyz")
    result = MaceAdapter(_executable(tmp_path, "mace")).prepare_inference(
        _structures(
            sha256=sha256,
            validation_status=ValidationStatus.NEEDS_REVIEW,
            structure_count=0,
        ),
        tmp_path,
        RunMode.PRODUCTION,
    )

    codes = [issue.code for issue in result.validation.errors]
    assert "artifact_not_validated" in codes
    assert "empty_structure_set" in codes


def test_production_adapter_requires_verified_executable(tmp_path: Path) -> None:
    sha256 = _write_artifact(tmp_path, "artifacts/dataset.json")
    result = DeepMDAdapter().prepare_training(
        _dataset(sha256=sha256, audit_status="PASS"),
        tmp_path,
        RunMode.PRODUCTION,
    )

    assert result.command is None
    assert "runtime_executable_required" in [
        issue.code for issue in result.validation.errors
    ]


def test_production_adapter_rejects_executable_without_launcher_protocol(
    tmp_path: Path,
) -> None:
    sha256 = _write_artifact(tmp_path, "artifacts/dataset.json")
    result = DeepMDAdapter("/bin/true").prepare_training(
        _dataset(sha256=sha256, audit_status="PASS"),
        tmp_path,
        RunMode.PRODUCTION,
    )

    assert result.command is None
    assert "runtime_launcher_protocol_mismatch" in [
        issue.code for issue in result.validation.errors
    ]


def test_uma_rejects_checkpoint_changed_after_identity_capture(
    tmp_path: Path,
) -> None:
    base_model = _base_model(tmp_path)
    (tmp_path / "checkpoints/uma.pt").write_text("changed\n", encoding="utf-8")
    result = UmaAdapter().prepare_finetuning(
        _dataset(audit_status="PASS"),
        base_model,
        tmp_path,
        RunMode.PRODUCTION,
    )

    assert "uma_base_model_hash_mismatch" in [
        issue.code for issue in result.validation.errors
    ]


def test_uma_hydra_preflight_asserts_bound_checkpoint_identity(
    tmp_path: Path,
) -> None:
    checkpoint_sha = _write_artifact(
        tmp_path, "checkpoints/uma.pt", "checkpoint\n"
    )
    config = tmp_path / "uma.yaml"
    config.write_text(
        "job:\n"
        "  scheduler: {mode: LOCAL}\n"
        "  device_type: CPU\n"
        "  run_dir: runs\n"
        "epochs: 1\n"
        "steps: null\n"
        "base_model_name: uma-s-1p1\n"
        "train_dataset:\n"
        "  dataset_configs: {omat: {}}\n"
        "val_dataset:\n"
        "  dataset_configs: {omat: {}}\n"
        "runner:\n"
        "  train_eval_unit:\n"
        "    model:\n"
        "      checkpoint_location: wrong.pt\n",
        encoding="utf-8",
    )
    script = (
        ROOT
        / "agents/Agent/skills/uma/scripts/validate_uma_finetune_launch.py"
    )
    uma_python = Path(
        os.environ.get(
            "GENKAI_UMA_TEST_PYTHON",
            "/home/pj24001724/ku40000345/wu/UMA-campare/.venv_uma/bin/python",
        )
    )
    if not uma_python.is_file():
        pytest.skip("configured UMA integration Python is unavailable")
    checkpoint = tmp_path / "checkpoints/uma.pt"
    completed = subprocess.run(
        [
            str(uma_python),
            str(script),
            "--config",
            str(config),
            "--mode",
            "train",
            "--override",
            f"runner.train_eval_unit.model.checkpoint_location={checkpoint}",
            "--expected-checkpoint",
            str(checkpoint),
            "--expected-checkpoint-sha256",
            checkpoint_sha,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"checkpoint : {checkpoint}" in completed.stdout


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
        sha256=_write_artifact(
            tmp_path, "stages/04_dft/mock-results.extxyz", "mock\n"
        ),
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


def test_dataset_build_cannot_promote_caller_metadata_without_audit(
    tmp_path: Path,
) -> None:
    source_sha = _write_artifact(
        tmp_path, "stages/04_dft/results.extxyz", "labels\n"
    )
    result = CalculationResultArtifact(
        artifact_id="result",
        path="stages/04_dft/results.extxyz",
        sha256=source_sha,
        producer="vasp",
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.DFT_CALCULATED,
        validation_status=ValidationStatus.PASSED,
        metadata={"label_source": "VASP OUTCAR"},
    )
    manifest = RunManifest(run_id="dataset-audit")
    manifest.register_artifact(result)
    save_manifest(tmp_path, manifest)

    dataset = build_dataset(result, REQUIRED_DATASET_METADATA, tmp_path)

    assert dataset.validation_status is ValidationStatus.NEEDS_REVIEW
    assert dataset.metadata["audit_status"] == "NOT_RUN"
    assert dataset.metadata["train_count"] == 0


def test_dataset_build_derives_counts_from_audited_splits(tmp_path: Path) -> None:
    source = tmp_path / "stages" / "04_dft" / "results.extxyz"
    _write_labeled_structure(source, 0.7)
    import hashlib

    result = CalculationResultArtifact(
        artifact_id="result",
        path=source.relative_to(tmp_path),
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        producer="vasp",
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.DFT_CALCULATED,
        validation_status=ValidationStatus.PASSED,
        metadata={"label_source": "VASP OUTCAR"},
    )
    manifest = RunManifest(run_id="dataset-audit")
    manifest.register_artifact(result)
    save_manifest(tmp_path, manifest)
    split_dirs = {}
    for name, distance in (("train", 0.7), ("validation", 0.8), ("test", 0.9)):
        file_path = tmp_path / "splits" / name / "data.extxyz"
        _write_labeled_structure(file_path, distance)
        split_dirs[name] = file_path.parent

    dataset = build_dataset(
        result,
        {
            **REQUIRED_DATASET_METADATA,
            "regression_tasks": "ef",
            "split_directories": split_dirs,
            "train_count": 999,
        },
        tmp_path,
    )

    assert dataset.validation_status is ValidationStatus.PASSED
    assert dataset.execution_state is ExecutionState.SUCCEEDED
    assert dataset.metadata["audit_status"] == "PASS"
    assert dataset.metadata["train_count"] == 1
    assert dataset.metadata["validation_count"] == 1
    assert dataset.metadata["test_count"] == 1
    assert len(dataset.metadata["split_inventory"]) == 3

    train_file = split_dirs["train"] / "data.extxyz"
    train_file.write_text("changed\n", encoding="utf-8")
    preflight = DeepMDAdapter(
        _launcher(
            tmp_path,
            "deepmd",
            "DEEPMD_WORK_DIR",
            "DEEPMD_ARGS",
            "DEEPMD_REQUIRED_PATHS",
            "DEEPMD_DRY_RUN",
        )
    ).prepare_training(dataset, tmp_path, RunMode.PRODUCTION)
    assert "dataset_split_hash_mismatch" in [
        issue.code for issue in preflight.validation.errors
    ]


def test_vasp_collection_rejects_preexisting_unparsed_result(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "stages" / "04_dft" / "results.extxyz"
    result_path.parent.mkdir(parents=True)
    result_path.write_text("fabricated\n", encoding="utf-8")
    input_artifact = CalculationInputArtifact(
        artifact_id="input",
        path="stages/04_dft/input-plan.json",
        sha256=SHA256,
        producer="test",
        metadata={"calculation_dirs": []},
    )

    with pytest.raises(ValueError, match="calculation_dirs"):
        collect_vasp_results(input_artifact, tmp_path)


def test_vasp_collection_parses_converged_outcar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calc_dir = tmp_path / "stages" / "04_dft" / "calc-1"
    calc_dir.mkdir(parents=True)
    (calc_dir / "OUTCAR").write_text(
        "aborting loop because EDIFF is reached\n", encoding="utf-8"
    )
    input_path = tmp_path / "stages" / "04_dft" / "input-plan.json"
    input_path.write_text("{}\n", encoding="utf-8")
    import hashlib

    input_artifact = CalculationInputArtifact(
        artifact_id="input",
        path=input_path.relative_to(tmp_path),
        sha256=hashlib.sha256(input_path.read_bytes()).hexdigest(),
        producer="test",
        execution_state=ExecutionState.SUCCEEDED,
        validation_status=ValidationStatus.PASSED,
        metadata={"calculation_dirs": ["stages/04_dft/calc-1"]},
    )
    manifest = RunManifest(run_id="vasp-collect")
    manifest.register_artifact(input_artifact)
    save_manifest(tmp_path, manifest)

    class FakeSystem:
        nopbc = False
        data = {
            "atom_names": ["H"],
            "atom_types": np.array([0]),
            "coords": np.array([[[0.0, 0.0, 0.0]]]),
            "cells": np.array([np.eye(3) * 8.0]),
            "energies": np.array([-1.0]),
            "forces": np.zeros((1, 1, 3)),
        }

        def __len__(self) -> int:
            return 1

    fake_dpdata = types.SimpleNamespace(
        LabeledSystem=lambda *_args, **_kwargs: FakeSystem()
    )
    monkeypatch.setitem(sys.modules, "dpdata", fake_dpdata)

    result = collect_vasp_results(input_artifact, tmp_path)

    assert result.evidence_level is EvidenceLevel.DFT_CALCULATED
    assert result.validation_status is ValidationStatus.PASSED
    assert (tmp_path / result.path).is_file()
