"""genkai-surface random: physically sensible random pipelines from the sample structure library.

Uses the repository's ``sample/`` library (Materials Project crystals, PubChem VOC molecules);
skipped when the library is not present. Offline, structure generation only.
"""

from __future__ import annotations

import io
import json
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest
import yaml
from ase.io import read

from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.app.pipeline import load_pipeline
from genkai.modeling.surface.app.random_jobs import (
    LibraryError,
    facet_for,
    generate,
    load_library,
    run,
    scenarios_for,
)
from genkai.modeling.surface.builders.adsorbate import auto_site_symbols
from genkai.modeling.surface.builders.slab import SlabSettings, build_slab, load_bulk
from genkai.modeling.surface.builders.vacancy import oxygen_indices
from genkai.modeling.surface.structure_io import components

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "sample"
pytestmark = pytest.mark.skipif(not (SAMPLE / "crystals" / "catalog.json").is_file(), reason="sample/ library not present")


@pytest.fixture(scope="module")
def library():
    return load_library(SAMPLE)


def _slab(library, prefix: str):
    row = next(r for r in library.crystals if r["id"].startswith(prefix))
    facet, _ = facet_for(row)
    return build_slab(load_bulk(library.crystal_path(row)), facet=facet, settings=SlabSettings(min_lateral_size=8.0)).atoms


def test_library_rules_are_realistic(library) -> None:
    assert len(library.crystals) == 32 and len(library.molecules) == 30
    for row in library.crystals:
        usable = scenarios_for(row, mlip=True, library=library)
        if row["collection"] != "stable":
            assert usable == []  # MP-unstable references are never drawn
            continue
        assert facet_for(row) is not None and {"adsorption", "defect", "metal", "energy"} <= set(usable)
        if row["category"] == "sulfide" or row["formula"] in {"SiO2", "NaNbO3"}:
            assert "sam" not in usable  # no carboxylate SAM on sulfides, silica or NaNbO3(001)
        if row["category"] == "sulfide":
            assert "amorphous" not in usable
        if row["category"] in {"oxide", "A2O3"}:
            assert "amorphous" in usable
    assert scenarios_for(library.crystals[0], mlip=False, library=library) == ["adsorption", "defect", "metal", "sam", "ald"]


def test_generation_is_reproducible_and_valid(library, tmp_path: Path) -> None:
    first = generate(library, tmp_path / "a", count=8, seed=11)
    second = generate(library, tmp_path / "b", count=8, seed=11)
    assert first == second
    for record in first:
        text_a = (tmp_path / "a" / record["file"]).read_text(encoding="utf-8")
        assert text_a.startswith("# 随机生成（seed 11")
        pipeline = load_pipeline(tmp_path / "a" / record["file"])
        methods = [step.method for step in pipeline.steps]
        assert methods[0] == "slab" and methods[-1] == "adsorbate"
        if record["scenario"] == "defect":
            vacancy = next(s for s in pipeline.steps if s.method == "vacancy")
            expected = "S" if record["formula"].endswith(("S", "S2")) else "O"
            assert vacancy.mapping["element"] == expected
    out = io.StringIO()
    assert jobs.command_check(sorted((tmp_path / "a").glob("*.yaml")), out) == 0, out.getvalue()
    index = json.loads((tmp_path / "a" / "random_index.json").read_text(encoding="utf-8"))
    assert index["seed"] == 11 and len(index["jobs"]) == 8


def test_filters_and_mlip_scenarios(library, tmp_path: Path) -> None:
    records = generate(library, tmp_path / "f", count=4, seed=3, crystals=["SnO2", "13"], molecules=["ethanol"],
                       scenarios=["defect", "metal"])
    assert {r["formula"] for r in records} <= {"SnO2", "MoS2"}
    assert {r["molecule"] for r in records} == {"02_ethanol"} and {r["scenario"] for r in records} <= {"defect", "metal"}
    with pytest.raises(LibraryError, match="--mlip"):
        generate(library, tmp_path / "m", count=1, seed=1, scenarios=["amorphous"])
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "test", "profiles": {
        "test": {"backend": "emt", "python": sys.executable, "device": "cpu"}}}), encoding="utf-8")
    records = generate(library, tmp_path / "m", count=4, seed=5, scenarios=["amorphous", "energy"], mlip="test")
    for record in records:
        pipeline = load_pipeline(tmp_path / "m" / record["file"], config_path=config)
        assert pipeline.mlip == "test"
        first = pipeline.steps[0].method
        assert first == ("amorphous_bulk" if record["scenario"] == "amorphous" else "slab")
        if record["scenario"] == "amorphous":
            assert record["amorphous_density_g_cm3"] > 0 and [s.method for s in pipeline.steps][1] == "amorphous_slab"


def test_auto_sites_and_sulfur_vacancies(library) -> None:
    sno2 = _slab(library, "04_")
    assert auto_site_symbols(sno2) == ["Sn"]
    mos2 = _slab(library, "13_")  # S-terminated basal plane: no exposed cation
    assert auto_site_symbols(mos2) == ["S"]
    top = mos2.positions[:, 2].max()
    sulfur = oxygen_indices(mos2, symbol="S", surface_depth=1.0)
    assert sulfur and all(mos2[i].symbol == "S" and mos2.positions[i, 2] >= top - 1.0 for i in sulfur)


def test_list_and_errors(library, tmp_path: Path) -> None:
    out = io.StringIO()
    args = Namespace(library=SAMPLE, list=True, mlip=None, count=1, seed=1, output=tmp_path, scenarios=None,
                     crystals=None, molecules=None)
    assert run(args, out) == 0
    text = out.getvalue()
    assert "04_SnO2_cassiterite_rutile_mp-856" in text and "非凸包稳定的参考相" in text
    bad = Namespace(**{**vars(args), "list": False, "library": tmp_path})
    out = io.StringIO()
    assert run(bad, out) == 2 and "不是结构库" in out.getvalue()


@pytest.mark.integration
def test_random_defect_job_runs(library, tmp_path: Path) -> None:
    [record] = generate(library, tmp_path, count=1, seed=2, crystals=["SnO2"], molecules=["ethanol"],
                        scenarios=["defect"])
    assert jobs.main(["run", "--quiet", str(tmp_path / record["file"])]) == 0
    [leaf] = read(tmp_path / "runs" / Path(record["file"]).stem / "pipeline_structures.extxyz", index=":")
    labels = components(leaf)
    added = np.array(leaf.get_chemical_symbols())[labels == "adsorbate"]
    assert sorted(set(added.tolist())) == ["C", "H", "O"]  # ethanol from the library
    assert leaf.info["pipeline_label"] == "slab#0 > vacancy#0 > adsorbate#0"


def test_nonpolar_only_filter_and_amorphous_energy_picks(library, tmp_path: Path) -> None:
    records = generate(library, tmp_path / "np", count=20, seed=9, nonpolar_only=True)
    assert len(records) == 20
    assert all(record["polar_facet"] is False for record in records)
    by_id = {row["id"]: row for row in library.crystals}
    for record in records:
        facet = facet_for(by_id[record["crystal"]])
        assert facet is not None and facet[1] is False
    index = json.loads((tmp_path / "np" / "random_index.json").read_text(encoding="utf-8"))
    assert index["nonpolar_only"] is True

    # Selecting only polar crystals with nonpolar_only=True raises LibraryError.
    with pytest.raises(LibraryError, match="没有符合条件"):
        generate(library, tmp_path / "np_empty", count=1, seed=1, crystals=["20_LaCrO3"], nonpolar_only=True)

    # CLI --list --nonpolar-only marks polar crystals as excluded.
    out = io.StringIO()
    args = Namespace(
        library=SAMPLE, list=True, mlip=None, count=1, seed=1, output=tmp_path,
        scenarios=None, crystals=None, molecules=None, nonpolar_only=True,
    )
    assert run(args, out) == 0
    assert "极性" in out.getvalue() and "--nonpolar-only" in out.getvalue()

    # amorphous scenario uses stoichiometric amorphous_slab + MLIP pick: lowest_energy downstream.
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "test", "profiles": {
        "test": {"backend": "emt", "python": sys.executable, "device": "cpu"}}}), encoding="utf-8")
    [amo] = generate(library, tmp_path / "amo", count=1, seed=4, crystals=["SnO2"],
                     molecules=["ethanol"], scenarios=["amorphous"], mlip="test", nonpolar_only=True)
    pipeline = load_pipeline(tmp_path / "amo" / amo["file"], config_path=config)
    assert [s.method for s in pipeline.steps] == ["amorphous_bulk", "amorphous_slab", "vacancy", "adsorbate"]
    assert pipeline.steps[1].mapping.get("stoichiometric") in (True, "true", "True")
    assert pipeline.steps[1].pick.mode == "lowest_energy"
    assert pipeline.steps[2].pick.mode == "lowest_energy"
    assert int(pipeline.steps[2].mapping["samples_per_count"]) == 4
    assert pipeline.steps[3].pick.mode == "lowest_energy"
