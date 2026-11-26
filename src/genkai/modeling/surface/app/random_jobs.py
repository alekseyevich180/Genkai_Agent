"""Random, physically sensible pipelines from a structure library (``genkai-surface random``).

The library is a folder with ``crystals/catalog.json`` and ``molecules/catalog.json``
(the layout of the repository's ``sample/`` folder: Materials Project hull-stable
crystals and PubChem-checked VOC molecules). For every requested job the generator
draws a crystal, a scenario allowed for it, a molecule and the scenario's choices,
and writes an ordinary pipeline file (see ``pipeline.py``) that ``genkai-surface
check/run`` executes. A fixed ``--seed`` reproduces the same set.

Scenarios and their realism rules:

* ``adsorption``  slab -> molecule on exposed surface sites;
* ``defect``      slab -> anion vacancy (O for oxides, S for sulfides) -> molecule;
* ``metal``       slab -> [vacancy] -> Pt/Pd/Au/Ag 13-atom cluster -> molecule (on the metal
                  or on the support);
* ``sam``         oxides only: slab -> acetic acid anchored bidentate -> molecule beside it;
* ``ald``         slab -> amorphous TiO2 or SnO2 island (ALD-like) -> molecule;
* ``amorphous``   (needs ``--mlip``) binary oxides: crystal -> melt-quench amorphous bulk ->
                  amorphous slab -> O vacancy -> molecule;
* ``energy``      (needs ``--mlip``) slab -> vacancy (lowest energy of 4) -> relax -> cluster
                  (lowest of fcc/hcp) -> relax -> molecule (lowest energy).

Facets: one common low-index facet per crystal phase (``PHASE_FACETS``); every crystal
of the sample library was cut with it by the slab builder (stoichiometric slabs).
Facets marked polar are written with a note: fine for structures, dipole-sensitive in
energy calculations. All structure-only jobs are unrelaxed geometric candidates.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

GENERATOR = "genkai.modeling.surface.app.random_jobs"

# phase -> (facet in the conventional cell, polar termination). Checked on the sample library.
PHASE_FACETS: dict[str, tuple[str, bool]] = {
    "rocksalt": ("100", False),
    "wurtzite": ("10-10", False),
    "anatase": ("101", False),
    "cassiterite_rutile": ("110", False),
    "fluorite": ("111", False),
    "alpha_corundum": ("1-102", False),
    "alpha_hematite": ("1-102", False),
    "corundum": ("1-102", False),
    "alpha_quartz": ("10-10", False),
    "bixbyite": ("111", False),
    "3R": ("0001", False),
    "2H": ("0001", False),
    "CdI2_type": ("0001", False),
    "orthorhombic": ("001", False),
    "marcasite": ("110", False),
    "rhombohedral": ("001", True),
    "cubic": ("001", True),
    "hercynite": ("001", True),
    "cubic_ordered_MP_model": ("001", True),
    "pseudo_ladder": ("001", False),
    "two_leg_ladder": ("001", True),
}
# Crystals whose (001) is polar although the phase name is shared with non-polar ones.
POLAR_IDS = {"20_LaCrO3_orthorhombic_mp-19281"}
OXIDE_CATEGORIES = {"oxide", "A2O3", "perovskite_ABO3", "spinel_AB2O4", "AB2O3"}
SULFIDE_CATEGORIES = {"sulfide"}
METALS = ("Pt", "Pd", "Au", "Ag")
STRUCTURE_SCENARIOS = ("adsorption", "defect", "metal", "sam", "ald")
MLIP_SCENARIOS = ("amorphous", "energy")
SAM_MOLECULE_ID = "30_acetic_acid"
# Crystals left out of the ``sam`` scenario, with the reason (checked on the sample library):
# carboxylic acids anchor on oxides with Lewis-acidic metal cations; silica is functionalised
# with silanes instead, and two slabs have no pair of exposed cations for a bidentate carboxylate.
SAM_EXCLUDED: dict[str, str] = {
    "SiO2": "silica is functionalised with silanes; quartz (10-10) has no exposed Si pair for a bidentate carboxylate",
    "NaNbO3": "the (001) slab has no pair of exposed cations within the bidentate span",
}
AMORPHOUS_DENSITY_FACTOR = 0.93  # amorphous oxides are typically 5-10 % less dense than the crystal
TITLES = {
    "adsorption": "{mol} 吸附在 {crystal}{facet}",
    "defect": "{crystal}{facet} 表面{vac}空位 + {mol}",
    "metal": "{metal}13 负载的 {crystal}{facet}{vac_note} + {mol}",
    "sam": "乙酸 SAM 修饰的 {crystal}{facet} + {mol}",
    "ald": "ALD 非晶 {ald} 岛修饰的 {crystal}{facet} + {mol}",
    "amorphous": "非晶 {crystal}（熔融-淬火）表面 O 空位 + {mol}",
    "energy": "{metal}13/{crystal}{facet}，按 MLIP 能量逐步挑选 + {mol}",
}


def project_root() -> Path:
    """The checkout that holds src/genkai (anchored on the package, not on this file's depth)."""
    import genkai

    return Path(genkai.__file__).resolve().parents[2]


class LibraryError(ValueError):
    """A library folder that cannot be used."""


@dataclass
class Library:
    root: Path
    crystals: list[dict[str, Any]]
    molecules: list[dict[str, Any]]
    amorphous: dict[str, Path] = field(default_factory=dict)

    def crystal_path(self, row: dict[str, Any]) -> Path:
        return self.root / row["cif"]

    def molecule_path(self, row: dict[str, Any]) -> Path:
        return self.root / row["xyz"]


def load_library(root: str | Path, *, amorphous_dir: Path | None = None) -> Library:
    folder = Path(root).resolve()
    try:
        crystals = json.loads((folder / "crystals" / "catalog.json").read_text(encoding="utf-8"))["crystals"]
        molecules = json.loads((folder / "molecules" / "catalog.json").read_text(encoding="utf-8"))["molecules"]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise LibraryError(f"{folder} 不是结构库：需要 crystals/catalog.json 和 molecules/catalog.json（{exc}）") from None
    amorphous_dir = amorphous_dir or project_root() / "examples" / "recipes" / "inputs"
    amorphous = {name: amorphous_dir / f"a-{name}.vasp" for name in ("TiO2", "SnO2")
                 if (amorphous_dir / f"a-{name}.vasp").is_file()}
    return Library(folder, crystals, molecules, amorphous)


def crystal_kind(row: dict[str, Any]) -> str:
    if row["category"] in SULFIDE_CATEGORIES:
        return "sulfide"
    if row["category"] in OXIDE_CATEGORIES:
        return "oxide"
    return "other"


def facet_for(row: dict[str, Any]) -> tuple[str, bool] | None:
    entry = PHASE_FACETS.get(row["phase"])
    if entry is None:
        return None
    return entry[0], entry[1] or row["id"] in POLAR_IDS


def scenarios_for(row: dict[str, Any], *, mlip: bool, library: Library) -> list[str]:
    """Scenarios that make sense for this crystal (hull-stable crystals of the main collection only)."""
    kind = crystal_kind(row)
    if facet_for(row) is None or kind == "other" or row.get("collection", "stable") != "stable":
        return []
    allowed = ["adsorption", "defect", "metal"]
    if kind == "oxide" and row["formula"] not in SAM_EXCLUDED:
        allowed.append("sam")
    if library.amorphous:
        allowed.append("ald")
    if mlip:
        allowed.append("energy")
        if kind == "oxide" and row["category"] in {"oxide", "A2O3"}:
            allowed.append("amorphous")
    return allowed


def _relative(path: Path, start: Path) -> str:
    """Relative path when the job folder sits near the library, otherwise absolute."""
    try:
        relative = Path(os.path.relpath(path, start)).as_posix()
    except ValueError:  # different drive on Windows
        return path.as_posix()
    return path.as_posix() if relative.startswith("../../../") else relative


def _crystal_density(path: Path) -> float:
    from ase.io import read

    atoms = read(path)
    return float(atoms.get_masses().sum() * 1.66053906660 / atoms.get_volume())


def build_job(
    library: Library, row: dict[str, Any], scenario: str, molecule: dict[str, Any], rng: random.Random,
    *, out_dir: Path, name: str, mlip: str | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(pipeline mapping, record of the choices) for one random job."""
    facet, polar = facet_for(row)  # type: ignore[misc]
    kind = crystal_kind(row)
    anion = "O" if kind == "oxide" else "S"
    bulk = _relative(library.crystal_path(row), out_dir)
    mol_path = _relative(library.molecule_path(molecule), out_dir)
    choices: dict[str, Any] = {"scenario": scenario, "crystal": row["id"], "formula": row["formula"],
                               "phase": row["phase"], "facet": facet, "polar_facet": polar,
                               "molecule": molecule["id"], "molecule_name": molecule.get("name_zh") or molecule["name"]}
    lateral = 15 if scenario in {"metal", "energy"} else 12
    slab = {"method": "slab", "bulk": bulk, "facet": facet, "min_lateral_size": lateral}
    vacancy = {"method": "vacancy", "element": anion, "vacancy_counts": [1]}
    # 12 placement trials are enough for a geometric candidate (the method default is 60).
    adsorbate = {"method": "adsorbate", "molecule": mol_path, "site_symbols": ["auto"], "n_trials_single": 12}
    steps: list[dict[str, Any]]
    if scenario == "adsorption":
        steps = [slab, adsorbate]
    elif scenario == "defect":
        steps = [slab, vacancy, adsorbate]
        choices["vacancy_element"] = anion
    elif scenario == "metal":
        metal = rng.choice(METALS)
        with_vacancy = rng.random() < 0.5
        on_metal = rng.random() < 0.5
        cluster = {"method": "cluster", "cluster_element": metal, "cluster_atoms": 13, "cluster_structures": ["fcc"]}
        if on_metal:
            adsorbate["site_symbols"] = [metal]
        steps = [slab, *([vacancy] if with_vacancy else []), cluster, adsorbate]
        choices.update(metal=metal, vacancy=with_vacancy, molecule_on=metal if on_metal else "support")
    elif scenario == "sam":
        acid = next(m for m in library.molecules if m["id"] == SAM_MOLECULE_ID)
        sam = {"method": "sam", "molecule": _relative(library.molecule_path(acid), out_dir),
               "binding_mode": "bidentate", "counts": [1]}
        steps = [slab, sam, adsorbate]
        choices["sam_molecule"] = acid["id"]
    elif scenario == "ald":
        name_ald = rng.choice(sorted(library.amorphous))
        ald = {"method": "ald", "amorphous": _relative(library.amorphous[name_ald], out_dir),
               "coverage": "partial", "island_atoms": 20}
        steps = [slab, ald, adsorbate]
        choices["ald_overlayer"] = f"a-{name_ald}"
    elif scenario == "amorphous":
        density = round(_crystal_density(library.crystal_path(row)) * AMORPHOUS_DENSITY_FACTOR, 2)
        steps = [
            {
                "method": "amorphous_bulk",
                "crystal": bulk,
                "density": density,
                "initial_rattle": 0.2,
                "max_melt_retries": 2,
                "melt_retry_step": 1000,
                "max_melt_temperature": 5000,
            },
            {"method": "amorphous_slab", "thickness": 10, "stoichiometric": True, "samples": 2, "pick": "lowest_energy"},
            {"method": "vacancy", "element": "O", "vacancy_counts": [1], "samples_per_count": 4, "pick": "lowest_energy"},
            {**adsorbate, "pick": "lowest_energy"},
        ]
        choices["amorphous_density_g_cm3"] = density
    elif scenario == "energy":
        metal = rng.choice(METALS)
        steps = [
            slab,
            {**vacancy, "samples_per_count": 4, "pick": "lowest_energy"},
            {"method": "relax"},
            {"method": "cluster", "cluster_element": metal, "cluster_atoms": 13,
             "cluster_structures": ["fcc", "hcp"], "pick": "lowest_energy"},
            {"method": "relax"},
            {**adsorbate, "site_symbols": [metal], "pick": "lowest_energy"},
        ]
        choices["metal"] = metal
    else:
        raise ValueError(f"unknown scenario {scenario!r}")
    mapping: dict[str, Any] = {"output": f"runs/{name}"}
    if scenario in MLIP_SCENARIOS:
        mapping["mlip"] = mlip
    mapping["pipeline"] = steps
    return mapping, choices


def _header(choices: dict[str, Any], row: dict[str, Any], molecule: dict[str, Any], seed: int, number: int) -> str:
    vac = choices.get("vacancy_element", "O")
    title = TITLES[choices["scenario"]].format(
        mol=choices["molecule_name"], crystal=row["formula"], facet=f"({choices['facet']})", vac=vac,
        metal=choices.get("metal", ""), ald=choices.get("ald_overlayer", "").replace("a-", ""),
        vac_note=" 含表面空位" if choices.get("vacancy") else "",
    )
    lines = [
        f"# 随机生成（seed {seed}，第 {number} 个）：{title}",
        f"# 晶体：{row['id']}（{row['formula']}，{row['phase']}，MP {row.get('legacy_numeric_id', row.get('material_id'))}，"
        f"凸包稳定={row.get('is_stable')}）",
        f"# 分子：{molecule['id']}（{molecule.get('name_zh', '')} {molecule['name']}，PubChem CID {molecule.get('pubchem_cid')}）",
    ]
    if choices["polar_facet"]:
        lines.append(f"# 注意：({choices['facet']}) 是极性终止面；结构生成可用，能量计算需考虑偶极（如偶极校正或对称 slab）。")
    if choices["scenario"] in MLIP_SCENARIOS:
        lines.append("# 需要 MLIP（顶层 mlip 为 genkai.yaml 中的配置名），只在获准做真实计算的服务器上运行。")
    else:
        lines.append("# 只生成未弛豫的几何结构，不计算能量。")
    return "\n".join(lines) + "\n\n"


def generate(
    library: Library,
    out_dir: Path,
    *,
    count: int,
    seed: int,
    scenarios: list[str] | None = None,
    crystals: list[str] | None = None,
    molecules: list[str] | None = None,
    mlip: str | None = None,
    nonpolar_only: bool = False,
) -> list[dict[str, Any]]:
    """Write ``count`` random pipeline files and ``random_index.json``; return the records."""
    import yaml

    rng = random.Random(seed)
    wanted = set(scenarios or (*STRUCTURE_SCENARIOS, *(MLIP_SCENARIOS if mlip else ())))
    unknown = wanted - set(STRUCTURE_SCENARIOS) - set(MLIP_SCENARIOS)
    if unknown:
        raise LibraryError(f"未知场景 {', '.join(sorted(unknown))}；可用：{', '.join((*STRUCTURE_SCENARIOS, *MLIP_SCENARIOS))}")
    if wanted & set(MLIP_SCENARIOS) and not mlip:
        raise LibraryError("amorphous、energy 场景需要 MLIP：加 --mlip <genkai.yaml 中的配置名>")

    def matches(row: dict[str, Any], keys: list[str] | None) -> bool:
        return not keys or any(k.lower() in (row["id"].lower(), row.get("formula", "").lower(), row.get("name", "").lower())
                               or row["id"].lower().startswith(k.lower()) for k in keys)

    pool = []
    for row in library.crystals:
        if matches(row, crystals):
            facet = facet_for(row)
            if nonpolar_only and (facet is None or facet[1]):
                continue
            usable = [s for s in scenarios_for(row, mlip=bool(mlip), library=library) if s in wanted]
            if usable:
                pool.append((row, usable))
    mols = [m for m in library.molecules if matches(m, molecules)]
    if not pool:
        raise LibraryError("没有符合条件的晶体/场景组合；用 --list 查看可用的晶体和场景")
    if not mols:
        raise LibraryError("没有符合条件的分子；用 --list 查看分子")
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for number in range(1, count + 1):
        row, usable = rng.choice(pool)
        scenario = rng.choice(usable)
        molecule = rng.choice(mols)
        name = f"{number:02d}_{scenario}_{row['formula']}_{molecule['name'].replace(' ', '_')}"
        mapping, choices = build_job(library, row, scenario, molecule, rng, out_dir=out_dir, name=name, mlip=mlip)
        path = out_dir / f"{name}.yaml"
        path.write_text(_header(choices, row, molecule, seed, number)
                        + yaml.safe_dump(mapping, allow_unicode=True, sort_keys=False), encoding="utf-8")
        records.append({"file": path.name, **choices})
    (out_dir / "random_index.json").write_text(json.dumps({
        "generator": GENERATOR, "library": library.root.as_posix(), "seed": seed, "count": count,
        "scenarios": sorted(wanted), "mlip": mlip, "nonpolar_only": nonpolar_only, "jobs": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return records


def describe(library: Library, stream: TextIO, *, mlip: bool, nonpolar_only: bool = False) -> None:
    print(f"结构库：{library.root}", file=stream)
    print(f"晶体 {len(library.crystals)} 个（晶面 / 可用场景）：", file=stream)
    for row in library.crystals:
        facet = facet_for(row)
        usable = scenarios_for(row, mlip=mlip, library=library)
        text = f"({facet[0]}){' 极性' if facet[1] else ''}" if facet else "无晶面规则"
        if nonpolar_only and facet and facet[1]:
            usable = []
            reason = "不可用：极性终止面（--nonpolar-only 已排除）"
        elif row.get("collection") != "stable":
            reason = "不可用：非凸包稳定的参考相"
        else:
            reason = "不可用：没有晶面规则"
        print(f"  {row['id']:<48s} {text:<12s} {', '.join(usable) or reason}", file=stream)
    print(f"分子 {len(library.molecules)} 个：", file=stream)
    print("  " + "、".join(f"{m['id']}({m.get('name_zh', '')})" for m in library.molecules), file=stream)
    print(f"ALD 非晶覆盖层：{', '.join(f'a-{k}' for k in sorted(library.amorphous)) or '无'}", file=stream)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--library", type=Path, default=None,
                        help="结构库文件夹（含 crystals/catalog.json、molecules/catalog.json）；默认项目里的 sample/")
    parser.add_argument("-n", "--count", type=int, default=6, help="生成几个任务")
    parser.add_argument("--seed", type=int, default=1, help="随机种子；相同种子得到相同的一组任务")
    parser.add_argument("-o", "--output", type=Path, default=Path("random_jobs"), help="写入流水线文件的文件夹")
    parser.add_argument("--scenarios", default=None,
                        help=f"只用这些场景（逗号分隔）：{', '.join((*STRUCTURE_SCENARIOS, *MLIP_SCENARIOS))}")
    parser.add_argument("--crystals", default=None, help="只用这些晶体（化学式或编号前缀，逗号分隔），如 SnO2,ZnO,13")
    parser.add_argument("--molecules", default=None, help="只用这些分子（英文名或编号前缀，逗号分隔），如 ethanol,acetone")
    parser.add_argument("--mlip", default=None,
                        help="genkai.yaml 中的配置名；给出后加入 amorphous（先非晶）和 energy（按能量挑选）场景")
    parser.add_argument("--nonpolar-only", action="store_true",
                        help="排除极性终止面晶体（仅保留非极性晶面，适合能量计算）")
    parser.add_argument("--list", action="store_true", help="列出库里可用的晶体、晶面、场景和分子，不生成文件")


def run(args: argparse.Namespace, stream: TextIO = sys.stdout) -> int:
    root = args.library or project_root() / "sample"
    nonpolar_only = bool(getattr(args, "nonpolar_only", False))
    try:
        library = load_library(root)
        if args.list:
            describe(library, stream, mlip=bool(args.mlip), nonpolar_only=nonpolar_only)
            return 0
        if args.count < 1:
            raise LibraryError("--count 至少为 1")
        split = (lambda text: [item.strip() for item in text.split(",") if item.strip()] if text else None)
        records = generate(library, args.output.resolve(), count=args.count, seed=args.seed,
                           scenarios=split(args.scenarios), crystals=split(args.crystals),
                           molecules=split(args.molecules), mlip=args.mlip, nonpolar_only=nonpolar_only)
    except LibraryError as exc:
        print(f"无法生成：{exc}", file=stream)
        return 2
    print(f"已在 {args.output} 生成 {len(records)} 个流水线（seed {args.seed}）：", file=stream)
    for record in records:
        print(f"  {record['file']}", file=stream)
    print(f"清单：{args.output / 'random_index.json'}", file=stream)
    print(f"下一步：genkai-surface check {args.output}/*.yaml，然后 genkai-surface run {args.output}/*.yaml", file=stream)
    return 0
