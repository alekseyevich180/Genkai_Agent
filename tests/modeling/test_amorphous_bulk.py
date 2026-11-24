"""Crystal -> amorphous bulk by melt-quench MD, and the chain crystal -> amorphous bulk -> amorphous slab.

MD runs use ASE EMT on 32-atom Cu cells with a very short schedule: they check the
plumbing (supercell, schedule, diagnostics, outputs, hand-off to amorphous_slab),
not the quality of an amorphous structure. EMT results are labelled empirical_potential.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from ase.build import bulk
from ase.calculators.emt import EMT
from ase.io import write

from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.builders.amorphous_bulk import (
    AmorphousBulkError,
    MeltQuenchSettings,
    cell_heights,
    choose_supercell,
    main,
    prepare_supercell,
    run_amorphous_bulk,
)
from genkai.modeling.surface.builders.amorphous_overlayer import check_amorphous_bulk
from genkai.modeling.surface.builders.amorphous_slab import AmorphousSlabSettings, run_amorphous_slab
from genkai.modeling.surface.structure_io import frame_metrics, read_frames, read_structure

ROOT = Path(__file__).resolve().parents[2]
SNO2_BULK = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling" / "sno2_101" / "bulk_from_materials_project.cif"
# About 360 MD steps: enough to exercise every stage, far too short for a real amorphous structure.
FAST = dict(melt_temperature=2500.0, melt_ps=0.2, quench_rate=20000.0, anneal_ps=0.05, max_steps=60, trajectory_interval=100)


def _cu(directory: Path) -> Path:
    path = directory / "Cu.cif"
    write(path, bulk("Cu", "fcc", a=3.61, cubic=True))
    return path


@pytest.fixture(scope="module")
def emt_run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("amorphous_bulk")
    settings = MeltQuenchSettings(supercell=(2, 2, 2), samples=2, **FAST)
    return run_amorphous_bulk(_cu(directory), settings, directory / "out", calculator=EMT(), calculator_name="emt")


def test_supercell_is_the_smallest_near_cubic_one_with_enough_atoms() -> None:
    sno2, _ = read_structure(SNO2_BULK)
    reps = choose_supercell(sno2, 150)
    widths = cell_heights(sno2) * np.array(reps)
    assert len(sno2) * np.prod(reps) >= 150 and widths.max() / widths.min() <= 1.5
    assert reps == (3, 3, 3)  # rutile a = 4.74, c = 3.19 A: 162 atoms
    assert choose_supercell(bulk("Cu", "fcc", a=3.61, cubic=True), 100) == (3, 3, 3)


def test_density_scaling_reaches_the_target_and_keeps_the_crystal_reference() -> None:
    sno2, _ = read_structure(SNO2_BULK)
    crystal, start, report = prepare_supercell(sno2, MeltQuenchSettings(density=6.4))
    assert report["start_density_g_cm3"] == pytest.approx(6.4, abs=1e-3)
    assert report["crystal_density_g_cm3"] > 6.8
    assert len(crystal) == len(start) == 162
    assert crystal.get_volume() < start.get_volume()


@pytest.mark.parametrize(
    "bad",
    [dict(melt_temperature=300.0), dict(supercell=(0, 1, 1)), dict(timestep_fs=10.0), dict(density=-1.0), dict(quench_rate=0.0)],
)
def test_invalid_settings_are_rejected(bad: dict) -> None:
    with pytest.raises(AmorphousBulkError):
        MeltQuenchSettings(**bad)


def test_dry_run_prepares_the_supercell_without_md(tmp_path: Path) -> None:
    result = run_amorphous_bulk(
        SNO2_BULK, MeltQuenchSettings(density=6.4), tmp_path, calculator=None, calculator_name="none", dry_run=True
    )
    manifest = result.manifest
    assert manifest["mode"] == "prepare-only" and manifest["evidence_level"] == "heuristic"
    assert manifest["scientific_calculation_started"] is False and not manifest["samples"]
    assert manifest["schedule"]["md_steps"]["total"] == 74000  # 10 ps melt + 54 ps quench + 10 ps anneal
    assert result.initial_path.is_file() and result.structures_path is None
    [initial] = read_frames(result.initial_path)
    assert len(initial) == 162 and not (tmp_path / "amorphous_bulk_000.extxyz").exists()


def test_mock_calculator_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert main(["--crystal", str(SNO2_BULK), "--output-dir", str(out)]) == 2
    assert not out.exists()
    with pytest.raises(AmorphousBulkError, match="forces"):
        run_amorphous_bulk(SNO2_BULK, MeltQuenchSettings(), out, calculator=None, calculator_name="none")


def test_melt_quench_writes_bulk_cells_and_diagnostics(emt_run) -> None:
    manifest = emt_run.manifest
    assert manifest["mode"] == "melt-quench" and manifest["evidence_level"] == "empirical_potential"
    assert len(emt_run.frames) == 2 and len(emt_run.sample_paths) == 2
    first, second = emt_run.frames
    assert len(first) == len(second) == 32 and first.get_chemical_formula() == "Cu32"
    assert first.pbc.all() and not first.constraints and "momenta" not in first.arrays
    assert not np.allclose(first.positions, second.positions)  # different initial velocities
    for frame in emt_run.frames:
        check_amorphous_bulk(frame)  # a dense periodic bulk, usable as --amorphous
        assert frame_metrics(frame)["min_contact_ratio"] > 0.6
    sample = manifest["samples"][0]
    assert set(sample["melt_rms_displacement_A"]) == {"Cu"}
    assert sample["md_steps"]["total"] == sum(v for k, v in sample["md_steps"].items() if k != "total")
    assert sample["delta_e_vs_crystal_eV_per_atom"] is not None and manifest["crystal_reference"]["energy_per_atom_eV"] is not None
    assert sample["diagnostics"]["pairs"]["Cu-Cu"]["cn_Cu_by_Cu"]["mean"] > 0
    assert manifest["crystal_diagnostics"]["pairs"]["Cu-Cu"]["cn_Cu_by_Cu"]["mean"] == 12.0
    # 0.2 ps is far too short to melt: the diagnostic must say so instead of passing silently.
    assert any("may still remember the crystal" in w for w in manifest["validation"]["warnings"])
    files = manifest["files"]
    assert len(files["md_logs"]) == 2 and all(Path(p).is_file() for p in files["md_logs"])
    rdf = json.loads(Path(files["rdf"]).read_text(encoding="utf-8"))
    assert {"crystal_supercell", "sample_000", "sample_001"} <= set(rdf) and "Cu-Cu" in rdf["sample_000"]
    assert (Path(files["samples"][0]).parent / "md" / "md_000.extxyz").is_file()


def test_amorphous_bulk_output_cuts_into_a_surface_slab(emt_run, tmp_path: Path) -> None:
    result = run_amorphous_slab(emt_run.sample_paths[0], AmorphousSlabSettings(thickness=6.0, vacuum=10.0), tmp_path, export=())
    [slab] = result.frames
    metrics = frame_metrics(slab)
    assert metrics["vacuum_gap_A"] >= 10.0 and metrics["n_fixed"] > 0
    assert result.manifest["amorphous"]["path"].endswith("amorphous_bulk_000.extxyz")


def test_job_file_chains_crystal_to_amorphous_bulk_to_slab(tmp_path: Path) -> None:
    _cu(tmp_path)
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "test_emt", "profiles": {
        "test_emt": {"backend": "emt", "python": sys.executable, "device": "cpu"},
    }}), encoding="utf-8")
    bulk_job = {"method": "amorphous_bulk", "mlip": "default", "output": "runs/bulk", "crystal": "Cu.cif",
                "supercell": [2, 2, 2], "export": "none", **{k: v for k, v in FAST.items()}}
    slab_job = {"method": "amorphous_slab", "output": "runs/slab", "amorphous": "runs/bulk/amorphous_bulk_000.extxyz",
                "thickness": 6, "vacuum": 10, "export": "none"}
    task = tmp_path / "chain.yaml"
    task.write_text(yaml.safe_dump({"jobs": [bulk_job, slab_job]}), encoding="utf-8")
    assert jobs.main(["check", str(task)]) == 0
    assert jobs.main(["run", "--quiet", str(task)]) == 0
    bulk_manifest = json.loads((tmp_path / "runs/bulk/manifest.json").read_text(encoding="utf-8"))
    assert bulk_manifest["metadata"]["calculator"] == "emt"
    assert bulk_manifest["artifacts"][0]["evidence_level"] == "empirical_potential"
    [slab] = read_frames(tmp_path / "runs/slab/amorphous_slab_structures.extxyz")
    assert slab.get_chemical_formula().startswith("Cu") and frame_metrics(slab)["vacuum_gap_A"] >= 10.0
