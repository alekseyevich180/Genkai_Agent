"""Chaining builders: component labels (phase 2) and the genkai-surface pipeline (phase 1).

Structure-only and offline: geometric builders with calculator=none, no energies.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from ase import Atoms
from ase.build import molecule
from ase.io import read, write

from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.app.pipeline import (
    PipelineError,
    Pick,
    ensure_vacuum,
    finalize_candidate,
    STEP_KINDS,
    Step,
    load_pipeline,
)
from genkai.modeling.surface.builders.adsorbate import get_surface_sites, unblocked_sites
from genkai.modeling.surface.builders.amorphous_overlayer import OverlayerBuildError, OverlayerSettings, run_overlayer
from genkai.modeling.surface.builders.metal_cluster.surface_cluster_builder import place_cluster_on_surface
from genkai.modeling.surface.builders.sites import exposed_indices, find_surface_sites, surface_region
from genkai.modeling.surface.builders.slab import SlabSettings, build_slab, load_bulk
from genkai.modeling.surface.builders.substrate import prepare_substrate
from genkai.modeling.surface.builders.vacancy import oxygen_indices
from genkai.modeling.surface.structure_io import components, frame_metrics, label_components

ROOT = Path(__file__).resolve().parents[2]
SNO2_BULK = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling" / "sno2_101" / "bulk_from_materials_project.cif"
H2O = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "examples" / "H2O.xyz"
BUTANOIC = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "examples" / "4-acid.vasp"
A_TIO2 = ROOT / "tests" / "amorphous" / "TiO2.vasp"


@pytest.fixture(scope="module")
def sno2_slab() -> Atoms:
    result = build_slab(load_bulk(SNO2_BULK), facet="110", settings=SlabSettings())
    return result.atoms.repeat((2, 4, 1))


def _decorate(slab: Atoms, at_xy: np.ndarray, label: str = "adsorbate", height: float = 2.0) -> Atoms:
    """Slab labelled substrate plus a water molecule ``height`` A above the surface at ``at_xy``."""
    atoms = label_components(slab.copy(), "substrate")
    water = molecule("H2O")
    water.translate([at_xy[0], at_xy[1], float(slab.positions[:, 2].max()) + height] - water.positions.mean(axis=0))
    n = len(atoms)
    atoms += water
    return label_components(atoms, label, range(n, len(atoms)))


def _top_sn(slab: Atoms) -> int:
    sn = [i for i, a in enumerate(slab) if a.symbol == "Sn"]
    return max(sn, key=lambda i: slab.positions[i, 2])


# ---------------------------------------------------------------------------
# Phase 2: builders see what earlier steps added
# ---------------------------------------------------------------------------


def test_unlabeled_slabs_keep_the_original_surface_rule(sno2_slab) -> None:
    z = sno2_slab.positions[:, 2]
    assert surface_region(sno2_slab, 2.5) == [int(i) for i in np.flatnonzero(z >= z.max() - 2.5)]
    assert list(components(sno2_slab)) == ["substrate"] * len(sno2_slab)


def test_surface_ignores_added_atoms_but_they_still_cover_the_site_below(sno2_slab) -> None:
    site = _top_sn(sno2_slab)
    decorated = _decorate(sno2_slab, sno2_slab.positions[site, :2])
    region = surface_region(decorated, 2.5)
    assert region and all(components(decorated)[i] == "substrate" for i in region)
    assert site in region and site not in exposed_indices(decorated, region)
    assert site not in [s.index for s in find_surface_sites(decorated, ["Sn"], undercoordinated_only=False)]


def test_vacancies_are_taken_only_from_substrate_oxygen_at_the_surface(sno2_slab) -> None:
    decorated = _decorate(sno2_slab, sno2_slab.positions[_top_sn(sno2_slab), :2])
    water_o = [i for i in range(len(sno2_slab), len(decorated)) if decorated[i].symbol == "O"]
    surface_o = oxygen_indices(decorated, allowed_components=("substrate",), surface_depth=2.5)
    assert not set(water_o) & set(surface_o)
    top = sno2_slab.positions[:, 2].max()
    assert all(decorated.positions[i, 2] >= top - 2.5 for i in surface_o)
    # The plain call keeps the old behaviour: every O of an unlabeled slab.
    assert len(oxygen_indices(sno2_slab)) == sno2_slab.get_chemical_symbols().count("O")


def test_adsorption_sites_under_added_atoms_are_blocked(sno2_slab) -> None:
    sites = get_surface_sites(sno2_slab, ["Sn"], 1.2, None)
    water = molecule("H2O")
    assert unblocked_sites(sno2_slab, sites, water, 3.5) == (sites, 0)  # nothing added yet
    decorated = _decorate(sno2_slab, sno2_slab.positions[sites[0], :2], label="cluster")
    kept, blocked = unblocked_sites(decorated, get_surface_sites(decorated, ["Sn"], 1.2, None), water, 3.5)
    assert blocked >= 1 and sites[0] not in kept
    assert get_surface_sites(decorated, ["O"], 1.2, None, site_components=["substrate"])  # water O excluded
    assert all(components(decorated)[i] == "substrate"
               for i in get_surface_sites(decorated, ["O"], 1.2, None, site_components=["substrate"]))


def test_sites_under_an_overlayer_island_are_covered(sno2_slab) -> None:
    # Regression (recipe 07): an ALD island is solid, but the substrate atoms under it are not surface.
    slab = label_components(sno2_slab.copy(), "substrate")
    site = _top_sn(slab)
    n = len(slab)
    above = slab.positions[site] + [1.6, 0.0, 2.4]  # one island atom near, not exactly over, the Sn
    slab += Atoms("Ti", positions=[above])
    label_components(slab, "overlayer", [n])
    region = surface_region(slab, 2.5)
    assert site in region and n in region  # substrate measured from its own top, island from its own
    assert site not in exposed_indices(slab, region)
    sites = get_surface_sites(slab, ["Sn"], 1.2, None)
    kept, blocked = unblocked_sites(slab, sites, molecule("H2O"), 3.5)
    assert site not in kept and blocked >= 1
    plain = sno2_slab.copy()  # unlabeled: nothing changes
    assert exposed_indices(plain, surface_region(plain, 2.5)) == exposed_indices(
        label_components(plain.copy(), "substrate"), surface_region(plain, 2.5))


def test_cluster_moves_to_a_free_spot_and_sits_on_the_solid_surface(sno2_slab) -> None:
    cluster = Atoms("Pt4", positions=[[0, 0, 0], [2.7, 0, 0], [1.35, 2.3, 0], [1.35, 0.8, 2.2]])
    cluster.positions -= cluster.positions.mean(axis=0)
    centre = (sno2_slab.cell.array.T @ [0.5, 0.5, 0.0])[:2]
    # Plain slab: original rule, requested spot and global top.
    plain: dict = {}
    combined = place_cluster_on_surface(sno2_slab, cluster, 0.5, 0.5, 2.5, 0, 0, 0, placement=plain)
    assert plain["x_frac"] == 0.5 and plain["y_frac"] == 0.5
    assert combined.positions[-4:, 2].min() == pytest.approx(sno2_slab.positions[:, 2].max() + 2.5)
    # Decorated slab: the requested spot is taken, so the cluster moves and does not touch the water.
    decorated = _decorate(sno2_slab, centre)
    moved: dict = {}
    combined = place_cluster_on_surface(decorated, cluster, 0.5, 0.5, 2.5, 0, 0, 0, placement=moved)
    assert (moved["x_frac"], moved["y_frac"]) != (0.5, 0.5)
    labels = components(combined)
    assert list(labels[-4:]) == ["cluster"] * 4
    gap = np.linalg.norm(combined.positions[labels == "cluster"][:, None] - combined.positions[labels == "adsorbate"][None], axis=2)
    assert gap.min() > 2.0
    assert frame_metrics(combined)["min_contact_ratio"] > 0.6


def test_ald_film_refuses_a_decorated_surface_and_islands_avoid_it(sno2_slab, tmp_path: Path) -> None:
    centre = (sno2_slab.cell.array.T @ [0.5, 0.5, 0.0])[:2]
    path = tmp_path / "decorated.extxyz"
    write(path, _decorate(sno2_slab, centre, label="cluster"))
    substrate = prepare_substrate(surface=path)
    with pytest.raises(OverlayerBuildError, match="overcoat"):
        run_overlayer(substrate, A_TIO2, OverlayerSettings("full", thickness=5.0), tmp_path / "full", export=())
    result = run_overlayer(substrate, A_TIO2, OverlayerSettings("partial", island_atoms=20), tmp_path / "island", export=())
    frame = result.frames[1]
    labels = components(frame)
    gap = np.linalg.norm(frame.positions[labels == "overlayer"][:, None] - frame.positions[labels == "cluster"][None], axis=2)
    assert gap.min() > 2.0  # the island kept clear of the added atoms (repeated with the supercell)


# ---------------------------------------------------------------------------
# Phase 1: the pipeline
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, data: dict, name: str = "pipe.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _problems(path: Path) -> list[str]:
    with pytest.raises(PipelineError) as error:
        load_pipeline(path)
    return error.value.problems


def test_order_wiring_and_roles_are_checked(tmp_path: Path) -> None:
    problems = _problems(_write(tmp_path, {"pipeline": [
        {"method": "slab", "bulk": str(SNO2_BULK)},
        {"method": "adsorbate", "molecule": str(H2O), "site_symbols": ["Sn"]},
        {"method": "vacancy", "input": "slab.cif"},
        {"method": "slab", "bulk": str(SNO2_BULK)},
        {"method": "amorphous_slab", "thickness": 8},
        {"method": "not_a_method"},
        {"method": "adsorbate", "molecule": str(H2O), "site_symbols": ["Sn"], "pick": "best", "output": "x"},
    ]}))
    text = "\n".join(problems)
    assert "第 3 步：不要写 input" in text
    assert "第 3 步：vacancy（晶格缺陷）不能放在 adsorbate（气体吸附）之后" in text and "allow_order: true" in text
    assert "第 4 步：slab 只能是第一步" in text
    assert "第 5 步：amorphous_slab 需要上一步给出非晶块体" in text
    assert "第 6 步：method 'not_a_method' 不能用于流水线" in text
    assert "第 7 步：不能写 output" in text and "pick 只能是" in text


def test_high_order_mlip_screening_methods_registered_and_inherit_mlip(tmp_path: Path) -> None:
    import sys

    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "other", "profiles": {
        "other": {"backend": "emt", "python": sys.executable, "device": "cpu"},
        "test_emt": {"backend": "emt", "python": sys.executable, "device": "cpu",
                     "settings": {"fmax": 0.1, "max_steps": 20}},
    }}), encoding="utf-8")

    for name in ("amorphous_surfaces", "amorphous_interface", "cluster_search", "sam_search"):
        assert name in STEP_KINDS
    assert "clean_slab_relaxed" in STEP_KINDS["sam_search"].skip_roles

    cluster_file = tmp_path / "Pt4.xyz"
    write(cluster_file, Atoms("Pt4", positions=[[0, 0, 0], [2.7, 0, 0], [1.35, 2.34, 0], [1.35, 0.78, 2.2]]))

    pipe1 = load_pipeline(_write(tmp_path, {
        "mlip": "test_emt",
        "pipeline": [
            {"method": "amorphous_bulk", "crystal": str(SNO2_BULK)},
            {"method": "amorphous_surfaces", "periods": 2, "samples": 2},
            {"method": "cluster_search", "cluster": str(cluster_file), "n_trials": 2,
             "selection_count": 1, "top_pool_size": 2, "top_pick_count": 1, "tail_pick_per_bin": 0},
            {"method": "sam_search", "molecule": str(BUTANOIC), "binding_mode": "monodentate", "n_trials": 2, "top_k": 1},
            {"method": "adsorbate", "molecule": str(H2O), "site_symbols": ["auto"]},
        ],
    }, "screen1.yaml"), config_path=config)
    assert [s.method for s in pipe1.steps] == [
        "amorphous_bulk", "amorphous_surfaces", "cluster_search", "sam_search", "adsorbate"
    ]
    for step in pipe1.steps[:4]:
        assert step.template.profile is not None and step.template.profile.name == "test_emt"

    pipe2 = load_pipeline(_write(tmp_path, {
        "mlip": "test_emt",
        "pipeline": [
            {"method": "slab", "bulk": str(SNO2_BULK), "facet": "110"},
            {"method": "amorphous_interface", "amorphous": str(A_TIO2), "thickness": 5, "n_matches": 1, "n_trials": 2},
            {"method": "sam_search", "molecule": str(BUTANOIC), "binding_mode": "monodentate", "n_trials": 2, "top_k": 1},
        ],
    }, "screen2.yaml"), config_path=config)
    assert [s.method for s in pipe2.steps] == ["slab", "amorphous_interface", "sam_search"]
    assert pipe2.steps[1].template.profile.name == "test_emt"
    assert pipe2.steps[2].template.profile.name == "test_emt"

    # blocked_keys: bulk must be rejected on amorphous_interface and sam_search after slab.
    bad = _problems(_write(tmp_path, {
        "mlip": "test_emt",
        "pipeline": [
            {"method": "slab", "bulk": str(SNO2_BULK), "facet": "110"},
            {"method": "amorphous_interface", "bulk": str(SNO2_BULK), "amorphous": str(A_TIO2)},
        ],
    }, "bad_blocked.yaml"))
    assert any("不要写 bulk" in p for p in bad)


def test_allow_order_accepts_vacancies_in_an_overlayer(tmp_path: Path) -> None:
    steps = [
        {"method": "slab", "bulk": str(SNO2_BULK), "facet": "110"},
        {"method": "ald", "amorphous": str(A_TIO2), "coverage": "full", "thickness": 5},
        {"method": "vacancy", "components": ["overlayer"]},
    ]
    # vacancy (lattice defects) after ald (overlayer) is against the default order ...
    assert any("不能放在 ald" in p for p in _problems(_write(tmp_path, {"pipeline": steps})))
    # ... and accepted on purpose, e.g. for O vacancies in the ALD film.
    pipe = load_pipeline(_write(tmp_path, {"allow_order": True, "pipeline": steps}, "ok.yaml"))
    assert [s.method for s in pipe.steps] == ["slab", "ald", "vacancy"]


def test_pick_and_step_defaults(tmp_path: Path) -> None:
    assert Pick("first").select(3) == [0] and Pick("all").select(3) == [0, 1, 2]
    assert Pick("index", (2, 0)).select(3) == [2, 0]
    with pytest.raises(IndexError):
        Pick("index", (3,)).select(3)
    pipe = load_pipeline(_write(tmp_path, {"pipeline": [
        {"method": "slab", "bulk": str(SNO2_BULK)},
        {"method": "vacancy", "pick": [0, 2]},
    ]}))
    vacancy = pipe.steps[1]
    assert vacancy.pick == Pick("index", (0, 2))
    assert vacancy.defaults_applied == {"surface_depth": "2.5"}
    assert "--surface-depth=2.5" in jobs.build_argv(vacancy.template)
    pipe = load_pipeline(_write(tmp_path, {"pipeline": [
        {"method": "slab", "bulk": str(SNO2_BULK)},
        {"method": "vacancy", "z_frac_min": 0.5},
    ]}, "window.yaml"))
    assert pipe.steps[1].defaults_applied == {}  # the user chose the window


def test_vacuum_is_restored_and_labels_are_completed(sno2_slab) -> None:
    atoms = sno2_slab.copy()
    cell = atoms.cell.array.copy()
    cell[2, 2] = float(atoms.positions[:, 2].max()) + 3.0
    atoms.set_cell(cell)
    assert ensure_vacuum(atoms, 10.0) == pytest.approx(7.0)
    assert atoms.cell[2, 2] == pytest.approx(atoms.positions[:, 2].max() + 10.0)
    step = Step(3, "cluster", STEP_KINDS["cluster"], {}, Pick("first"), {}, template=None)  # type: ignore[arg-type]
    decorated = label_components(sno2_slab.copy(), "substrate")
    decorated += Atoms("Pt", positions=[[0.0, 0.0, float(sno2_slab.positions[:, 2].max()) + 2.5]])
    frame, record = finalize_candidate(decorated, step, first=False, min_vacuum=10.0)
    assert components(frame)[-1] == "cluster" and record["notes"]
    with pytest.raises(RuntimeError, match="component"):
        finalize_candidate(sno2_slab.copy(), step, first=False, min_vacuum=10.0)


def test_job_loader_points_pipeline_files_to_check_and_run(tmp_path: Path) -> None:
    path = _write(tmp_path, {"pipeline": [{"method": "slab", "bulk": str(SNO2_BULK)}]})
    with pytest.raises(jobs.JobFileError, match="流水线文件"):
        jobs.load_job_file(path)
    out = io.StringIO()
    assert jobs.command_check([path], out) == 0 and "流水线共 1 步，检查通过" in out.getvalue()


@pytest.mark.integration
def test_pipeline_runs_slab_vacancy_cluster_adsorbate_with_branches(tmp_path: Path) -> None:
    path = _write(tmp_path, {"output": "runs/chain", "pipeline": [
        {"method": "slab", "bulk": str(SNO2_BULK), "facet": "110", "repeat_xy": [2, 4]},
        {"method": "vacancy", "vacancy_counts": [1], "samples_per_count": 2, "pick": "all"},
        {"method": "cluster", "cluster_element": "Pt", "cluster_atoms": 13, "cluster_structures": ["fcc"]},
        {"method": "adsorbate", "molecule": str(H2O), "site_symbols": ["Sn"], "coverage_counts": [1],
         "patterns": ["uniform"], "n_trials_single": 4},
    ]})
    assert jobs.main(["run", "--quiet", str(path)]) == 0
    out = tmp_path / "runs" / "chain"
    manifest = json.loads((out / "pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] in {"PASS", "WARN"} and len(manifest["structures"]) == 2
    assert manifest["steps"][1]["defaults_applied"] == {"surface_depth": "2.5"}
    slab = read(out / "01_slab" / "root" / "pipeline" / "candidate_000.extxyz")
    slab.wrap(pbc=[True, True, False])
    o_top = max(p[2] for p, s in zip(slab.positions, slab.get_chemical_symbols()) if s == "O")
    leaves = read(out / "pipeline_structures.extxyz", index=":")
    labels_seen = set()
    for leaf, record in zip(leaves, manifest["structures"]):
        assert leaf.info["pipeline_label"] == record["label"]
        assert [link["method"] for link in record["lineage"]] == ["slab", "vacancy", "cluster", "adsorbate"]
        leaf.wrap(pbc=[True, True, False])
        labels = components(leaf)
        labels_seen.add(record["label"])
        assert dict(zip(*np.unique(labels, return_counts=True))) == {"substrate": len(slab) - 1, "cluster": 13, "adsorbate": 3}
        assert len(leaf.constraints[0].index) == len(slab.constraints[0].index)  # fixed atoms kept
        removed = [p for p in slab.positions if np.linalg.norm(leaf.positions[labels == "substrate"] - p, axis=1).min() > 0.01]
        assert len(removed) == 1 and removed[0][2] >= o_top - 2.5  # a surface O vacancy
        solid_top = leaf.positions[labels == "substrate", 2].max()
        assert leaf.positions[labels == "cluster", 2].min() == pytest.approx(solid_top + 2.5, abs=0.01)
        gap = np.linalg.norm(leaf.positions[labels == "adsorbate"][:, None] - leaf.positions[labels == "cluster"][None], axis=2)
        assert gap.min() > 1.5
        assert leaf.cell[2, 2] - leaf.positions[:, 2].max() >= 10.0 - 1e-6
    assert len(labels_seen) == 2  # two branches from the two vacancy candidates
    log = (out / "04_adsorbate" / "c0-0-0" / "run.log").read_text(encoding="utf-8")
    assert "Sites blocked by atoms of earlier steps" in log


@pytest.mark.integration
def test_pipeline_reports_overcoat_and_branch_limits(tmp_path: Path) -> None:
    overcoat = _write(tmp_path, {"output": "runs/overcoat", "allow_order": True, "pipeline": [
        {"method": "slab", "bulk": str(SNO2_BULK), "facet": "110", "repeat_xy": [2, 4]},
        {"method": "cluster", "cluster_element": "Pt", "cluster_atoms": 13, "cluster_structures": ["fcc"]},
        {"method": "ald", "amorphous": str(A_TIO2), "coverage": "full", "thickness": 5, "export": "none"},
    ]})
    assert jobs.main(["run", "--quiet", str(overcoat)]) == 1
    manifest = json.loads((tmp_path / "runs/overcoat/pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "FAIL" and "overcoat" in (tmp_path / "runs/overcoat/03_ald/c0-0/run.log").read_text(encoding="utf-8")

    branches = _write(tmp_path, {"output": "runs/branches", "max_branches": 2, "pipeline": [
        {"method": "slab", "bulk": str(SNO2_BULK), "facet": "110"},
        {"method": "vacancy", "vacancy_counts": [1], "samples_per_count": 3, "pick": "all"},
    ]}, "branches.yaml")
    assert jobs.main(["run", "--quiet", str(branches)]) == 1
    manifest = json.loads((tmp_path / "runs/branches/pipeline_manifest.json").read_text(encoding="utf-8"))
    assert any("max_branches=2" in failure for failure in manifest["failures"])


@pytest.mark.integration
def test_pipeline_runs_slab_cluster_search_and_adsorbate_with_emt(tmp_path: Path) -> None:
    import sys
    from ase.build import bulk as ase_bulk

    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "test_emt", "profiles": {
        "test_emt": {"backend": "emt", "python": sys.executable, "device": "cpu",
                     "settings": {"fmax": 0.2, "max_steps": 10}},
    }}), encoding="utf-8")
    cu_bulk = tmp_path / "Cu.cif"
    write(cu_bulk, ase_bulk("Cu", "fcc", a=3.61, cubic=True))
    pt4 = tmp_path / "Pt4.xyz"
    write(pt4, Atoms("Pt4", positions=[[0, 0, 0], [2.75, 0, 0], [1.38, 2.38, 0], [1.38, 0.79, 2.25]]))
    co = tmp_path / "CO.xyz"
    write(co, molecule("CO"))

    pipe = _write(tmp_path, {
        "output": "runs/cs_chain",
        "mlip": "test_emt",
        "pipeline": [
            {"method": "slab", "bulk": str(cu_bulk), "facet": "111", "repeat_xy": [3, 3], "min_slab_size": 6},
            {"method": "cluster_search", "cluster": str(pt4), "n_trials": 2, "seed": 3,
             "selection_count": 1, "top_pool_size": 2, "top_pick_count": 1, "tail_pick_per_bin": 0},
            {"method": "adsorbate", "molecule": str(co), "site_symbols": ["Pt"], "coverage_counts": [1],
             "patterns": ["uniform"], "n_trials_single": 2},
        ],
    }, "cs_chain.yaml")
    assert jobs.main(["check", str(pipe)]) == 0
    assert jobs.main(["run", "--quiet", str(pipe)]) == 0
    out = tmp_path / "runs" / "cs_chain"
    manifest = json.loads((out / "pipeline_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] in {"PASS", "WARN"}
    [leaf] = read(out / "pipeline_structures.extxyz", index=":")
    labels = components(leaf)
    assert set(labels.tolist()) == {"substrate", "cluster", "adsorbate"}
    assert int((labels == "cluster").sum()) == 4
    assert int((labels == "adsorbate").sum()) == 2
    assert leaf.constraints
