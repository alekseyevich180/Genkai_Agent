"""Offline interface contracts; backend doubles never load or evaluate a model."""

from dataclasses import asdict
from types import ModuleType, SimpleNamespace
import sys
from unittest.mock import Mock

import pytest

from genkai.modeling.surface import adsorbate, amorphous_screen, calculators, cluster_search, sam_search, slab, vacancy


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "local.model"
    path.write_bytes(b"interface test only; not a model")
    return path


@pytest.fixture
def mace_backend(monkeypatch):
    factory = Mock(return_value=object())
    module = ModuleType("mace.calculators")
    module.MACECalculator = factory
    monkeypatch.setitem(sys.modules, "mace", ModuleType("mace"))
    monkeypatch.setitem(sys.modules, "mace.calculators", module)
    # Selecting MACE must work without FAIRChem, even for an unknown UMA task.
    monkeypatch.setitem(sys.modules, "fairchem", None)
    return factory


def test_mace_requires_an_existing_explicit_checkpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("MACE_MODEL", raising=False)
    monkeypatch.setitem(sys.modules, "mace", None)
    with pytest.raises(ValueError, match="MACE_MODEL"):
        calculators.build_calculator("mace")
    with pytest.raises(FileNotFoundError, match="MACE checkpoint"):
        calculators.build_calculator("mace", mace_model=tmp_path / "missing.model")


def test_explicit_mace_model_overrides_environment(checkpoint, monkeypatch, mace_backend):
    monkeypatch.setenv("MACE_MODEL", "/missing/environment.model")
    calculators.build_calculator("mace", mace_model=checkpoint, device="cpu", mace_dtype="float64")
    mace_backend.assert_called_once_with(model_paths=str(checkpoint), device="cpu", default_dtype="float64")


@pytest.mark.parametrize("entry", ["shared", "slab", "adsorbate", "vacancy", "cluster"])
def test_energy_entrypoints_use_mace_without_uma(entry, checkpoint, monkeypatch, mace_backend):
    monkeypatch.setenv("MACE_MODEL", str(checkpoint))
    if entry == "shared":
        calc = calculators.build_calculator("mace", task_name="unused", device="cpu")
    elif entry == "slab":
        calc = slab.build_energy_calculator("mace", "unused", "unused", "cpu")
    elif entry == "cluster":
        calc = cluster_search.build_calculator("unused", "cpu", False, calculator_name="mace", task_name="unused")
    else:
        module = adsorbate if entry == "adsorbate" else vacancy
        calc = module.build_calculator("mace", "unused", "cpu", "unused", False)
    assert calc is mace_backend.return_value
    mace_backend.assert_called_once_with(model_paths=str(checkpoint), device="cpu", default_dtype="float32")
    assert calculators.evidence_for("mace") == "mlip_predicted"


def test_invalid_mace_options_fail_before_model_loading(checkpoint, mace_backend):
    with pytest.raises(ValueError, match="mace_dtype"):
        calculators.build_calculator("mace", mace_model=checkpoint, mace_dtype="float16")
    with pytest.raises(ValueError, match="UMA"):
        calculators.build_calculator("mace", mace_model=checkpoint, checkpoint="uma.pt")
    mace_backend.assert_not_called()


@pytest.mark.parametrize("checkpoint_path", [None, "local-uma.pt"])
def test_uma_model_and_checkpoint_routes(monkeypatch, checkpoint_path):
    module = ModuleType("fairchem.core")
    module.FAIRChemCalculator = Mock()
    module.pretrained_mlip = SimpleNamespace(get_predict_unit=Mock())
    monkeypatch.setitem(sys.modules, "fairchem", ModuleType("fairchem"))
    monkeypatch.setitem(sys.modules, "fairchem.core", module)
    monkeypatch.setattr(calculators, "available_uma_tasks", lambda: ["omat"])
    calculators.build_calculator("uma", uma_model="uma-s-1p1", task_name="omat", device="cpu", checkpoint=checkpoint_path)
    if checkpoint_path:
        module.FAIRChemCalculator.from_model_checkpoint.assert_called_once_with(checkpoint_path, task_name="omat", device="cpu")
        module.pretrained_mlip.get_predict_unit.assert_not_called()
    else:
        module.pretrained_mlip.get_predict_unit.assert_called_once_with("uma-s-1p1", device="cpu")
        module.FAIRChemCalculator.assert_called_once_with(module.pretrained_mlip.get_predict_unit.return_value, task_name="omat")
    with pytest.raises(ValueError, match="oc22"):
        calculators.build_calculator("uma", task_name="oc22")


def test_optional_dispersion_wraps_mace(checkpoint, mace_backend, monkeypatch):
    module = ModuleType("ase.calculators.dftd3")
    module.DFTD3 = Mock()
    monkeypatch.setitem(sys.modules, "ase.calculators.dftd3", module)
    result = calculators.build_calculator("mace", mace_model=checkpoint, include_d3=True)
    module.DFTD3.assert_called_once_with(dft=mace_backend.return_value)
    assert result is module.DFTD3.return_value


def test_model_settings_record_resolved_environment_model(checkpoint, monkeypatch, mace_backend):
    monkeypatch.setenv("MACE_MODEL", str(checkpoint))
    settings = amorphous_screen.ModelSettings(calculator="mace", device="cpu")
    assert asdict(settings)["mace_model"] == str(checkpoint)
    assert settings.build() is mace_backend.return_value
    search = sam_search.SamSearchSettings(calculator="mace")
    assert asdict(search)["mace_model"] == str(checkpoint)


def test_sam_cli_passes_mace_settings_to_search(checkpoint, tmp_path, monkeypatch):
    captured = {}

    def stop_after_settings(substrate, molecule, sam, search, output, **kwargs):
        captured.update(asdict(search))
        raise RuntimeError("interface boundary reached")

    monkeypatch.setattr(sam_search, "substrate_from_args", lambda args: object())
    monkeypatch.setattr(sam_search, "run_sam_search", stop_after_settings)
    with pytest.raises(RuntimeError, match="interface boundary"):
        sam_search.main([
            "--surface", "input.cif", "--molecule", "molecule.xyz", "--binding-mode", "monodentate",
            "--search-calculator", "mace", "--mace-model", str(checkpoint), "--mace-dtype", "float64",
            "--device", "cpu", "--output-dir", str(tmp_path),
        ])
    assert captured["calculator"] == "mace"
    assert captured["mace_model"] == str(checkpoint)
    assert captured["mace_dtype"] == "float64"
    assert captured["device"] == "cpu"


@pytest.mark.parametrize("command", ["surfaces", "interface"])
def test_amorphous_cli_passes_mace_settings(command, checkpoint, mace_backend):
    flags = ["--calculator", "mace"] if command == "surfaces" else ["--surface", "slab.cif", "--search-calculator", "mace"]
    args = amorphous_screen._build_parser().parse_args([
        command, "--amorphous", "bulk.cif", "--output-dir", "output", "--device", "cpu",
        "--mace-model", str(checkpoint), "--mace-dtype", "float64", *flags,
    ])
    model = amorphous_screen._model_from_args(args)
    assert model.build() is mace_backend.return_value
    mace_backend.assert_called_once_with(model_paths=str(checkpoint), device="cpu", default_dtype="float64")


def test_legacy_mock_behavior_stays_distinct():
    assert slab.build_energy_calculator("none", "unused", "unused", "cpu") is None
    assert isinstance(adsorbate.build_calculator("none", "unused", "cpu", "unused", False), adsorbate.AdsorptionTestCalculator)
    assert isinstance(vacancy.build_calculator("none", "unused", "cpu", "unused", False), vacancy.CompositionTestCalculator)
    with pytest.raises(ValueError, match="Unknown calculator"):
        calculators.build_calculator("typo")
