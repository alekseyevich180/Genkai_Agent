"""Structure-only execution of surface-modeling plans (no energy model, offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ase.constraints import FixAtoms
from ase.io import read
from click.testing import CliRunner
from pymatgen.core import Lattice, Structure

from genkai.cli import main as cli_main
from genkai.contracts.artifacts import EvidenceLevel, ExecutionState, StructureSetArtifact
from genkai.mlip.protocol import RunMode
from genkai.modeling.surface.executor import (
    SurfaceExecutionBlocked,
    SurfaceExecutionOverrides,
    execute_surface_plan,
    resolve_gas_molecule,
)
from genkai.modeling.surface.slab import build_slab, write_slab_outputs
from genkai.workflow.store import load_manifest
from genkai.workflows.paper_to_mlip import initialize_paper_to_mlip_run, preflight_paper_to_mlip


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "surface_execution" / "sno2_sam_gas_relations.jsonl"


def _rutile_sno2() -> Structure:
    return Structure.from_spacegroup(
        "P4_2/mnm", Lattice.tetragonal(4.737, 3.186), ["Sn", "O"], [[0, 0, 0], [0.3057, 0.3057, 0]]
    )


@pytest.fixture
def gas_run(tmp_path: Path, monkeypatch):
    """Offline run of the SnO2 SAM gas-sensor paper: extraction -> plan -> prepared candidates."""
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / ".matplotlib"))
    root = tmp_path / "run"
    initialize_paper_to_mlip_run(root, FIXTURE)
    manifest = load_manifest(root)
    plan = next(item for item in reversed(manifest.artifacts) if item.artifact_type == "modeling-plan")
    bulk = tmp_path / "SnO2_bulk.cif"
    _rutile_sno2().to(filename=str(bulk))
    return root, plan, bulk


def _manifest_text(root: Path) -> str:
    return (root / "manifest.json").read_text(encoding="utf-8")


def test_executor_blocks_until_reviewed_inputs_are_supplied(gas_run) -> None:
    root, plan, _ = gas_run
    before = _manifest_text(root)

    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(plan, root, SurfaceExecutionOverrides())

    missing = blocked.value.missing
    assert set(missing) == {"bulk", "surface_facet", "molecule", "coverage_counts"}
    assert "HRTEM" in missing["surface_facet"]  # the observed lattice plane is not used
    assert "acetone" in missing["molecule"]  # paper gases are listed, not auto-picked
    assert _manifest_text(root) == before
    assert not (root / "stages" / "03_surface_structures").exists()


def test_executor_generates_slab_and_gas_adsorbate_structures(gas_run) -> None:
    root, plan, bulk = gas_run

    artifact = execute_surface_plan(
        plan,
        root,
        SurfaceExecutionOverrides(
            bulk=bulk,
            surface_facet="(110)",
            molecule_name="NO2",
            coverage_counts=(1, 2),
            patterns=("uniform", "random"),
            random_repeats=1,
        ),
    )

    assert isinstance(artifact, StructureSetArtifact)
    assert artifact.execution_state is ExecutionState.SUCCEEDED
    assert artifact.evidence_level is EvidenceLevel.HEURISTIC
    assert artifact.metadata["calculator"] == "none"
    assert artifact.metadata["scientific_calculation_started"] is False
    assert artifact.metadata["facet"] == [1, 1, 0]
    assert artifact.metadata["facet_source"] == "override"
    assert artifact.metadata["site_symbols"] == ["Sn"]  # plan's spurious "S" was dropped

    frames = read(root / artifact.path, index=":")
    assert len(frames) == artifact.metadata["structure_count"] >= 3
    clean, adsorbed = frames[0], frames[1:]
    assert clean.info["role"] == "clean_slab"
    fixed_count = len(clean.constraints[0].get_indices())
    assert fixed_count > 0
    for frame in adsorbed:
        assert frame.info["role"] == "adsorbate_on_slab"
        assert "N" in frame.get_chemical_symbols()
        assert set(frame.get_tags()[len(clean):]) == {2}
        assert isinstance(frame.constraints[0], FixAtoms)
        assert len(frame.constraints[0].get_indices()) == fixed_count
        assert frame.calc is None and "energy" not in frame.info  # no mock energies leak

    manifest = load_manifest(root)
    stage = manifest.stages[-1]
    assert stage.stage_id == "03_surface_structures"
    assert stage.execution_state is ExecutionState.SUCCEEDED
    assert manifest.artifacts[-1].artifact_id == artifact.artifact_id
    report = json.loads((root / artifact.metadata["execution_report"]).read_text(encoding="utf-8"))
    assert "plan_site_symbols_filtered" in [check["code"] for check in report["validation"]["checks"]]
    assert report["molecule"]["formula"] == "NO2"

    # MACE preflight now reads a real ASE structure set instead of a JSON command plan.
    preflight = preflight_paper_to_mlip(root, "mace", RunMode.DRY_RUN)
    codes = {issue.code for issue in preflight.errors + preflight.warnings}
    assert codes.isdisjoint(
        {
            "empty_structure_set",
            "mace_structure_read_failed",
            "structure_count_mismatch",
            "mace_single_input_required",
            "mace_structure_file_missing",
        }
    )


def test_facet_registry_requires_explicit_opt_in(gas_run) -> None:
    root, plan, bulk = gas_run
    slab_only = ("slab_generation",)

    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(plan, root, SurfaceExecutionOverrides(bulk=bulk, tasks=slab_only))
    assert set(blocked.value.missing) == {"surface_facet"}

    artifact = execute_surface_plan(
        plan, root, SurfaceExecutionOverrides(bulk=bulk, use_facet_registry=True, tasks=slab_only)
    )
    assert artifact.metadata["facet"] == [1, 1, 0]
    assert artifact.metadata["facet_source"] == "stable_facet_registry"
    assert artifact.metadata["structure_count"] == 1


def test_reviewed_slab_file_is_used_and_bulk_cells_are_rejected(gas_run, tmp_path: Path) -> None:
    root, plan, bulk = gas_run
    slab_dir = tmp_path / "reviewed"
    slab_file = Path(
        write_slab_outputs(build_slab(_rutile_sno2(), facet="(110)"), slab_dir)["files"]["surface_slab"]
    )

    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(plan, root, SurfaceExecutionOverrides(surface=bulk, tasks=("slab_generation",)))
    assert "looks like a bulk cell" in blocked.value.missing["surface"]

    artifact = execute_surface_plan(
        plan, root, SurfaceExecutionOverrides(surface=slab_file, tasks=("slab_generation",))
    )
    assert artifact.metadata["slab_source"] == "file"
    assert artifact.metadata["source_tasks"] == ["reviewed_slab"]


def test_materials_project_route_requires_opt_in(gas_run) -> None:
    root, plan, _ = gas_run
    calls: list[str] = []

    def fake_provider(*, formula: str):
        calls.append(formula)
        return _rutile_sno2(), {"formula": "SnO2", "spacegroup_symbol": "P4_2/mnm", "material_id": "mp-test"}

    overrides = SurfaceExecutionOverrides(use_facet_registry=True, tasks=("slab_generation",))
    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(plan, root, overrides, bulk_provider=fake_provider)
    assert "--allow-materials-project" in blocked.value.missing["bulk"]
    assert calls == []

    artifact = execute_surface_plan(
        plan,
        root,
        SurfaceExecutionOverrides(use_facet_registry=True, allow_materials_project=True, tasks=("slab_generation",)),
        bulk_provider=fake_provider,
    )
    assert calls == ["SnO2"]
    assert artifact.metadata["slab_source"] == "materials_project"


def test_unknown_molecule_and_absent_site_symbol_block_without_side_effects(gas_run) -> None:
    root, plan, bulk = gas_run
    base = {"bulk": bulk, "surface_facet": "(110)", "coverage_counts": (1,)}

    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(plan, root, SurfaceExecutionOverrides(molecule_name="PAC12IMI", **base))
    assert "supported" in blocked.value.missing["molecule"]

    before = _manifest_text(root)
    with pytest.raises(SurfaceExecutionBlocked) as blocked:
        execute_surface_plan(
            plan, root, SurfaceExecutionOverrides(molecule_name="H2", site_symbols=("Ce",), **base)
        )
    assert "not present in the slab" in blocked.value.missing["site_symbols"]
    assert _manifest_text(root) == before
    assert not (root / "stages" / "03_surface_structures").exists()


def test_repeated_execution_registers_a_new_stage(gas_run) -> None:
    root, plan, bulk = gas_run
    overrides = SurfaceExecutionOverrides(bulk=bulk, use_facet_registry=True, tasks=("slab_generation",))

    first = execute_surface_plan(plan, root, overrides)
    second = execute_surface_plan(plan, root, overrides)

    stage_ids = [stage.stage_id for stage in load_manifest(root).stages]
    assert stage_ids[-2:] == ["03_surface_structures", "03_surface_structures_2"]
    assert first.artifact_id != second.artifact_id


def test_gas_molecule_library_resolves_formulas_and_names() -> None:
    assert resolve_gas_molecule("acetone")[0] == "CH3COCH3"
    assert resolve_gas_molecule("H2S")[1].get_chemical_formula() == "H2S"
    assert resolve_gas_molecule("no2")[0] == "NO2"
    assert resolve_gas_molecule("ethanol")[1].get_chemical_formula() == "C2H6O"
    with pytest.raises(ValueError, match="supported"):
        resolve_gas_molecule("PAC12IMI")


def test_cli_reports_blocked_inputs_then_executes(gas_run) -> None:
    root, _, bulk = gas_run
    runner = CliRunner()

    blocked = runner.invoke(cli_main, ["surface", "execute", "--run-root", str(root)])
    assert blocked.exit_code == 2
    assert "Blocked" in blocked.output and "coverage_counts" in blocked.output

    done = runner.invoke(
        cli_main,
        [
            "surface",
            "execute",
            "--run-root",
            str(root),
            "--bulk",
            str(bulk),
            "--use-facet-registry",
            "--tasks",
            "slab_generation",
        ],
    )
    assert done.exit_code == 0, done.output
    assert "structures:" in done.output
