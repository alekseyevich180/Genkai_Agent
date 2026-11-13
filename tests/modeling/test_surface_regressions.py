"""Regression tests for surface-modeling correctness fixes (2026-11-12/13)."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.build import fcc111
from ase.io import write

from genkai.modeling.mapping import (
    _build_argument_template,
    _build_task_inputs,
    _load_surface_modeling_parameter_schema,
    _loaded_species,
)
from genkai.modeling.surface import adsorbate


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS = PROJECT_ROOT / "agents/Agent/skills/surface-modeling/scripts"


def test_adsorbate_sites_and_uniform_pattern_respect_periodic_boundaries() -> None:
    slab = fcc111("Pt", size=(4, 4, 3), vacuum=10.0)
    nn = 3.92 / np.sqrt(2.0)
    sites = adsorbate.get_surface_sites(slab, ["Pt"], 1.2, None)
    assert len(sites) == 16

    # Two-site groups must be nearest neighbours, including across the cell edge,
    # and their centroid must sit on the bridge rather than mid-cell.
    groups = adsorbate.build_site_groups(slab, sites, 2)
    centers = adsorbate.group_positions(slab, groups)
    for group, center in zip(groups, centers):
        pair = adsorbate.minimum_image_vectors(slab, slab.positions[group[1]] - slab.positions[group[0]])
        assert np.isclose(np.linalg.norm(pair), nn, atol=0.01)
        for site in group:
            offset = adsorbate.minimum_image_vectors(slab, slab.positions[site] - center)
            assert np.isclose(np.linalg.norm(offset[:2]), nn / 2.0, atol=0.01)

    # "uniform" coverage of 4 sites on a 4x4 cell is the 2x2 sublattice.
    site_positions = slab.positions[sites]
    pairwise = adsorbate.lateral_distance_matrix(slab, site_positions)
    selected = adsorbate.farthest_site_selection(site_positions[:, :2], 4, pairwise)
    min_separation = min(pairwise[i, j] for i in selected for j in selected if i != j)
    assert min_separation > 2.0 * nn - 0.05


def test_programmatic_adsorbate_run_records_run_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / ".matplotlib"))
    surface_path = tmp_path / "surface.cif"
    molecule_path = tmp_path / "H2.xyz"
    write(
        surface_path,
        Atoms(
            symbols=["Sn", "Sn", "O", "O"],
            positions=[[2.0, 2.0, 2.0], [7.0, 7.0, 2.0], [2.0, 7.0, 0.0], [7.0, 2.0, 0.0]],
            cell=[10.0, 10.0, 15.0],
            pbc=[True, True, False],
        ),
    )
    write(molecule_path, Atoms("H2", positions=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.74]]))

    adsorbate.run_adsorbate_landscape(
        adsorbate.AdsorbateLandscapeConfig(
            surface=surface_path,
            molecule=molecule_path,
            output_dir=tmp_path / "landscape",
            site_symbols="Sn",
            coverage_counts="1",
            patterns="uniform",
            n_trials_single=1,
            calculator="none",
            max_steps=0,
        )
    )

    config = json.loads((tmp_path / "landscape" / "run_config.json").read_text(encoding="utf-8"))
    assert config["calculator"] == "none"
    assert config["task_name"] == "omat"
    assert config["surface"] == str(surface_path)


def test_ptomodel_never_copies_task_key_into_uma_task_name() -> None:
    schema = _load_surface_modeling_parameter_schema()
    for task in ("slab_generation", "vacancy_landscape", "adsorbate_landscape"):
        template = _build_argument_template(task, {"surfaces": ["CeO2(111)"]}, {}, schema)
        assert template["arguments"]["task_name"] is None, task
        assert "task_name" not in template["auto_mapped_parameters"], task


def test_ptomodel_slab_generation_template_maps_formula_facet_or_requests_bulk() -> None:
    schema = _load_surface_modeling_parameter_schema()
    metal = _build_argument_template(
        "slab_generation",
        {"material": "Pt nanoparticles", "surfaces": ["Pt(111)"], "facets": ["(111)"]},
        {"facet_set": ["(111)"]},
        schema,
    )["parameter_bindings"]
    assert metal["formula"]["value"] == "Pt"
    assert metal["facet"]["value"] == "(111)"
    assert metal["facet"]["confidence"] == "high"

    unknown = _build_argument_template(
        "slab_generation",
        {"material": "MOF-derived carbon", "surfaces": ["N-doped carbon"]},
        {},
        schema,
    )["parameter_bindings"]
    assert unknown["formula"]["value"] is None
    assert unknown["bulk"]["status"] == "needs_upstream_artifact"
    assert unknown["facet"]["status"] == "stable_facet_registry_or_manual"


def test_characterization_lattice_planes_are_not_exposed_facets() -> None:
    schema = _load_surface_modeling_parameter_schema()

    def facet_binding(task: str, task_inputs: dict) -> dict:
        bindings = _build_argument_template(task, task_inputs, {}, schema)["parameter_bindings"]
        return bindings["facet" if task == "slab_generation" else "surface_facet"]

    hrtem = {
        "surfaces": ["SnO2 nanowire surface"],
        "facets": ["(101)"],
        "facet_mentions": ["SnO2 (101) plane observed by HRTEM"],
    }
    xrd = {"surfaces": ["SnO2"], "facets": ["(110)"], "facet_mentions": ["(110) diffraction peak in XRD"]}
    exposed = {
        "surfaces": ["TiO2 nanosheets"],
        "facets": ["(001)"],
        "facet_mentions": ["anatase TiO2 nanosheets with exposed (001) facets"],
    }
    modeled = {"surfaces": ["CeO2"], "facets": ["(111)"], "slab_models": ["CeO2(111) slab"]}
    for task in ("slab_generation", "surface_cluster_builder"):
        for unconfirmed in (hrtem, xrd):
            binding = facet_binding(task, unconfirmed)
            assert binding["value"] is None, (task, unconfirmed)
            assert binding["status"] == "stable_facet_registry_or_manual"
        assert facet_binding(task, exposed)["value"] == "(001)"
        assert facet_binding(task, modeled)["value"] == "(111)"


def test_ptomodel_does_not_map_oxide_cluster_to_metal_element() -> None:
    task_inputs = _build_task_inputs(
        "surface_cluster_builder",
        {
            "materials": ["Ru"],
            "surfaces": ["Ru/LaOx–SiO2", "SiO2"],
            "active_sites": ["Ru–LaOx interface"],
            "clusters": ["LaOx clusters"],
        },
        None,
    )
    assert task_inputs["cluster_species"] == ["Ru"]
    assert task_inputs["cluster_species_source"] == "active_sites"
    assert task_inputs["non_elemental_cluster_terms"] == ["LaOx clusters"]
    assert _loaded_species("LaOx clusters") == "LaOx"
    assert _loaded_species("Pt13 cluster") == "Pt"


def test_vacancy_skill_entry_records_calculator_run_config(tmp_path: Path) -> None:
    output_dir = tmp_path / "vacancy"
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_SCRIPTS / "vacancy/vacancy_landscape.py"),
            "--input",
            str(PROJECT_ROOT / "agents/Agent/skills/surface-modeling/examples/CeO2 (1 1 1).cif"),
            "--vacancy-counts",
            "1",
            "--samples-per-count",
            "1",
            "--calculator",
            "none",
            "--max-steps",
            "0",
            "--output-dir",
            str(output_dir),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    config = json.loads((output_dir / "run_config.json").read_text(encoding="utf-8"))
    assert config["calculator"] == "none"
    assert config["task_name"] == "omat"
    assert config["uma_model"] == "uma-s-1p2"


def test_cluster_search_exposes_uma_task_head() -> None:
    import inspect

    from genkai.modeling.surface import cluster_search

    parameter = inspect.signature(cluster_search.build_calculator).parameters["task_name"]
    assert parameter.default == "oc22"
    completed = subprocess.run(
        [sys.executable, str(SKILL_SCRIPTS / "cluster_search/ads_nanocluster.py"), "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--task_name" in completed.stdout
