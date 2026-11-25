"""Recipes (examples/recipes) and gas molecules by name.

The structure-only recipes must stay valid; the MLIP recipes must parse with a
configured profile. Offline, structure generation only.
"""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml
from ase.io import read

from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.app.pipeline import load_pipeline
from genkai.modeling.surface.builders.molecules import canonical_gas_name, load_molecule
from genkai.modeling.surface.structure_io import components

ROOT = Path(__file__).resolve().parents[2]
RECIPES = ROOT / "examples" / "recipes"
STRUCTURE_ONLY = sorted(p for p in RECIPES.glob("*.yaml") if "_mlip_" not in p.name)
MLIP = sorted(p for p in RECIPES.glob("*.yaml") if "_mlip_" in p.name)


def test_gas_names_and_aliases() -> None:
    assert canonical_gas_name("NO2") == "NO2" and canonical_gas_name("no2") == "NO2"
    assert canonical_gas_name("ethanol") == "C2H5OH" and canonical_gas_name("acetone") == "CH3COCH3"
    assert canonical_gas_name("H2S") == "H2S" and canonical_gas_name("unobtainium") is None
    atoms, source = load_molecule("NO2")
    assert atoms.get_chemical_formula() == "NO2" and "built-in" in source
    atoms, _ = load_molecule("acetone")
    assert sorted(atoms.get_chemical_symbols()).count("C") == 3
    with pytest.raises(FileNotFoundError):
        load_molecule("missing_dir/NO2")  # a path is never read as a gas name
    water = ROOT / "agents/Agent/skills/surface-modeling/examples/H2O.xyz"
    assert load_molecule(water)[1] == water.as_posix()


def test_job_files_keep_gas_names_and_resolve_files(tmp_path: Path) -> None:
    option = jobs.METHODS["adsorbate"].option("molecule")
    assert jobs._convert(option, "NO2", tmp_path) == "NO2"
    assert jobs._convert(option, "ethanol", tmp_path) == "C2H5OH"
    (tmp_path / "my.xyz").write_text("1\n\nH 0 0 0\n", encoding="utf-8")
    assert jobs._convert(option, "my.xyz", tmp_path) == (tmp_path / "my.xyz").resolve()
    # A file named like a gas wins over the built-in geometry.
    (tmp_path / "CO").write_text("2\n\nC 0 0 0\nO 0 0 1.13\n", encoding="utf-8")
    assert jobs._convert(option, "CO", tmp_path) == (tmp_path / "CO").resolve()


def test_structure_only_recipes_pass_check() -> None:
    assert len(STRUCTURE_ONLY) >= 10
    out = io.StringIO()
    assert jobs.command_check(STRUCTURE_ONLY, out) == 0, out.getvalue()


def test_mlip_recipes_parse_with_a_configured_profile(tmp_path: Path) -> None:
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "test", "profiles": {
        "test": {"backend": "emt", "python": sys.executable, "device": "cpu"},
    }}), encoding="utf-8")
    assert len(MLIP) >= 2
    for path in MLIP:
        pipeline = load_pipeline(path, config_path=config)
        assert pipeline.mlip == "default"
        assert any(step.pick.by_energy or step.method in {"relax", "amorphous_bulk"} for step in pipeline.steps)


@pytest.mark.integration
def test_simplest_recipe_runs(tmp_path: Path) -> None:
    shutil.copytree(RECIPES / "inputs", tmp_path / "inputs")
    recipe = shutil.copy(RECIPES / "01_sno2_no2.yaml", tmp_path / "01_sno2_no2.yaml")
    assert jobs.main(["run", "--quiet", str(recipe)]) == 0
    [leaf] = read(tmp_path / "runs" / "01_sno2_no2" / "pipeline_structures.extxyz", index=":")
    labels = components(leaf)
    added = np.array(leaf.get_chemical_symbols())[labels == "adsorbate"]
    assert sorted(added.tolist()) == ["N", "O", "O"]  # one NO2 from the built-in geometry
    assert leaf.info["pipeline_label"] == "slab#0 > adsorbate#0"
