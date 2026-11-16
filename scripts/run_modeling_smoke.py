#!/usr/bin/env python
"""Smoke-test every surface-modeling method on structures shipped in this repository.

Each case calls the real entry point (skill script or ``python -m genkai.modeling.surface.jobs``) in a
subprocess, then reads every produced structure with ASE and checks that it is
non-empty, free of overlapping atoms, has vacuum (slabs), keeps fixed atoms
(extxyz/POSCAR outputs) and contains the expected elements.

Profiles
--------
local (default)
    Structure generation only: ``--calculator none`` / ``--max-steps 0``; no
    network, GPU, UMA, VASP or Materials Project. Energies printed by the mock
    calculators are meaningless and are not checked.
server (prepared, not validated on a workstation)
    The same cases with ``--calculator uma`` wherever a method supports it
    (vacancy, adsorbate, most-stable-facet ranking), plus the UMA-only cluster
    search. Needs fairchem-core, the UMA model and a GPU (``--device cuda``).
    Run it only where real calculations are authorized.

Cases that need Materials Project run only with ``--enable network`` (and
``MP_API_KEY`` in the environment).

Examples
--------
    python scripts/run_modeling_smoke.py                     # all local cases
    python scripts/run_modeling_smoke.py --list
    python scripts/run_modeling_smoke.py --only sam,ald      # by method or case-id prefix
    python scripts/run_modeling_smoke.py --profile server --device cuda --output-dir runs/smoke

Exit code: 0 when no case FAILs (WARN does not fail unless --strict), 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SKILL_SCRIPTS = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "scripts"
EXAMPLES = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "examples"
SE4 = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling"
ARCHIVES = ROOT / "tests" / "fixtures" / "archives" / "generated"

if str(SRC) not in sys.path:  # the checks below live in the library; works without an install too
    sys.path.insert(0, str(SRC))

from genkai.modeling.surface.structure_io import CLASH_RATIO, MIN_VACUUM_A, frame_metrics, read_frames  # noqa: E402

# Structures already in the repository: key -> (path, description).
INPUTS: dict[str, tuple[Path, str]] = {
    "ceo2_111_slab": (EXAMPLES / "CeO2 (1 1 1).cif", "CeO2(111) slab, two O-Ce-O trilayers (skill example)"),
    "h2o": (EXAMPLES / "H2O.xyz", "H2O (skill example)"),
    "butanoic_acid": (EXAMPLES / "4-acid.vasp", "C4H8O2 butanoic acid (skill example)"),
    "sno2_bulk": (SE4 / "sno2_101" / "bulk_from_materials_project.cif", "rutile SnO2 bulk saved from Materials Project"),
    "sno2_101_legacy_slab": (
        SE4 / "sno2_101" / "stable_surface_slab.vasp",
        "SnO2(101) slab from the old MP route (c not normal to the surface)",
    ),
    "h2": (SE4 / "inputs" / "H2.xyz", "H2"),
    "methylcyclohexanone": (
        ARCHIVES / "s41467-025-56361-4_surface_fullrun_v3" / "modeling_demo" / "inputs" / "4-methylcyclohexanone_C7H12O.xyz",
        "4-methylcyclohexanone C7H12O",
    ),
    "ru_bulk": (
        ARCHIVES / "s41563-025-02134-9_surface_fullrun" / "modeling" / "structures" / "cluster_bulk_from_materials_project.cif",
        "hcp Ru bulk saved from Materials Project",
    ),
    "ru7_cluster": (
        ARCHIVES / "s41563-025-02134-9_surface_fullrun" / "modeling" / "structures" / "Ru_hcp_r7.xyz",
        "hcp Ru nanoparticle, radius 7 A (file name r7 = radius, not 7 atoms)",
    ),
    "a_sno2": (ROOT / "tests" / "amorphous" / "SnO2", "amorphous SnO2, 48 atoms (extension-less POSCAR)"),
    "a_tio2": (ROOT / "tests" / "amorphous" / "TiO2.vasp", "amorphous TiO2, 48 atoms"),
}


@dataclass
class Context:
    profile: str
    device: str
    uma_model: str
    enabled: set[str]
    uma_task: str = "omat"

    @property
    def server(self) -> bool:
        return self.profile == "server"

    def uma_args(self, style: str = "dash", flag: str = "--calculator") -> list[str]:
        sep = "-" if style == "dash" else "_"
        return [flag, "uma", "--device", self.device, f"--uma{sep}model", self.uma_model, f"--task{sep}name", self.uma_task]


@dataclass
class Case:
    case_id: str
    method: str
    description: str
    inputs: tuple[str, ...]
    commands: Callable[[Context, Path], list[list[str]]]
    outputs: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    expect_exit: int = 0
    expect_message: str | None = None
    contains: tuple[str, ...] = ()
    min_structures: int = 1
    slab: bool = True
    fixed: bool = False
    fewer: tuple[str, str] | None = None
    prepare: Callable[[Path], dict[str, str]] | None = None


def path(key: str) -> str:
    return str(INPUTS[key][0])


def py(*parts: Any) -> list[str]:
    return [sys.executable, *[str(part) for part in parts]]


def skill(relative: str) -> str:
    return str(SKILL_SCRIPTS / relative)


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------


def slab_case(bulk: str, facet: str | None = None) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        cmd = py(skill("surface/slab_generation.py"), "--bulk", path(bulk), "--output-dir", out / "slab")
        if facet:
            cmd += ["--facet", facet]
        elif ctx.server:
            cmd += ctx.uma_args()  # most stable facet by UMA surface energy instead of the registry
        return [cmd]

    return build


def vacancy_case(ctx: Context, out: Path) -> list[list[str]]:
    cmd = py(
        skill("vacancy/vacancy_landscape.py"),
        "--input", path("ceo2_111_slab"),
        "--output-dir", out / "vacancy",
        "--vacancy-counts", "1,2",
        "--samples-per-count", "3",
    )
    cmd += ctx.uma_args() if ctx.server else ["--calculator", "none", "--max-steps", "0"]
    return [cmd]


def adsorbate_case(surface: str, molecule: str, site_symbols: str) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        cmd = py(
            skill("adsorbate/adsorbate_landscape.py"),
            "--surface", path(surface),
            "--molecule", path(molecule),
            "--site-symbols", site_symbols,
            "--output-dir", out / "adsorbate",
            "--coverage-counts", "1,2",
            "--patterns", "uniform,random",
            "--random-repeats", "1",
        )
        if ctx.server:
            cmd += ctx.uma_args()
        else:
            cmd += ["--calculator", "none", "--max-steps", "0", "--n-trials-single", "8"]
        return [cmd]

    return build


def cluster_case(extra: list[str]) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        return [
            py(
                skill("metal_cluster/surface_cluster_builder.py"),
                "--surface", path("ceo2_111_slab"),
                "--cluster_atoms", "13",
                "--output_dir", out / "cluster",
                *extra,
            )
        ]

    return build


CLUSTER_SELECTION = ["--selection_count", "2", "--top_pool_size", "4", "--top_pick_count", "2", "--tail_pick_per_bin", "0"]


def cluster_search_case(ctx: Context, out: Path) -> list[list[str]]:
    cmd = py(
        skill("cluster_search/ads_nanocluster.py"),
        "--surface", path("ceo2_111_slab"),
        "--cluster", path("ru7_cluster"),
        "--output_dir", out / "cluster_search",
        "--n_trials", "20" if ctx.server else "8",
        "--max_steps", "50",
        "--seed", "1",
        *CLUSTER_SELECTION,
    )
    cmd += ctx.uma_args("underscore") if ctx.server else ["--calculator", "none"]
    return [cmd]


def island_search_case(ctx: Context, out: Path) -> list[list[str]]:
    """ALD island cut from a-TiO2 -> Optuna placement with tilt on the clean SnO2 slab."""
    ald = py(
        skill("ald/ald_overlayer.py"), "--bulk", path("sno2_bulk"), "--amorphous", path("a_tio2"),
        "--coverage", "partial", "--island-atoms", "20", "--export", "none", "--output-dir", out / "ald",
    )
    search = py(
        skill("cluster_search/ads_nanocluster.py"),
        "--surface", out / "ald" / "substrate_slab.extxyz",
        "--cluster", out / "ald" / "islands" / "island_000.extxyz",
        "--placement_shape", "input", "--max_tilt", "60",
        "--n_trials", "20" if ctx.server else "8", "--max_steps", "50", "--seed", "1",
        "--output_dir", out / "search",
        *CLUSTER_SELECTION,
    )
    search += ctx.uma_args("underscore") if ctx.server else ["--calculator", "none"]
    return [ald, search]


def sam_search_case(ctx: Context, out: Path) -> list[list[str]]:
    cmd = py(
        skill("sam/sam_search.py"), "--bulk", path("sno2_bulk"), "--molecule", path("butanoic_acid"),
        "--binding-mode", "monodentate", "--n-trials", "8", "--top-k", "2", "--coverage-counts", "1,2",
        "--output-dir", out / "sam_search",
    )
    if ctx.server:
        cmd += ctx.uma_args(flag="--search-calculator")
    else:
        cmd += ["--screen-steps", "2", "--max-steps", "2"]
    return [cmd]


def amorphous_screen_case(kind: str) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        if kind == "surfaces":
            cmd = py(skill("amorphous/amorphous_screen.py"), "surfaces", "--amorphous", path("a_tio2"),
                     "--periods", "2", "--samples", "3", "--output-dir", out / "screen")
            flag = "--calculator"
        else:
            cmd = py(skill("amorphous/amorphous_screen.py"), "interface", "--bulk", path("sno2_bulk"),
                     "--amorphous", path("a_tio2"), "--thickness", "5", "--n-matches", "2", "--n-trials", "4",
                     "--output-dir", out / "screen")
            flag = "--search-calculator"
        if ctx.server:
            cmd += ctx.uma_args(flag=flag)
        else:
            cmd += ["--max-steps", "2"] + (["--screen-steps", "2"] if kind == "interface" else [])
        return [cmd]

    return build


def sam_case(substrate: list[str], molecule: str | None, extra: list[str]) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        molecule_path = path(molecule) if molecule else str(out / "inputs" / "CH3SH.xyz")
        cmd = py(skill("sam/sam_builder.py"), *substrate, "--molecule", molecule_path, "--output-dir", out / "sam", *extra)
        if ctx.server and "--bulk" in substrate and "--facet" not in extra:
            cmd += ctx.uma_args()
        return [cmd]

    return build


def ald_case(substrate: list[str], extra: list[str]) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        cmd = py(skill("ald/ald_overlayer.py"), *substrate, "--output-dir", out / "ald", *extra)
        if ctx.server and "--bulk" in substrate and "--facet" not in extra:
            cmd += ctx.uma_args()
        return [cmd]

    return build


def amorphous_slab_case(amorphous: str, extra: list[str]) -> Callable[[Context, Path], list[list[str]]]:
    def build(ctx: Context, out: Path) -> list[list[str]]:
        return [py(skill("amorphous/amorphous_slab.py"), "--amorphous", path(amorphous), "--output-dir", out / "amorphous", *extra)]

    return build


def sam_on_amorphous_case(ctx: Context, out: Path) -> list[list[str]]:
    slab = amorphous_slab_case("a_sno2", ["--thickness", "8"])(ctx, out)[0]
    sam = py(
        skill("sam/sam_builder.py"),
        "--surface", out / "amorphous" / "amorphous_slab_000.extxyz",
        "--molecule", path("butanoic_acid"),
        "--binding-mode", "bidentate",
        "--counts", "1",
        "--output-dir", out / "sam",
    )
    return [slab, sam]


def write_methanethiol(case_dir: Path) -> dict[str, str]:
    """No thiol molecule file exists in the repository; take CH3SH from ASE's built-in G2 set."""
    from ase.build import molecule
    from ase.io import write

    target = case_dir / "inputs" / "CH3SH.xyz"
    target.parent.mkdir(parents=True, exist_ok=True)
    write(target, molecule("CH3SH"))
    return {"CH3SH.xyz": "ase.build.molecule('CH3SH') (G2 reference geometry)"}


def write_job_file(case_dir: Path) -> dict[str, str]:
    """Two chained jobs for genkai-surface: pure amorphous SnO2 slab -> bidentate butanoic acid on it."""
    (case_dir / "job.yaml").write_text(
        "jobs:\n"
        "  - method: amorphous_slab\n"
        "    output: runs/amorphous\n"
        f"    amorphous: '{INPUTS['a_sno2'][0].as_posix()}'\n"
        "    thickness: 8\n"
        "  - method: sam\n"
        "    output: runs/sam\n"
        "    surface: runs/amorphous/amorphous_slab_000.extxyz\n"
        f"    molecule: '{INPUTS['butanoic_acid'][0].as_posix()}'\n"
        "    binding_mode: bidentate\n"
        "    counts: [1]\n",
        encoding="utf-8",
    )
    return {"job.yaml": "two-job genkai-surface file written by the smoke script"}


def job_file_case(ctx: Context, out: Path) -> list[list[str]]:
    return [py("-m", "genkai.modeling.surface.jobs", "run", "--quiet", out / "job.yaml")]


def by_path(key: str) -> list[str]:
    return ["--bulk", path(key)] if key.endswith("_bulk") else ["--surface", path(key)]


# ---------------------------------------------------------------------------
# Case registry
# ---------------------------------------------------------------------------

CASES: list[Case] = [
    Case("slab_sno2_stable_facet", "slab_generation", "SnO2 bulk -> most stable facet (registry locally)",
         ("sno2_bulk",), slab_case("sno2_bulk"), ("slab/slab.extxyz",), fixed=True),
    Case("slab_sno2_101", "slab_generation", "SnO2 bulk -> explicit (101)",
         ("sno2_bulk",), slab_case("sno2_bulk", "101"), ("slab/slab.extxyz",), fixed=True),
    Case("slab_ru_stable_facet", "slab_generation", "hcp Ru bulk -> most stable facet",
         ("ru_bulk",), slab_case("ru_bulk"), ("slab/slab.extxyz",), fixed=True),
    Case("slab_sno2_materials_project", "slab_generation", "SnO2 downloaded from Materials Project",
         (), lambda ctx, out: [py(skill("surface/slab_generation.py"), "--formula", "SnO2", "--output-dir", out / "slab")],
         ("slab/slab.extxyz",), requires=("network",), fixed=True),
    Case("vacancy_ceo2_111", "vacancy_landscape", "O vacancies (1, 2) in CeO2(111)",
         ("ceo2_111_slab",), vacancy_case, ("vacancy/structures/*.cif",), min_structures=4,
         fewer=("O", "ceo2_111_slab")),
    Case("adsorbate_ceo2_h2o", "adsorbate_landscape", "H2O coverage 1-2 on Ce sites of CeO2(111)",
         ("ceo2_111_slab", "h2o"), adsorbate_case("ceo2_111_slab", "h2o", "Ce"),
         ("adsorbate/structures/*.cif",), contains=("H",), min_structures=2),
    Case("adsorbate_sno2_101_ketone", "adsorbate_landscape", "4-methylcyclohexanone on Sn of the legacy SnO2(101) slab",
         ("sno2_101_legacy_slab", "methylcyclohexanone"),
         adsorbate_case("sno2_101_legacy_slab", "methylcyclohexanone", "Sn"),
         ("adsorbate/structures/*.cif",), contains=("C", "H"), min_structures=2),
    Case("cluster_pt13_on_ceo2", "surface_cluster_builder", "Pt13 (fcc/hcp/bcc) on CeO2(111)",
         ("ceo2_111_slab",), cluster_case(["--cluster_element", "Pt"]),
         ("cluster/*_on_surface.cif",), contains=("Pt",), min_structures=3),
    Case("cluster_ru13_hcp_on_ceo2", "surface_cluster_builder", "Ru13 hcp (lattice from Ru bulk) on CeO2(111)",
         ("ceo2_111_slab", "ru_bulk"), cluster_case(["--cluster_bulk_file", path("ru_bulk"), "--cluster_structures", "hcp"]),
         ("cluster/*_on_surface.cif",), contains=("Ru",)),
    Case("cluster_search_ru7_on_ceo2", "cluster_search",
         "Optuna placement search of an r = 7 A Ru particle on CeO2(111) (mock locally, UMA on the server)",
         ("ceo2_111_slab", "ru7_cluster"), cluster_search_case, ("cluster_search/mlip_output/0*_trial_*.cif",),
         contains=("Ru",), min_structures=2),
    Case("island_search_atio2_on_sno2", "cluster_search",
         "ALD a-TiO2 island -> Optuna placement with tilt on the clean SnO2 slab (chained)",
         ("sno2_bulk", "a_tio2"), island_search_case, ("search/mlip_output/0*_trial_*.cif",),
         contains=("Ti",), min_structures=2),
    Case("sam_sno2_butanoic_monodentate", "sam", "butanoic acid, monodentate, counts 1,2 on the most stable SnO2 facet",
         ("sno2_bulk", "butanoic_acid"),
         sam_case(by_path("sno2_bulk"), "butanoic_acid", ["--binding-mode", "monodentate", "--counts", "1,2"]),
         ("sam/sam_structures.extxyz",), contains=("C",), min_structures=3, fixed=True),
    Case("sam_ceo2_butanoic_bidentate", "sam", "butanoic acid, bidentate, counts 1,2 on the CeO2(111) example slab",
         ("ceo2_111_slab", "butanoic_acid"),
         sam_case(by_path("ceo2_111_slab"), "butanoic_acid", ["--binding-mode", "bidentate", "--counts", "1,2"]),
         ("sam/sam_structures.extxyz",), contains=("C",), min_structures=3, fixed=True),
    Case("sam_ru_methanethiol_fcc", "sam", "CH3SH (ASE G2) thiolate in fcc hollows, tilt 30, on the stable Ru facet",
         ("ru_bulk",),
         sam_case(by_path("ru_bulk"), None, ["--binding-mode", "fcc", "--counts", "1,2", "--tilt", "30"]),
         ("sam/sam_structures.extxyz",), contains=("S",), min_structures=3, fixed=True, prepare=write_methanethiol),
    Case("sam_on_legacy_tilted_slab", "sam", "butanoic acid on the legacy SnO2(101) slab (tilted c, normalized automatically)",
         ("sno2_101_legacy_slab", "butanoic_acid"),
         sam_case(by_path("sno2_101_legacy_slab"), "butanoic_acid", ["--binding-mode", "monodentate", "--counts", "1"]),
         ("sam/sam_structures.extxyz",), contains=("C",), min_structures=2, fixed=True),
    Case("sam_on_amorphous_sno2_slab", "sam", "pure amorphous SnO2 slab -> butanoic acid bidentate on it (chained)",
         ("a_sno2", "butanoic_acid"), sam_on_amorphous_case,
         ("sam/sam_structures.extxyz",), contains=("C",), min_structures=2, fixed=True),
    Case("ald_full_asno2_on_sno2", "ald_overlayer", "6 A amorphous SnO2 film on the most stable SnO2 facet",
         ("sno2_bulk", "a_sno2"),
         ald_case(by_path("sno2_bulk"), ["--amorphous", path("a_sno2"), "--coverage", "full", "--thickness", "6"]),
         ("ald/ald_structures.extxyz",), contains=("Sn",), min_structures=2, fixed=True),
    Case("ald_full_atio2_on_sno2", "ald_overlayer", "5 A amorphous TiO2 film on the most stable SnO2 facet",
         ("sno2_bulk", "a_tio2"),
         ald_case(by_path("sno2_bulk"), ["--amorphous", path("a_tio2"), "--coverage", "full", "--thickness", "5"]),
         ("ald/ald_structures.extxyz",), contains=("Ti",), min_structures=2, fixed=True),
    Case("ald_partial_asno2_on_sno2_101", "ald_overlayer", "30-atom amorphous SnO2 island on SnO2(101)",
         ("sno2_bulk", "a_sno2"),
         ald_case(by_path("sno2_bulk"), ["--facet", "101", "--amorphous", path("a_sno2"), "--coverage", "partial",
                                         "--island-atoms", "30", "--samples", "2"]),
         ("ald/ald_structures.extxyz",), contains=("Sn",), min_structures=3, fixed=True),
    Case("ald_partial_atio2_on_ceo2", "ald_overlayer", "24-atom amorphous TiO2 island on the CeO2(111) example slab",
         ("ceo2_111_slab", "a_tio2"),
         ald_case(by_path("ceo2_111_slab"), ["--amorphous", path("a_tio2"), "--coverage", "partial", "--island-atoms", "24"]),
         ("ald/ald_structures.extxyz",), contains=("Ti",), min_structures=2, fixed=True),
    Case("ald_full_atio2_on_ceo2_cut", "ald_overlayer",
         "hexagonal CeO2(111) vs square a-TiO2 cell: no lattice match -> cut film with repaired seams",
         ("ceo2_111_slab", "a_tio2"),
         ald_case(by_path("ceo2_111_slab"), ["--amorphous", path("a_tio2"), "--coverage", "full", "--thickness", "5"]),
         ("ald/ald_structures.extxyz",), contains=("Ti",), min_structures=2, fixed=True),
    Case("ald_full_strain_only_blocks_unmatched", "ald_overlayer",
         "--film-fit strain on CeO2(111) + a-TiO2 must be blocked (exit 2)",
         ("ceo2_111_slab", "a_tio2"),
         ald_case(by_path("ceo2_111_slab"), ["--amorphous", path("a_tio2"), "--coverage", "full", "--thickness", "5",
                                             "--film-fit", "strain"]),
         expect_exit=2, expect_message="No in-plane supercell match"),
    Case("ald_partial_atio2_on_legacy_slab", "ald_overlayer", "30-atom amorphous TiO2 island on the legacy tilted SnO2(101) slab",
         ("sno2_101_legacy_slab", "a_tio2"),
         ald_case(by_path("sno2_101_legacy_slab"), ["--amorphous", path("a_tio2"), "--coverage", "partial", "--island-atoms", "30"]),
         ("ald/ald_structures.extxyz",), contains=("Ti",), min_structures=2, fixed=True),
    Case("amorphous_slab_sno2", "amorphous_slab", "pure amorphous SnO2 surface, 8 A, 2 different cuts",
         ("a_sno2",), amorphous_slab_case("a_sno2", ["--thickness", "8", "--samples", "2"]),
         ("amorphous/amorphous_slab_structures.extxyz",), contains=("Sn",), min_structures=2, fixed=True),
    Case("amorphous_slab_tio2", "amorphous_slab", "pure amorphous TiO2 surface, 10 A, 2x2 in-plane",
         ("a_tio2",), amorphous_slab_case("a_tio2", ["--thickness", "10", "--repeat-xy", "2,2"]),
         ("amorphous/amorphous_slab_structures.extxyz",), contains=("Ti",), fixed=True),
    Case("sam_search_sno2_butanoic", "sam_search",
         "Optuna over anchored placements of butanoic acid on SnO2(110), then coverage 2 by copying",
         ("sno2_bulk", "butanoic_acid"), sam_search_case, ("sam_search/sam_search_structures.extxyz",),
         contains=("C",), min_structures=4, fixed=True),
    Case("amorphous_screen_surfaces_tio2", "amorphous_screen",
         "a-TiO2: relax bulk, cut 3 stoichiometric 2-period surfaces, rank by surface energy",
         ("a_tio2",), amorphous_screen_case("surfaces"), ("screen/amorphous_surfaces_ranked.extxyz",),
         contains=("Ti",), min_structures=3),
    Case("amorphous_screen_interface_atio2_on_sno2", "amorphous_screen",
         "a-TiO2 film on SnO2(110): 2 lattice matches x Optuna (shift, gap), rank by adhesion",
         ("sno2_bulk", "a_tio2"), amorphous_screen_case("interface"), ("screen/amorphous_interfaces_ranked.extxyz",),
         contains=("Ti",), min_structures=2, fixed=True),
    Case("job_file_amorphous_then_sam", "surface_jobs",
         "genkai-surface job file: amorphous SnO2 slab -> bidentate butanoic acid on it (chained, structure only)",
         ("a_sno2", "butanoic_acid"), job_file_case, ("runs/sam/sam_structures.extxyz",),
         contains=("C",), min_structures=2, fixed=True, prepare=write_job_file),
]


# ---------------------------------------------------------------------------
# Structure checks
# ---------------------------------------------------------------------------


def count_element(file: Path, element: str) -> int:
    return read_frames(file)[0].get_chemical_symbols().count(element)


def check_outputs(case: Case, case_dir: Path) -> tuple[str, list[str], dict[str, Any]]:
    """Return (status, notes, details) for the structures written by a case."""
    files = sorted({f for pattern in case.outputs for f in case_dir.glob(pattern) if f.is_file()})
    notes: list[str] = []
    details: dict[str, Any] = {"files": [f.relative_to(case_dir).as_posix() for f in files], "frames": []}
    if not files:
        return "FAIL", [f"no structure file matches {', '.join(case.outputs)}"], details
    frames: list[tuple[Path, Any]] = []
    for file in files:
        try:
            frames.extend((file, frame) for frame in read_frames(file))
        except Exception as exc:  # unreadable output is a failure, not a warning
            return "FAIL", [f"cannot read {file.name}: {exc}"], details
    status = "PASS"
    elements: set[str] = set()
    for file, frame in frames:
        metrics = frame_metrics(frame)
        metrics["file"] = file.relative_to(case_dir).as_posix()
        details["frames"].append(metrics)
        elements.update(frame.get_chemical_symbols())
        if metrics["n_atoms"] == 0:
            return "FAIL", [f"empty structure in {file.name}"], details
    details["structure_count"] = len(frames)
    if len(frames) < case.min_structures:
        return "FAIL", [f"{len(frames)} structure(s), expected >= {case.min_structures}"], details
    missing = [e for e in case.contains if e not in elements]
    if missing:
        return "FAIL", [f"expected element(s) {', '.join(missing)} absent"], details
    if case.fewer:
        element, reference = case.fewer
        limit = count_element(INPUTS[reference][0], element)
        counts = [f.get_chemical_symbols().count(element) for _, f in frames]
        if not all(c < limit for c in counts):
            return "FAIL", [f"some structures keep all {limit} {element} atoms"], details
    ratios = [m["min_contact_ratio"] for m in details["frames"] if "min_contact_ratio" in m]
    if ratios and min(ratios) < CLASH_RATIO:
        status = "WARN"
        notes.append(f"overlapping atoms: min contact ratio {min(ratios)} < {CLASH_RATIO}")
    if case.slab:
        gaps = [m.get("vacuum_gap_A", 0.0) for m in details["frames"]]
        if min(gaps) < MIN_VACUUM_A:
            status = "WARN"
            notes.append(f"vacuum gap {min(gaps)} A < {MIN_VACUUM_A} A")
    if case.fixed and not all(m["n_fixed"] > 0 for m in details["frames"]):
        status = "WARN"
        notes.append("some frames have no fixed atoms")
    notes.insert(0, f"{len(frames)} structures, {len(files)} file(s), min contact ratio {min(ratios) if ratios else 'n/a'}")
    return status, notes, details


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def subprocess_env(case_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), env.get("PYTHONPATH")]))
    env["MPLBACKEND"] = "Agg"
    env["MPLCONFIGDIR"] = str(case_dir / ".mplconfig")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_case(case: Case, ctx: Context, output_root: Path, timeout: float) -> dict[str, Any]:
    record: dict[str, Any] = {
        "case_id": case.case_id,
        "method": case.method,
        "description": case.description,
        "inputs": {key: INPUTS[key][0].relative_to(ROOT).as_posix() for key in case.inputs},
        "expect_exit": case.expect_exit,
    }
    blocked_by = [need for need in case.requires if need not in ctx.enabled]
    if blocked_by:
        hint = {"uma": "--profile server", "network": "--enable network"}
        record.update(status="SKIP", notes=[f"requires {', '.join(blocked_by)} ({'; '.join(hint[b] for b in blocked_by)})"])
        return record
    missing = [key for key in case.inputs if not INPUTS[key][0].is_file()]
    if missing:
        record.update(status="FAIL", notes=[f"missing input(s): {', '.join(missing)}"])
        return record

    case_dir = output_root / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    if case.prepare is not None:
        record["derived_inputs"] = case.prepare(case_dir)
    commands = case.commands(ctx, case_dir)
    record["commands"] = [" ".join(f'"{c}"' if " " in c else c for c in cmd) for cmd in commands]
    started = time.perf_counter()
    exit_code = 0
    output_text = ""
    with (case_dir / "run.log").open("w", encoding="utf-8") as log:
        for cmd in commands:
            log.write(f"$ {' '.join(cmd)}\n")
            try:
                completed = subprocess.run(
                    cmd, cwd=case_dir, env=subprocess_env(case_dir), capture_output=True,
                    text=True, encoding="utf-8", errors="replace", timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                record.update(status="FAIL", notes=[f"timed out after {timeout:.0f} s"], seconds=round(time.perf_counter() - started, 1))
                return record
            log.write(completed.stdout + completed.stderr + f"[exit {completed.returncode}]\n")
            output_text += completed.stdout + completed.stderr
            exit_code = completed.returncode
            if exit_code != 0:
                break
    record["seconds"] = round(time.perf_counter() - started, 1)
    record["exit_code"] = exit_code
    record["log"] = (case_dir / "run.log").relative_to(output_root).as_posix()

    if exit_code != case.expect_exit:
        tail = [line for line in output_text.strip().splitlines() if line.strip()][-3:]
        record.update(status="FAIL", notes=[f"exit {exit_code}, expected {case.expect_exit}", *tail])
        return record
    if case.expect_exit != 0:
        found = case.expect_message is None or case.expect_message in output_text
        record.update(
            status="PASS" if found else "FAIL",
            notes=[f"blocked as expected (exit {exit_code})" if found else f"message {case.expect_message!r} not found"],
        )
        return record
    status, notes, details = check_outputs(case, case_dir)
    record.update(status=status, notes=notes, structures=details)
    return record


def environment_info() -> dict[str, Any]:
    info: dict[str, Any] = {"python": sys.version.split()[0], "platform": platform.platform()}
    for package in ("ase", "pymatgen", "numpy", "scipy", "fairchem"):
        try:
            from importlib.metadata import version

            info[package] = version(package if package != "fairchem" else "fairchem-core")
        except Exception:
            info[package] = None
    try:
        info["git_commit"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        info["git_commit"] = None
    return info


def select_cases(only: str | None, skip: str | None) -> list[Case]:
    def matches(case: Case, tokens: list[str]) -> bool:
        return any(case.case_id.startswith(t) or case.method.startswith(t) for t in tokens)

    selected = CASES
    if only:
        tokens = [t.strip() for t in only.split(",") if t.strip()]
        selected = [c for c in selected if matches(c, tokens)]
    if skip:
        tokens = [t.strip() for t in skip.split(",") if t.strip()]
        selected = [c for c in selected if not matches(c, tokens)]
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test every surface-modeling method on structures shipped in this repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples", 1)[1] if __doc__ and "Examples" in __doc__ else None,
    )
    parser.add_argument("--profile", choices=["local", "server"], default="local",
                        help="local: structure generation only (default); server: UMA calculations (not validated locally).")
    parser.add_argument("--enable", default="", help="Extra capabilities, e.g. 'network' for Materials Project cases.")
    parser.add_argument("--device", choices=["cuda", "cpu"], default="cuda", help="UMA device for --profile server.")
    parser.add_argument("--uma-model", default="uma-s-1p2")
    parser.add_argument(
        "--uma-task",
        default="omat",
        help="UMA task head for --profile server (fairchem 2.7.1: omol, omat, odac, oc20, oc25, omc).",
    )
    parser.add_argument("--only", default=None, help="Comma-separated case-id prefixes or method names.")
    parser.add_argument("--skip", default=None, help="Comma-separated case-id prefixes or method names to leave out.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Default: a new folder in the system temp directory.")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Seconds per case.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on WARN as well as FAIL.")
    parser.add_argument("--list", action="store_true", help="List the cases and their inputs, then exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    enabled = {item.strip() for item in args.enable.split(",") if item.strip()}
    if args.profile == "server":
        enabled.add("uma")
    ctx = Context(profile=args.profile, device=args.device, uma_model=args.uma_model, enabled=enabled, uma_task=args.uma_task)
    cases = select_cases(args.only, args.skip)
    if args.list:
        for case in cases:
            needs = f" [requires {', '.join(case.requires)}]" if case.requires else ""
            expect = f" [expects exit {case.expect_exit}]" if case.expect_exit else ""
            print(f"{case.case_id:36s} {case.method:24s} {case.description}{needs}{expect}")
            for key in case.inputs:
                file, text = INPUTS[key]
                print(f"{'':38s}- {file.relative_to(ROOT).as_posix()} ({text}){'' if file.is_file() else '  MISSING'}")
        return 0
    if not cases:
        print("No case matches the selection.", file=sys.stderr)
        return 1

    output_root = args.output_dir or Path(tempfile.mkdtemp(prefix="genkai_modeling_smoke_"))
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    not_selected = [case.case_id for case in CASES if case not in cases]
    selection = {
        "only": args.only,
        "skip": args.skip,
        "selected": len(cases),
        "total": len(CASES),
        "not_selected": not_selected,
    }
    print(f"Profile {args.profile}; {len(cases)} of {len(CASES)} case(s) selected; output {output_root}")
    if not_selected:
        print(f"Not selected (--only/--skip): {', '.join(not_selected)}")
    results = []
    for case in cases:
        print(f"-> {case.case_id} ...", end="", flush=True)
        record = run_case(case, ctx, output_root, args.timeout)
        results.append(record)
        print(f" {record['status']} ({record.get('seconds', 0)} s)")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": args.profile,
        "enabled": sorted(enabled),
        "selection": selection,
        "scientific_calculation": args.profile == "server",
        "note": (
            "local profile: structure generation only (calculator none, max_steps 0); "
            "any energies printed by the scripts are mock values"
            if args.profile == "local"
            else "server profile: UMA calculations requested"
        ),
        "environment": environment_info(),
        "summary": {s: sum(r["status"] == s for r in results) for s in ("PASS", "WARN", "FAIL", "SKIP")},
        "cases": results,
    }
    report_path = output_root / "smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"{'CASE':36s} {'METHOD':24s} {'STATUS':6s} {'SEC':>7s}  NOTES")
    for record in results:
        notes = "; ".join(record.get("notes", []))
        print(f"{record['case_id']:36s} {record['method']:24s} {record['status']:6s} {record.get('seconds', 0):7.1f}  {notes[:110]}")
    summary = report["summary"]
    print(f"\nPASS {summary['PASS']}  WARN {summary['WARN']}  FAIL {summary['FAIL']}  SKIP {summary['SKIP']}"
          f"  (ran {len(cases)} of {len(CASES)} cases)")
    if not_selected:
        print(f"Not selected (--only/--skip), so not in this table: {', '.join(not_selected)}")
    print(f"Report: {report_path}")
    failed = summary["FAIL"] > 0 or (args.strict and summary["WARN"] > 0)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
