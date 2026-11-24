"""Pipeline phase 3: intermediate relaxation (method relax) and picking candidates by energy.

Offline with ASE EMT on small metal cells (Cu slab, Pt clusters, CO): EMT gives real
forces, so the selection logic is exercised end to end; results are labelled
empirical_potential, not MLIP. UMA/MACE runs follow the same path on a server.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from ase.build import bulk, fcc111, molecule
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms
from ase.io import read, write

from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.app.pipeline import Pick, PipelineError, _parse_pick, load_pipeline, select_lowest
from genkai.modeling.surface.screening.relax import RelaxError, RelaxSettings, main as relax_main, run_relax
from genkai.modeling.surface.structure_io import components, label_components


def _config(directory: Path) -> Path:
    path = directory / "genkai.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "default": "test_emt", "profiles": {
        "test_emt": {"backend": "emt", "python": sys.executable, "device": "cpu",
                     "settings": {"fmax": 0.1, "max_steps": 40}},
    }}), encoding="utf-8")
    return path


def _cu_slab_file(directory: Path) -> Path:
    slab = fcc111("Cu", (2, 2, 3), vacuum=8.0)
    slab.set_constraint(FixAtoms(indices=[a.index for a in slab if a.tag == 3]))
    label_components(slab, "substrate")
    co = molecule("CO")
    co.translate(slab.positions[-1] + [0, 0, 2.0] - co.positions[0])
    n = len(slab)
    slab += co
    label_components(slab, "adsorbate", range(n, len(slab)))
    second = slab.copy()
    second.positions[n:] += [0.6, 0.0, 0.3]
    path = directory / "frames.extxyz"
    write(path, [slab, second])
    return path


def test_select_lowest_groups_by_composition() -> None:
    records = [
        {"index": 0, "formula": "Cu12O", "energy_eV": -1.0},
        {"index": 1, "formula": "Cu12O", "energy_eV": -3.0},
        {"index": 2, "formula": "Cu12O2", "energy_eV": -5.0},
        {"index": 3, "formula": "Cu12O", "energy_eV": -2.0},
        {"index": 4, "formula": "Cu12O2", "energy_eV": -4.0},
    ]
    assert select_lowest(records, 1) == [1, 2]
    assert select_lowest(records, 2) == [1, 3, 2, 4]


def test_pick_lowest_energy_parsing() -> None:
    assert _parse_pick("lowest_energy") == Pick("lowest_energy", count=1)
    assert _parse_pick("lowest_energy", "3") == Pick("lowest_energy", count=3)
    with pytest.raises(ValueError, match="pick_count 只和"):
        _parse_pick("all", "2")
    with pytest.raises(ValueError, match="正整数"):
        _parse_pick("lowest_energy", "0")


def test_relax_keeps_labels_and_fixed_atoms_and_refuses_the_mock(tmp_path: Path) -> None:
    frames_path = _cu_slab_file(tmp_path)
    manifest = run_relax(frames_path, RelaxSettings(fmax=0.1, max_steps=30), tmp_path / "out",
                         calculator=EMT(), calculator_name="emt")
    assert manifest["evidence_level"] == "empirical_potential" and len(manifest["frames"]) == 2
    relaxed = read(tmp_path / "out" / "relaxed_structures.extxyz", index=":")
    original = read(frames_path, index=":")
    for before, after in zip(original, relaxed):
        assert list(components(after)) == list(components(before))
        assert list(after.constraints[0].index) == list(before.constraints[0].index)
        fixed = after.constraints[0].index
        assert np.allclose(after.positions[fixed], before.positions[fixed])  # fixed atoms did not move
    assert all(np.isfinite(row["energy_eV"]) for row in manifest["frames"])
    single = run_relax(frames_path, RelaxSettings(max_steps=0), tmp_path / "sp", calculator=EMT(), calculator_name="emt")
    assert single["mode"] == "single-point"
    with pytest.raises(RelaxError):
        run_relax(frames_path, RelaxSettings(), tmp_path / "mock", calculator=EMT(), calculator_name="none")
    assert relax_main(["--structures", str(frames_path), "--output-dir", str(tmp_path / "cli")]) == 2


def test_energy_pick_needs_an_energy_model(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GENKAI_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    cu = tmp_path / "Cu.cif"
    write(cu, bulk("Cu", "fcc", a=3.61, cubic=True))
    path = tmp_path / "pipe.yaml"
    path.write_text(yaml.safe_dump({"pipeline": [
        {"method": "slab", "bulk": "Cu.cif", "facet": "111"},
        {"method": "cluster", "cluster_element": "Pt", "cluster_atoms": 13, "pick": "lowest_energy"},
    ]}), encoding="utf-8")
    with pytest.raises(PipelineError) as error:
        load_pipeline(path)
    assert any("pick: lowest_energy 需要能量模型" in p and "genkai.yaml" in p for p in error.value.problems)


@pytest.mark.integration
def test_pipeline_relaxes_and_keeps_the_lowest_energy_candidates(tmp_path: Path) -> None:
    _config(tmp_path)
    write(tmp_path / "Cu.cif", bulk("Cu", "fcc", a=3.61, cubic=True))
    write(tmp_path / "CO.xyz", molecule("CO"))
    path = tmp_path / "pipe.yaml"
    path.write_text(yaml.safe_dump({"output": "runs/energy", "mlip": "test_emt", "pipeline": [
        {"method": "slab", "bulk": "Cu.cif", "facet": "111", "repeat_xy": [4, 4], "min_slab_size": 6},
        {"method": "cluster", "cluster_element": "Pt", "cluster_atoms": 13, "cluster_structures": ["fcc", "hcp"],
         "pick": "lowest_energy"},
        {"method": "relax"},
        {"method": "adsorbate", "molecule": "CO.xyz", "site_symbols": ["Pt"], "coverage_counts": [1, 2],
         "patterns": ["uniform"], "n_trials_single": 3, "pick": "lowest_energy"},
    ]}, sort_keys=False), encoding="utf-8")
    assert jobs.main(["check", str(path)]) == 0
    assert jobs.main(["run", "--quiet", str(path)]) == 0
    out = tmp_path / "runs" / "energy"
    manifest = json.loads((out / "pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] in {"PASS", "WARN"} and manifest["energy_models_used"] == ["test_emt (emt)"]

    cluster_run = manifest["steps"][1]["runs"][0]
    energies = cluster_run["energies"]
    assert len(energies) == 2 and len({row["formula"] for row in energies}) == 1  # fcc and hcp Pt13, same composition
    best = min(energies, key=lambda row: row["energy_eV"])
    assert cluster_run["picked"] == [best["candidate"]]
    assert Path(cluster_run["energy_manifest"]).is_file()

    adsorbate_run = manifest["steps"][3]["runs"][0]
    assert len({row["formula"] for row in adsorbate_run["energies"]}) == 2  # one and two CO
    assert len(adsorbate_run["picked"]) == 2  # the lowest of each coverage
    for formula in {row["formula"] for row in adsorbate_run["energies"]}:
        group = [row for row in adsorbate_run["energies"] if row["formula"] == formula]
        assert [row["picked"] for row in group].count(True) == 1
        assert min(group, key=lambda row: row["energy_eV"])["picked"]

    leaves = read(out / "pipeline_structures.extxyz", index=":")
    assert len(leaves) == 2 and len(manifest["structures"]) == 2
    for leaf, record in zip(leaves, manifest["structures"]):
        methods = [link["method"] for link in record["lineage"]]
        assert methods == ["slab", "cluster", "relax", "adsorbate"]
        assert record["lineage"][1]["relaxed_for_pick"] is True and "energy_eV" in record["lineage"][3]
        labels = components(leaf)
        assert {"substrate", "cluster", "adsorbate"} == set(labels.tolist())
        assert int((labels == "cluster").sum()) == 13
        assert leaf.constraints  # fixed atoms survive relaxation and picking
