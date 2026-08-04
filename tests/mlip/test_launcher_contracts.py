from pathlib import Path

from genkai.mlip.launchers import LAUNCHER_CONTRACTS, get_launcher_contract


def test_registry_covers_all_adapter_roles() -> None:
    assert set(LAUNCHER_CONTRACTS) == {"mace", "deepmd", "uma"}
    assert get_launcher_contract("mace").environment_variable == "GENKAI_MACE_LAUNCHER"
    assert "MACE_WORK_DIR" in get_launcher_contract("mace").required_markers


def test_unknown_launcher_is_rejected() -> None:
    try:
        get_launcher_contract("vasp")
    except KeyError:
        pass
    else:
        raise AssertionError("unknown launcher must fail closed")


def test_skill_validation_uses_canonical_dataset_audit() -> None:
    path = Path("agents/Agent/skills/uma/scripts/validate_uma_finetune_data.py")
    source = path.read_text(encoding="utf-8")
    assert "from genkai.datasets.ase import audit_dataset_splits" in source
