"""Job-file interface to the surface-modeling methods (console script ``genkai-surface``).

People other than the developers describe one modeling task in a short YAML
file instead of learning each method's command line. This module

* lists the open methods and writes commented job templates (``methods``,
  ``template``);
* validates a job file against the method's option table below and against the
  method's own argparse parser (``check``);
* runs the method's existing entry point in a subprocess with the
  structure-only settings locked (``run``), reads every produced structure,
  checks overlaps, vacuum and fixed atoms, and writes ``manifest.json``
  (:class:`genkai.contracts.run.RunManifest`) next to the outputs.

Existing jobs stay structure-only. An explicit ``mlip`` profile enables energy
calculations in the Python environment configured in genkai.yaml. Dedicated
search methods select the default profile. Materials Project stays offline.

Job files are read with PyYAML's ``BaseLoader`` so every scalar stays a string
and is converted by the option table: ``facet: 0001`` stays ``"0001"`` and
``010`` is not read as an octal number.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import importlib
import io
import locale
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, TextIO

import yaml

from ..mlip.mlip_config import MlipConfigError, MlipProfile, find_config, load_config, probe_profile

PROG = "genkai-surface"
STRUCTURE_ONLY_NOTE = "只生成未弛豫的结构，没有计算能量（calculator 固定为 none）。"
UNSET_STRINGS = {"", "null", "Null", "NULL", "~"}
JOB_KEYS = ("method", "output", "description", "mlip", "config")


# ---------------------------------------------------------------------------
# Option tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Option:
    """One job-file key and the method CLI flag it maps to.

    kind: path | int | float | str | facet | ints | floats | words.
    Defaults and choices are read from the method's own parser, not repeated here.
    """

    key: str
    flag: str
    kind: str
    help: str
    required: bool = False
    example: str | None = None
    length: int | None = None
    allow_auto: bool = False
    nargs: bool = False
    suggested: bool = False  # optional, but shown filled in the template's first section


@dataclass(frozen=True)
class Group:
    keys: tuple[str, ...]
    mode: str  # one: exactly one; any: at least one; at_most_one
    help: str


@dataclass(frozen=True)
class Method:
    name: str
    title: str
    summary: str
    module: str
    options: tuple[Option, ...]
    output_flag: str
    outputs: tuple[str, ...]
    groups: tuple[Group, ...] = ()
    locked: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    calculator_flag: str | None = None
    requires_mlip: bool = False
    subcommand: str | None = None
    style: str = "dash"
    fixed_expected: bool = True
    vacuum_expected: bool = True  # False for bulk outputs (no vacuum layer by design)

    def option(self, key: str) -> Option:
        return next(option for option in self.options if option.key == key)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(option.key for option in self.options)


FIXED_FRACTION = Option("fixed_fraction", "--fixed-fraction", "float", "固定 slab 下部这一比例厚度内的原子；0 表示不固定")
SEED = Option("seed", "--seed", "int", "随机数种子；相同种子得到相同结构")
SAMPLER = Option("sampler", "--sampler", "str", "搜索优化器，默认 periodic_gp，也可选择 tpe")
EXPORT = Option("export", "--export", "words", "另外导出的格式：cif、vasp（可写两个），或 none")

SUBSTRATE_OPTIONS = (
    Option("bulk", "--bulk", "path", "块体晶体文件，程序自动切出晶面", example="<块体结构.cif>"),
    Option("surface", "--surface", "path", "已有的 slab 文件", example="<slab.cif>"),
    Option("bulk_format", "--bulk-format", "str", "块体文件格式（扩展名无法判断时填写，如 vasp）"),
    Option("surface_format", "--surface-format", "str", "slab 文件格式（扩展名无法判断时填写，如 vasp、extxyz）"),
    Option(
        "facet", "--facet", "facet",
        "从 bulk 切出的晶面（常规晶胞的 Miller 指数），如 \"110\" 或 [1, 1, 0]；不写则按内置稳定晶面表选择",
        example='"110"',
    ),
    Option("min_slab_size", "--min-slab-size", "float", "slab 最小厚度（Å）"),
    Option("min_vacuum_size", "--min-vacuum-size", "float", "真空层厚度（Å）"),
    Option("min_lateral_size", "--min-lateral-size", "float", "面内最小宽度（Å），不足时自动扩胞"),
    Option("repeat_xy", "--repeat-xy", "ints", "面内扩胞倍数，如 [2, 2]（写了就不再按 min_lateral_size 自动扩胞）", length=2),
    FIXED_FRACTION,
    Option("fixed_layers", "--fixed-layers", "int", "改为固定底部这么多层原子"),
)
SUBSTRATE_GROUP = Group(("bulk", "surface"), "one", "基底：bulk（块体，自动切面）与 surface（已有 slab）二选一")

METHODS: dict[str, Method] = {}


def _register(method: Method) -> None:
    METHODS[method.name] = method


_register(Method(
    name="slab",
    title="切面（slab）",
    summary="从块体晶体切出表面 slab；不写晶面时按内置稳定晶面表选择",
    module="genkai.modeling.surface.builders.slab",
    options=(
        Option("bulk", "--bulk", "path", "块体晶体文件（CIF、POSCAR 等）", required=True, example="<块体结构.cif>"),
        Option(
            "facet", "--facet", "facet",
            "晶面（常规晶胞的 Miller 指数），如 \"110\"、\"0001\" 或 [1, 1, 0]；不写则按内置稳定晶面表选择",
            example='"110"',
        ),
        Option("min_slab_size", "--min-slab-size", "float", "slab 最小厚度（Å）"),
        Option("min_vacuum_size", "--min-vacuum-size", "float", "真空层厚度（Å）"),
        Option("min_lateral_size", "--min-lateral-size", "float", "面内最小宽度（Å），不足时自动扩胞"),
        Option("repeat_xy", "--repeat-xy", "ints", "面内扩胞倍数，如 [2, 2]；auto 表示按 min_lateral_size", length=2, allow_auto=True),
        FIXED_FRACTION,
        Option("fixed_layers", "--fixed-layers", "int", "改为固定底部这么多层原子"),
        Option("slab_position", "--slab-position", "str", "bottom：slab 放在晶胞底部、真空在上方；center：两侧都有真空"),
        Option("bottom_margin", "--bottom-margin", "float", "slab 放在底部时，最低原子与晶胞底面的间距（Å）"),
        Option("miller_basis", "--miller-basis", "str", "晶面指数参照的晶胞：auto、conventional（常规晶胞）或 input（输入晶胞）"),
    ),
    output_flag="--output-dir",
    outputs=("slab.extxyz",),
    locked=("--calculator=none", "--relax-steps=0"),
    notes=("不写 facet 时按内置稳定晶面表选择，不计算表面能；表里没有的材料会停下并提示，请写 facet。",),
    calculator_flag="--calculator",
))

_register(Method(
    name="vacancy",
    title="氧空位",
    summary="在含氧 slab 的表面去掉 O 原子，生成不同空位数的结构",
    module="genkai.modeling.surface.builders.vacancy",
    options=(
        Option("input", "--input", "path", "含氧化物的 slab 文件（只处理 O 空位）", required=True, example="<slab.cif>"),
        Option("vacancy_counts", "--vacancy-counts", "ints", "空位数，如 [1, 2]，每个数生成一组结构"),
        Option("samples_per_count", "--samples-per-count", "int", "每个空位数抽取的构型数"),
        Option("z_frac_min", "--z-frac-min", "float", "可选 O 位点的最小分数坐标 z（0–1，按整个晶胞高度）"),
        Option("z_frac_max", "--z-frac-max", "float", "可选 O 位点的最大分数坐标 z（0–1，按整个晶胞高度）"),
        Option("surface_depth", "--surface-depth", "float", "只取表面顶部以下这么深（Å）内的 O（表面空位）；写了就不再用 z_frac"),
        Option("components", "--components", "words", "可去掉哪些部分的 O：substrate（基底）、overlayer（ALD 覆盖层）；默认 substrate"),
        SEED,
        FIXED_FRACTION,
    ),
    output_flag="--output-dir",
    outputs=("structures/*.cif",),
    locked=("--calculator=none", "--max-steps=0"),
    notes=(
        "vacancy_energy_landscape.csv 和图里的能量是模拟值，没有物理意义；只使用 structures/ 里的结构。",
        "stable_vacancy_structure.cif 是按模拟能量挑的，clean_relaxed.cif 没有弛豫：文件名里的 stable、relaxed 在这里不成立。",
        "z_frac 按整个晶胞高度计算；slab 放在晶胞底部时，表层原子的 z 通常远小于 1。",
    ),
    calculator_flag="--calculator",
))

_register(Method(
    name="adsorbate",
    title="分子吸附",
    summary="把气体或有机分子放到 slab 表面位点上，生成不同覆盖度的结构",
    module="genkai.modeling.surface.builders.adsorbate",
    options=(
        Option("surface", "--surface", "path", "slab 文件", required=True, example="<slab.cif>"),
        Option("molecule", "--molecule", "path", "分子文件（XYZ、CIF、POSCAR 等）", required=True, example="<分子.xyz>"),
        Option("site_symbols", "--site-symbols", "words", "吸附位点的表面元素，如 Ce；多个元素写成列表", required=True, example="Ce"),
        Option("site_components", "--site-components", "words",
               "位点限定在哪些部分：substrate、overlayer、cluster、sam；默认不限（被团簇/SAM 盖住的位点总会排除）"),
        Option("coverage_counts", "--coverage-counts", "ints", "每个晶胞的分子数，如 [1, 2]；不写则从 1 到最多能放下的数"),
        Option("patterns", "--patterns", "words", "多分子排布方式：uniform、clustered、stripe、island、random"),
        Option("random_repeats", "--random-repeats", "int", "random 排布重复几次"),
        Option("n_trials_single", "--n-trials-single", "int", "单个分子位置的采样次数（只影响候选几何）"),
        SAMPLER,
        Option("site_z_tolerance", "--site-z-tolerance", "float", "表面位点的高度容差（Å）"),
        Option("max_sites", "--max-sites", "int", "最多使用的表面位点数"),
        Option("site_group_size", "--site-group-size", "int", "每个吸附位点包含的表面原子数"),
        Option("site_radius", "--site-radius", "float", "分子在位点周围的水平采样半径（Å）"),
        Option("z_gap_min", "--z-gap-min", "float", "分子与表面的最小初始间距（Å）"),
        Option("z_gap_max", "--z-gap-max", "float", "分子与表面的最大初始间距（Å）"),
        SEED,
        FIXED_FRACTION,
    ),
    output_flag="--output-dir",
    outputs=("structures/*.cif",),
    locked=("--calculator=none", "--max-steps=0"),
    notes=(
        "adsorbate_coverage_landscape.csv 和图里的能量是模拟值，没有物理意义；只使用 structures/ 里的结构。",
        "*_relaxed.cif 没有弛豫，*best*.cif 是按模拟能量挑的：文件名里的 relaxed、best 在这里不成立。",
        "放置多个分子时不检查分子之间的重叠，大分子在小晶胞上可能出现原子过近（检查结果标为 WARN）。",
    ),
    calculator_flag="--calculator",
))

_register(Method(
    name="cluster",
    title="金属团簇负载",
    summary="构建 fcc/hcp/bcc 金属团簇并放到 slab 表面（几何放置，不优化）",
    module="genkai.modeling.surface.builders.metal_cluster.surface_cluster_builder",
    options=(
        Option("surface", "--surface", "path", "slab 文件", required=True, example="<slab.cif>"),
        Option("cluster_element", "--cluster_element", "str", "金属元素，如 Pt", example="Pt"),
        Option("cluster_bulk_file", "--cluster_bulk_file", "path", "单质块体文件，用来确定元素和晶格常数", example="<金属块体.cif>"),
        Option("cluster_atoms", "--cluster_atoms", "int", "团簇原子数", example="13"),
        Option("cluster_layers", "--cluster_layers", "int", "保留的径向壳层数", example="2"),
        Option("cluster_radius", "--cluster_radius", "float", "团簇半径（Å）", example="4.0"),
        Option("cluster_structures", "--cluster_structures", "words", "团簇结构类型：fcc、hcp、bcc，可写多个；不写则三种都建", nargs=True),
        Option("cluster_a", "--cluster_a", "float", "手动指定晶格常数 a（Å）"),
        Option("cluster_c", "--cluster_c", "float", "手动指定 hcp 的晶格常数 c（Å）"),
        Option("x_frac", "--x_frac", "float", "团簇在 slab 面内的分数坐标 x"),
        Option("y_frac", "--y_frac", "float", "团簇在 slab 面内的分数坐标 y"),
        Option("z_height", "--z_height", "float", "团簇底部与表面的初始间距（Å）"),
        Option("phi", "--phi", "float", "欧拉旋转角 phi（度）"),
        Option("theta", "--theta", "float", "欧拉旋转角 theta（度）"),
        Option("psi", "--psi", "float", "欧拉旋转角 psi（度）"),
    ),
    groups=(
        Group(("cluster_element", "cluster_bulk_file"), "any", "团簇元素：cluster_element 与 cluster_bulk_file 至少写一个"),
        Group(("cluster_atoms", "cluster_layers", "cluster_radius"), "one", "团簇大小：cluster_atoms、cluster_layers、cluster_radius 三选一"),
    ),
    output_flag="--output_dir",
    outputs=("*_on_surface.cif",),
    notes=("团簇按几何规则放置，没有做结构优化或能量筛选。",),
))

_register(Method(
    name="sam",
    title="SAM 自组装单分子层",
    summary="把用户提供的分子按选定结合方式锚定在表面（膦酸、羧酸、硫醇）",
    module="genkai.modeling.surface.builders.sam",
    options=(
        *SUBSTRATE_OPTIONS,
        Option("molecule", "--molecule", "path", "SAM 分子文件（CIF、XYZ、POSCAR 等）", required=True, example="<分子.xyz>"),
        Option("molecule_format", "--molecule-format", "str", "分子文件格式（扩展名无法判断时填写）"),
        Option(
            "binding_mode", "--binding-mode", "str",
            "结合方式。膦酸：monodentate | bidentate | tridentate；羧酸：monodentate | bidentate；"
            "硫醇：top | bridge | hollow | fcc | hcp",
            required=True, example="monodentate",
        ),
        Option("counts", "--counts", "ints", "每个晶胞的分子数，如 [1, 2]，每个数生成一帧", example="[1, 2]"),
        Option("density", "--density", "float", "目标密度（个/nm²），换算成整数个分子", example="2.0"),
        Option("anchor_kind", "--anchor-kind", "str", "锚定基团：phosphonic、carboxylic、thiol（分子里有多个基团时必须写）"),
        Option("anchor_atoms", "--anchor-atoms", "ints", "锚定原子在分子文件里的序号（从 0 开始），如 [3, 4, 5]"),
        Option("tilt", "--tilt", "float", "分子轴相对表面法向的倾角（度）"),
        Option("azimuth", "--azimuth", "float", "倾斜方向，相对晶胞 a 轴（度）"),
        Option("bond_length", "--bond-length", "float", "锚定原子与表面位点的键长（Å），默认用共价半径之和"),
        Option("bond_tolerance", "--bond-tolerance", "float", "锚定键长允许偏离目标值的最大量（Å），超过就放弃该位点"),
        Option("acidic_h", "--acidic-h", "str", "酸性 H：auto（含 O 表面转成表面 OH，否则去掉）、transfer、remove、keep"),
        Option("site_symbols", "--site-symbols", "words", "锚定的表面元素，如 Sn 或 Au；不写则自动判断"),
        Option("surface_depth", "--surface-depth", "float", "表面层厚度（Å），只在这一层里找位点"),
        Option("max_span", "--max-span", "float", "同一锚定位点组内原子的最大距离（Å）"),
        Option("pattern", "--pattern", "str", "多分子排布：uniform、clustered、random"),
        SEED,
        Option("n_starts", "--n-starts", "int", "每个分子绕自身轴尝试的起始转角数（几何拟合的起点）"),
        EXPORT,
    ),
    groups=(
        SUBSTRATE_GROUP,
        Group(("counts", "density"), "one", "覆盖度：counts 与 density 二选一"),
    ),
    output_flag="--output-dir",
    outputs=("sam_structures.extxyz",),
    locked=("--calculator=none",),
    notes=("分子按几何规则锚定，结构未弛豫。",),
))

_register(Method(
    name="ald",
    title="ALD 非晶覆盖层",
    summary="在晶体表面覆盖非晶氧化物：全覆盖成膜（full），或部分覆盖成岛（partial）",
    module="genkai.modeling.surface.builders.amorphous_overlayer",
    options=(
        *SUBSTRATE_OPTIONS,
        Option("amorphous", "--amorphous", "path", "非晶块体结构（周期性晶胞）", required=True, example="<非晶块体.vasp>"),
        Option("amorphous_format", "--amorphous-format", "str", "非晶文件格式（无扩展名的 POSCAR 写 vasp）"),
        Option("coverage", "--coverage", "str", "full：连续膜；partial：岛状", required=True, example="full"),
        Option("thickness", "--thickness", "float", "膜厚（Å），coverage: full 时必填", example="6", suggested=True),
        Option("island_atoms", "--island-atoms", "int", "岛的原子数（部分覆盖）"),
        Option("island_radius", "--island-radius", "float", "岛的半球半径（Å，部分覆盖）"),
        Option("island_position", "--island-position", "floats", "岛中心的面内分数坐标，如 [0.5, 0.5]", length=2),
        Option("island_separation", "--island-separation", "float", "岛与周期镜像之间的最小间隙（Å）"),
        Option("interface_gap", "--interface-gap", "float", "slab 顶部与覆盖层底部的间距（Å）"),
        Option("max_strain", "--max-strain", "float", "全覆盖晶格匹配允许的最大面内应变（0.05 即 5%）"),
        Option("max_area", "--max-area", "float", "晶格匹配超胞的最大面积（Å²）"),
        Option("film_fit", "--film-fit", "str", "全覆盖成膜方式：auto（先晶格匹配，不行就切割）、strain（只用晶格匹配）、cut（切割并修复接缝）"),
        Option("samples", "--samples", "int", "从非晶块体切出几个不同的样本"),
        SEED,
        EXPORT,
    ),
    groups=(
        SUBSTRATE_GROUP,
        Group(("island_atoms", "island_radius"), "at_most_one", "岛的大小：island_atoms 与 island_radius 最多写一个"),
    ),
    output_flag="--output-dir",
    outputs=("ald_structures.extxyz",),
    locked=("--calculator=none",),
    notes=(
        "覆盖层只做了几何拼接，没有退火或弛豫。",
        "coverage: partial 时另外输出 islands/ 里的岛和 substrate_slab.extxyz，以后可作为能量搜索的输入。",
    ),
))

_register(Method(
    name="amorphous_slab",
    title="纯非晶表面",
    summary="从非晶块体切出非晶 slab（只保留不需要删原子的切割位置）",
    module="genkai.modeling.surface.builders.amorphous_slab",
    options=(
        Option("amorphous", "--amorphous", "path", "非晶块体结构（周期性晶胞）", required=True, example="<非晶块体.vasp>"),
        Option("amorphous_format", "--amorphous-format", "str", "非晶文件格式（无扩展名的 POSCAR 写 vasp）"),
        Option("thickness", "--thickness", "float", "slab 厚度（Å）", required=True, example="8"),
        Option("vacuum", "--vacuum", "float", "slab 上方的真空层（Å）"),
        Option("min_lateral_size", "--min-lateral-size", "float", "面内最小宽度（Å），不足时自动扩胞"),
        Option("repeat_xy", "--repeat-xy", "ints", "面内扩胞倍数，如 [2, 2]", length=2),
        FIXED_FRACTION,
        Option("samples", "--samples", "int", "切出几个不同的表面"),
        SEED,
        EXPORT,
    ),
    output_flag="--output-dir",
    outputs=("amorphous_slab_structures.extxyz",),
    notes=("只做几何切割，结构未弛豫。",),
))

RELAX_OPTIONS = (
    Option("fmax", "--fmax", "float", "弛豫的力收敛阈值（eV/Å）；默认读取 MLIP 配置"),
    Option("max_steps", "--max-steps", "int", "弛豫步数上限；0 为单点计算，默认读取 MLIP 配置"),
)
SEARCH_STEPS = Option("screen_steps", "--screen-steps", "int", "每个搜索候选的短弛豫步数")

# Existing structure-generation methods opt into energies with just mlip: <profile>.
for _name in ("slab", "vacancy", "adsorbate"):
    _method = METHODS[_name]
    _extra = (
        (Option("fmax", "--fmax", "float", "弛豫力阈值（eV/Å）"),
         Option("relax_steps", "--relax-steps", "int", "每次求能量前的弛豫步数；默认 0"),
         Option("max_index", "--max-index", "int", "晶面排序的最高 Miller 指数"))
        if _name == "slab" else RELAX_OPTIONS
    )
    if _name == "vacancy":
        _extra += (Option("mu_o", "--mu-o", "float", "氧化学势参考（eV），真实空位能计算时请自行确定"),)
    METHODS[_name] = replace(_method, options=(*_method.options, *_extra))

_register(Method(
    name="sam_search", title="SAM 能量搜索", summary="锚定参数搜索、短弛豫、精排与覆盖度计算",
    module="genkai.modeling.surface.screening.sam_search", calculator_flag="--search-calculator", requires_mlip=True,
    options=(
        *SUBSTRATE_OPTIONS,
        Option("molecule", "--molecule", "path", "SAM 分子文件", required=True, example="<分子.xyz>"),
        Option("binding_mode", "--binding-mode", "str", "结合方式，例如 monodentate", required=True, example="monodentate"),
        Option("molecule_format", "--molecule-format", "str", "分子格式"),
        Option("anchor_kind", "--anchor-kind", "str", "锚定基团类型"),
        Option("anchor_atoms", "--anchor-atoms", "ints", "锚定原子序号（从 0 开始）"),
        Option("site_symbols", "--site-symbols", "words", "锚定表面元素"),
        Option("acidic_h", "--acidic-h", "str", "酸性 H 的处理方式"),
        Option("bond_length", "--bond-length", "float", "锚定键长（Å）"),
        Option("max_span", "--max-span", "float", "同组锚定位点的最大跨度（Å）"),
        Option("n_trials", "--n-trials", "int", "搜索候选数"),
        SAMPLER,
        Option("top_k", "--top-k", "int", "最终弛豫的候选数"),
        Option("max_tilt", "--max-tilt", "float", "最大倾角（度）"),
        Option("coverage_counts", "--coverage-counts", "ints", "覆盖度分子数，例如 [1, 2]"),
        Option("binding_tolerance", "--binding-tolerance", "float", "锚定键容差（Å）"),
        *RELAX_OPTIONS, SEARCH_STEPS, SEED, EXPORT,
    ),
    groups=(SUBSTRATE_GROUP,), output_flag="--output-dir", outputs=("sam_search_structures.extxyz",),
    locked=("--calculator=none",), notes=("真实能量来自所选 MLIP 配置；需验证模型适用性。",),
))

_register(Method(
    name="amorphous_bulk", title="非晶块体（熔融-淬火）",
    summary="从晶体出发，用 MLIP 分子动力学熔融-淬火得到非晶块体，可再交给 amorphous_slab 切出表面",
    module="genkai.modeling.surface.builders.amorphous_bulk", calculator_flag="--calculator", requires_mlip=True,
    fixed_expected=False, vacuum_expected=False,
    options=(
        Option("crystal", "--crystal", "path", "晶体块体结构（CIF、POSCAR 等）", required=True, example="<晶体.cif>"),
        Option("crystal_format", "--crystal-format", "str", "晶体文件格式（扩展名无法判断时填写，如 vasp）"),
        Option("supercell", "--supercell", "ints", "扩胞倍数，如 [3, 3, 4]", length=3),
        Option("min_atoms", "--min-atoms", "int", "自动选择接近立方、原子数不少于此值的超胞"),
        Option("density", "--density", "float", "目标密度（g/cm³）；不写则保持晶体密度（非晶氧化物通常低 5–10%）"),
        Option("melt_temperature", "--melt-temperature", "float", "熔融温度（K），约为熔点的 1.5–2 倍"),
        Option("melt_ps", "--melt-ps", "float", "熔融时长（ps）"),
        Option("quench_rate", "--quench-rate", "float", "线性降温速率（K/ps）"),
        Option("final_temperature", "--final-temperature", "float", "降温终点和退火温度（K）"),
        Option("anneal_ps", "--anneal-ps", "float", "终点温度下的退火时长（ps）"),
        Option("timestep", "--timestep", "float", "MD 步长（fs）；含 H 时用 0.5"),
        Option("friction", "--friction", "float", "Langevin 摩擦系数（1/fs）"),
        Option("samples", "--samples", "int", "独立熔融-淬火的次数（不同初速度）"),
        SEED,
        *RELAX_OPTIONS,
        Option("no_cell_relax", "--no-cell-relax", "bool", "true 时最后只弛豫原子，不弛豫晶胞"),
        Option("no_crystal_reference", "--no-crystal-reference", "bool", "true 时不计算弛豫晶体的参考能量"),
        Option("trajectory_interval", "--trajectory-interval", "int", "每隔多少步保存一帧 MD 轨迹；0 不保存"),
        EXPORT,
    ),
    groups=(Group(("supercell", "min_atoms"), "at_most_one", "超胞：supercell 与 min_atoms 最多写一个"),),
    output_flag="--output-dir", outputs=("amorphous_bulk_structures.extxyz",),
    notes=(
        "熔融-淬火是真实的分子动力学计算，只在获准的服务器上运行；默认温度程序约 7.4 万步 MD。",
        "结构取决于势函数、温度程序和降温速率；请对照 amorphous_bulk_manifest.json 中的熔融位移、配位数和 RDF 检查。",
        "输出的 amorphous_bulk_000.extxyz 可作为 amorphous_slab、ald、amorphous_surfaces 的 amorphous 输入。",
    ),
))

_register(Method(
    name="relax", title="弛豫或单点（MLIP）",
    summary="用 MLIP 逐个弛豫结构文件里的每一帧并给出能量；流水线用它做中间弛豫和按能量挑候选",
    module="genkai.modeling.surface.screening.relax", calculator_flag="--calculator", requires_mlip=True,
    fixed_expected=False, vacuum_expected=False,
    options=(
        Option("structures", "--structures", "path", "结构文件（extxyz 可含多帧）", required=True, example="<structures.extxyz>"),
        *RELAX_OPTIONS,
        Option("relax_cell", "--relax-cell", "bool", "true 时同时弛豫晶胞（块体用；slab 保持 false）"),
    ),
    output_flag="--output-dir", outputs=("relaxed_structures.extxyz",),
    notes=("能量只能在同一组成、同一模型之间比较；结果见 relax_manifest.json。",),
))

ANNEAL_OPTIONS = (
    Option("anneal_steps", "--anneal-steps", "int", "退火 MD 步数；默认 0（关闭）"),
    Option("anneal_temperature", "--anneal-temperature", "float", "退火温度（K）"),
    Option("no_cell_relax", "--no-cell-relax", "bool", "true 时只弛豫原子，不弛豫块体晶胞"),
)
_register(Method(
    name="amorphous_surfaces", title="非晶表面能筛选", summary="弛豫块体和多个非晶表面，按表面能排序",
    module="genkai.modeling.surface.screening.amorphous_screen", subcommand="surfaces",
    calculator_flag="--calculator", requires_mlip=True, fixed_expected=False,
    options=(
        Option("amorphous", "--amorphous", "path", "非晶块体文件", required=True, example="<非晶块体.vasp>"),
        Option("amorphous_format", "--amorphous-format", "str", "非晶块体格式"),
        Option("periods", "--periods", "int", "厚度包含的完整周期数"),
        Option("thickness", "--thickness", "float", "指定厚度（Å），与 periods 最多填一个"),
        Option("samples", "--samples", "int", "表面样本数"),
        Option("vacuum", "--vacuum", "float", "真空厚度（Å）"),
        Option("min_lateral_size", "--min-lateral-size", "float", "面内最小宽度（Å）"),
        Option("fix_bottom", "--fix-bottom", "bool", "true 为固定底层，默认两侧自由"),
        *RELAX_OPTIONS, *ANNEAL_OPTIONS, SEED, EXPORT,
    ),
    groups=(Group(("periods", "thickness"), "at_most_one", "厚度：periods 与 thickness 最多写一个"),),
    output_flag="--output-dir", outputs=("amorphous_surfaces_ranked.extxyz",),
))
_register(Method(
    name="amorphous_interface", title="非晶/晶体界面能搜索", summary="搜索非晶膜的平移和界面间距，按粘附能排序",
    module="genkai.modeling.surface.screening.amorphous_screen", subcommand="interface",
    calculator_flag="--search-calculator", requires_mlip=True,
    options=(
        *SUBSTRATE_OPTIONS,
        Option("amorphous", "--amorphous", "path", "非晶块体文件", required=True, example="<非晶块体.vasp>"),
        Option("amorphous_format", "--amorphous-format", "str", "非晶块体格式"),
        Option("thickness", "--thickness", "float", "膜厚（Å）"),
        Option("film_fit", "--film-fit", "str", "成膜方式 auto、strain 或 cut"),
        Option("n_matches", "--n-matches", "int", "晶格匹配候选数"),
        Option("n_rotations", "--n-rotations", "int", "旋转切割候选数"),
        Option("n_trials", "--n-trials", "int", "每个界面的搜索次数"),
        SAMPLER,
        Option("gap_min", "--gap-min", "float", "界面最小间距（Å）"),
        Option("gap_max", "--gap-max", "float", "界面最大间距（Å）"),
        Option("max_strain", "--max-strain", "float", "最大应变"),
        Option("max_area", "--max-area", "float", "最大面内面积（Å²）"),
        *RELAX_OPTIONS, SEARCH_STEPS, *ANNEAL_OPTIONS, SEED, EXPORT,
    ),
    groups=(SUBSTRATE_GROUP,), output_flag="--output-dir", outputs=("amorphous_interfaces_ranked.extxyz",),
    locked=("--calculator=none",),
))
_register(Method(
    name="cluster_search", title="团簇/非晶岛负载搜索", summary="为预制团簇或岛搜索负载位置并弛豫",
    module="genkai.modeling.surface.screening.cluster_search", calculator_flag="--calculator", requires_mlip=True, style="underscore",
    options=(
        Option("surface", "--surface", "path", "基底 slab", required=True, example="<slab.cif>"),
        Option("cluster", "--cluster", "path", "预制团簇或岛", required=True, example="<团簇.xyz>"),
        *(Option(key, "--" + key, kind, help) for key, kind, help in (
            ("n_trials", "int", "搜索次数"), ("max_steps", "int", "弛豫步数上限"),
            ("fmax", "float", "力收敛阈值（eV/Å）"), ("fixed_fraction", "float", "基底底部固定比例"),
            ("max_tilt", "float", "最大倾角（度）"), ("placement_shape", "str", "input 保留输入形状，relaxed 使用弛豫形状"),
            ("placement_mode", "str", "cell 或 active"), ("active_symbols", "words", "活性位点元素"),
            ("z_min", "float", "最小间距（Å）"), ("z_max", "float", "最大间距（Å）"),
            ("min_vacuum", "float", "最小真空（Å）"), ("selection_count", "int", "输出构型数"),
            ("top_pool_size", "int", "最低能候选池大小"), ("top_pick_count", "int", "最低能输出数"),
            ("tail_pick_per_bin", "int", "每个其余能量区间的输出数"), ("seed", "int", "随机种子"),
        ) if key != "active_symbols"),
        Option("active_symbols", "--active_symbols", "words", "活性位点元素", nargs=True),
        SAMPLER,
    ), output_flag="--output_dir", outputs=("mlip_output/[0-9]*_trial_*.cif",),
))

NOT_OPEN = (
    ("amorphous_screen", "非晶筛选", "请用 amorphous_surfaces 或 amorphous_interface"),
    ("Materials Project", "按化学式下载块体结构", "需要联网和 MP_API_KEY；请先下载 CIF 再用 bulk"),
)

ENERGY_KEYS = {
    "calculator", "search_calculator", "uma_model", "task_name", "device", "include_d3", "fmax",
    "max_steps", "relax_steps", "screen_steps", "checkpoint", "mu_o", "max_index", "smoke_test",
    "mace_model", "mace_dtype",
}
TASK_ENERGY_KEYS = {"fmax", "max_steps", "relax_steps", "screen_steps", "mu_o", "max_index", "anneal_steps", "anneal_temperature", "no_cell_relax"}
NETWORK_KEYS = {"formula", "material_id", "surface_formula", "surface_mp_id", "cluster_from_mp", "cluster_mp_id"}
RESERVED_KEYS = {"output_dir": "输出目录请用 output 指定"}


# ---------------------------------------------------------------------------
# Errors and parsed jobs
# ---------------------------------------------------------------------------


class JobFileError(ValueError):
    """A job file that cannot be run; ``problems`` holds one message per issue."""

    def __init__(self, source: Path, problems: list[str]):
        self.source = source
        self.problems = problems
        super().__init__(f"{source}: " + "; ".join(problems))


@dataclass
class Job:
    source: Path
    index: int | None
    method: Method
    values: dict[str, Any]
    raw: dict[str, Any]
    output: Path
    description: str | None = None
    profile: MlipProfile | None = None
    runtime_info: dict[str, Any] = field(default_factory=dict)

    @property
    def calculator(self) -> str:
        return self.profile.backend if self.profile else "none"

    @property
    def label(self) -> str:
        where = self.source.name if self.index is None else f"{self.source.name} 第 {self.index + 1} 个任务"
        return f"{where}（{self.method.name}）"

    def input_paths(self) -> list[tuple[str, Path]]:
        return [(key, value) for key, value in self.values.items() if self.method.option(key).kind == "path"]


@dataclass
class FileCheck:
    name: str
    frames: int
    atoms: str
    min_contact_ratio: float | None
    min_vacuum_A: float | None
    fixed: str


@dataclass
class JobResult:
    job: Job
    status: str  # PASS | WARN | FAIL | SKIP
    seconds: float = 0.0
    messages: list[str] = field(default_factory=list)
    files: list[FileCheck] = field(default_factory=list)
    manifest: Path | None = None
    cuda_oom: bool = False


# ---------------------------------------------------------------------------
# Reading and validating job files
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", locale.getpreferredencoding(False) or "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise JobFileError(path, ["文件编码无法识别，请另存为 UTF-8"])


def _load_documents(path: Path) -> list[tuple[int | None, Any]]:
    if not path.is_file():
        raise JobFileError(path, ["任务文件不存在"])
    try:
        data = yaml.load(_read_text(path), Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        hint = "；Windows 路径请改用正斜杠 /，或用单引号括起来" if "escape" in str(exc) else ""
        raise JobFileError(path, [f"YAML 格式错误：{exc}{hint}"]) from None
    if not isinstance(data, dict):
        raise JobFileError(path, ["任务文件需要写成“键: 值”的形式，至少包含 method"])
    if "pipeline" in data:
        raise JobFileError(path, [f"这是流水线文件；请用 `{PROG} check` 或 `{PROG} run`（会自动识别），不要按普通任务读取"])
    if "jobs" in data:
        extra = sorted(set(data) - {"jobs"})
        if extra:
            raise JobFileError(path, [f"使用 jobs 列表时，顶层只能有 jobs，多出了：{', '.join(extra)}"])
        jobs = data["jobs"]
        if not isinstance(jobs, list) or not jobs or not all(isinstance(item, dict) for item in jobs):
            raise JobFileError(path, ["jobs 需要是任务列表，每一项以 “- method: ...” 开头"])
        return list(enumerate(jobs))
    return [(None, data)]


def _unset(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in UNSET_STRINGS)


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if not _unset(item)]
    return [item for item in re.split(r"[,\s]+", str(value).strip()) if item]


def _convert(option: Option, value: Any, base: Path) -> Any:
    if isinstance(value, dict):
        raise ValueError("不能是嵌套的“键: 值”结构")
    if option.kind in {"path", "int", "float", "str"} and isinstance(value, list):
        raise ValueError("只能写一个值，不能是列表")
    text = value.strip() if isinstance(value, str) else value
    if option.kind == "path":
        path = Path(os.path.expanduser(text))
        return (path if path.is_absolute() else base / path).resolve()
    if option.kind == "int":
        try:
            return int(text)
        except ValueError:
            raise ValueError(f"需要整数，写的是 {text!r}") from None
    if option.kind == "float":
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"需要数字，写的是 {text!r}") from None
    if option.kind == "str":
        return text
    if option.kind == "bool":
        if text.lower() not in {"true", "false"}:
            raise ValueError("需要 true 或 false")
        return text.lower() == "true"
    if option.kind == "facet":
        if isinstance(value, list):
            try:
                return ",".join(str(int(item)) for item in value)
            except ValueError:
                raise ValueError("列表形式的晶面只能包含整数，如 [1, 1, 0]") from None
        if not re.fullmatch(r"[\s()\[\]{}0-9,\-]+", text):
            raise ValueError(f"晶面写法无法识别：{text!r}；请写成 \"110\"、\"1-10\" 或 [1, 1, 0]")
        return text
    if option.kind in {"ints", "floats"}:
        if option.allow_auto and isinstance(value, str) and text.lower() == "auto":
            return "auto"
        caster = int if option.kind == "ints" else float
        items = _items(value)
        try:
            numbers = [caster(item) for item in items]
        except ValueError:
            kind = "整数" if option.kind == "ints" else "数字"
            raise ValueError(f"需要{kind}列表，如 [1, 2]，写的是 {value!r}") from None
        if not numbers:
            raise ValueError("列表是空的")
        if option.length is not None and len(numbers) != option.length:
            raise ValueError(f"需要 {option.length} 个数，写了 {len(numbers)} 个")
        return numbers
    if option.kind == "words":
        words = _items(value)
        if not words:
            raise ValueError("列表是空的")
        return words
    raise AssertionError(f"unknown option kind {option.kind}")


def _blocked_reason(key: str) -> str | None:
    if key in ENERGY_KEYS:
        return f"{key} 需要启用 MLIP；计算器与模型参数请集中写入 genkai.yaml，任务里用 mlip: default 或配置名称选择。"
    if key in NETWORK_KEYS:
        return f"{key} 不能设置：这个界面目前不联网下载结构，请提供本地结构文件"
    if key in RESERVED_KEYS:
        return f"{key} 不能设置：{RESERVED_KEYS[key]}"
    return None


def _default_output(source: Path, index: int | None, method: str) -> Path:
    base = source.parent / "runs" / source.stem
    return (base if index is None else base / f"{index + 1:02d}_{method}").resolve()


def _parse_job(
    source: Path, index: int | None, mapping: dict[str, Any], config_path: Path | None = None,
) -> tuple[Job | None, list[str]]:
    problems: list[str] = []
    data = {str(key).strip().replace("-", "_"): value for key, value in mapping.items()}
    method_name = data.get("method")
    if _unset(method_name) or not isinstance(method_name, str):
        return None, [f"缺少 method；可用的方法：{', '.join(METHODS)}"]
    name = method_name.strip().lower().replace("-", "_")  # SAM, ALD and amorphous-slab are accepted
    method = METHODS.get(name)
    if method is None:
        not_open = {item for item, _, _ in NOT_OPEN}
        if name in not_open:
            return None, [f"方法 {method_name} 暂未开放（需要能量计算或联网）"]
        guess = difflib.get_close_matches(name, list(METHODS), n=1)
        hint = f"；是不是 {guess[0]}？" if guess else ""
        return None, [f"未知的方法 {method_name!r}{hint}（可用：{', '.join(METHODS)}）"]

    base = source.parent
    profile = None
    selection = data.get("mlip", "default" if method.requires_mlip else "none")
    if not isinstance(selection, str):
        problems.append("mlip 需要配置名称，例如 mace、uma、default 或 none。")
    elif selection.strip().lower() not in {"none", "null", "", "~"}:
        if method.calculator_flag is None:
            problems.append(f"{method.name} 是几何生成方法；请使用 sam_search、amorphous_surfaces、amorphous_interface 或 cluster_search 进行能量筛选。")
        else:
            explicit = config_path
            if explicit is None and not _unset(data.get("config")):
                if not isinstance(data["config"], str):
                    problems.append("config 必须是配置文件路径。")
                else:
                    explicit = (base / Path(os.path.expanduser(data["config"]))).absolute()
            try:
                profile = load_config(find_config(source, explicit)).select(selection.strip())
            except MlipConfigError as exc:
                problems.append(str(exc))
    elif method.requires_mlip:
        problems.append(f"{method.name} 需要 MLIP 配置；请填写 mlip: default 或已配置的名称。")
    values: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for key, value in data.items():
        if key in JOB_KEYS:
            continue
        blocked = None if key in method.keys and (key not in ENERGY_KEYS or profile is not None) else _blocked_reason(key)
        if blocked:
            problems.append(blocked)
            continue
        if key not in method.keys:
            guess = difflib.get_close_matches(key, list(method.keys) + list(JOB_KEYS), n=1)
            hint = f"，是不是 {guess[0]}？" if guess else f"；用 `{PROG} methods {method.name}` 查看全部参数"
            problems.append(f"{method.name} 没有参数 {key}{hint}")
            continue
        if _unset(value):
            continue
        try:
            values[key] = _convert(method.option(key), value, base)
            raw[key] = value
        except ValueError as exc:
            problems.append(f"{key}：{exc}")

    for option in method.options:
        if option.required and option.key not in values and not any(option.key in g.keys for g in method.groups):
            problems.append(f"缺少必填项 {option.key}（{option.help}）")
    for group in method.groups:
        given = [key for key in group.keys if key in values]
        if (group.mode == "one" and len(given) != 1) or (group.mode == "any" and not given) or (
            group.mode == "at_most_one" and len(given) > 1
        ):
            problems.append(group.help + (f"，现在写了 {', '.join(given)}" if given else "，现在一个也没写"))

    output_raw = data.get("output")
    if isinstance(output_raw, (list, dict)):
        problems.append("output 只能是一个目录路径")
        output_raw = None
    if _unset(output_raw):
        output = _default_output(source, index, method.name)
    else:
        output = Path(os.path.expanduser(str(output_raw).strip()))
        output = (output if output.is_absolute() else base / output).resolve()
    description = data.get("description")
    description = None if _unset(description) else str(description).strip()
    if problems:
        return None, problems
    if SAMPLER.key in method.keys and SAMPLER.key not in values:
        values[SAMPLER.key] = option_default(method, SAMPLER)
    job = Job(source, index, method, values, raw, output, description, profile)
    parser_problem = _parser_problem(job)
    if parser_problem:
        return None, [f"参数检查未通过：{parser_problem}"]
    return job, []


def load_job_file(path: str | Path, *, config_path: Path | None = None) -> list[Job]:
    """Parse and validate one job file (a single job or a ``jobs:`` list)."""
    source = Path(path).resolve()
    jobs: list[Job] = []
    problems: list[str] = []
    for index, mapping in _load_documents(source):
        job, issues = _parse_job(source, index, mapping, config_path)
        prefix = "" if index is None else f"第 {index + 1} 个任务："
        problems.extend(prefix + issue for issue in issues)
        if job is not None:
            jobs.append(job)
    outputs = [job.output for job in jobs]
    for output in {o for o in outputs if outputs.count(o) > 1}:
        problems.append(f"多个任务使用同一个输出目录 {output}")
    if problems:
        raise JobFileError(source, problems)
    return jobs


# ---------------------------------------------------------------------------
# Method parsers (single source of defaults and choices)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def method_parser(name: str) -> argparse.ArgumentParser:
    method = METHODS[name]
    parser = importlib.import_module(method.module)._build_parser()
    if method.subcommand:
        subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
        return subparsers.choices[method.subcommand]
    return parser


def _actions(name: str) -> dict[str, argparse.Action]:
    return dict(method_parser(name)._option_string_actions)


def _format(value: Any) -> str:
    return os.fspath(value) if isinstance(value, Path) else str(value)


def display_command(argv: list[str]) -> str:
    return " ".join(f'"{item}"' if " " in item else item for item in argv)


def _width(text: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _pad(text: str, width: int, right: bool = False) -> str:
    gap = " " * max(width - _width(text), 0)
    return gap + text if right else text + gap


def build_argv(job: Job) -> list[str]:
    """Method CLI arguments for a job, with the locked structure-only settings appended."""
    argv: list[str] = [job.method.subcommand] if job.method.subcommand else []
    for option in job.method.options:
        if option.key not in job.values:
            continue
        value = job.values[option.key]
        if option.kind == "bool":
            if value:
                argv.append(option.flag)
        elif isinstance(value, list) and option.nargs:
            argv += [option.flag, *(_format(item) for item in value)]
        elif isinstance(value, list):
            argv.append(f"{option.flag}={','.join(_format(item) for item in value)}")
        else:
            argv.append(f"{option.flag}={_format(value)}")
    locked = list(job.method.locked)
    if job.profile:
        # Leave --calculator=none intact when it controls only substrate preparation.
        replaced = {job.method.calculator_flag, "--max-steps", "--relax-steps"}
        locked = [value for value in locked if value.partition("=")[0] not in replaced]
        argv += job.profile.calculator_args(job.method.calculator_flag or "--calculator", job.method.style)
        for key, value in job.profile.settings.items():
            if key in job.method.keys and key not in job.values:
                argv.append(f"{job.method.option(key).flag}={value}")
    argv += locked
    argv.append(f"{job.method.output_flag}={_format(job.output)}")
    return argv


def _parser_problem(job: Job) -> str | None:
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(buffer):
            argv = build_argv(job)
            method_parser(job.method.name).parse_args(argv[1:] if job.method.subcommand else argv)
    except SystemExit as exc:
        if exc.code:
            lines = [line for line in buffer.getvalue().splitlines() if "error:" in line]
            return lines[-1].split("error:", 1)[1].strip() if lines else buffer.getvalue().strip()
    return None


# ---------------------------------------------------------------------------
# Templates and method descriptions
# ---------------------------------------------------------------------------


def _yaml_value(option: Option, value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Path):
        return value.as_posix()
    if option.kind == "bool":
        return str(value).lower()
    if option.kind in {"ints", "floats", "words"} and not (option.allow_auto and value == "auto"):
        items = _items(value) if isinstance(value, str) else [str(item) for item in value]
        return "[" + ", ".join(items) + "]"
    if option.kind == "facet":
        return f'"{value}"'
    return str(value)


def option_default(method: Method, option: Option) -> Any:
    action = _actions(method.name).get(option.flag)
    return None if action is None else action.default


def option_choices(method: Method, option: Option) -> list[str] | None:
    action = _actions(method.name).get(option.flag)
    return [str(choice) for choice in action.choices] if action is not None and action.choices else None


def _help_line(method: Method, option: Option) -> str:
    choices = option_choices(method, option)
    text = option.help
    if choices and not all(choice in text for choice in choices):
        text += f"（可选：{' | '.join(choices)}）"
    return text


def render_template(name: str) -> str:
    """A commented job file: required keys filled with placeholders, optional keys commented out."""
    method = METHODS[name]
    grouped = {key for group in method.groups for key in group.keys}
    lines = [
        f"# Genkai 表面建模任务文件：{method.title}",
        f"# {method.summary}",
        "#",
        f"# 检查：{PROG} check 本文件      运行：{PROG} run 本文件",
        "# 规则：相对路径以本文件所在目录为准；Windows 路径用正斜杠 /（或单引号括起来）；",
        "#       晶面写成带引号的字符串（\"110\"）或列表（[1, 1, 0]）；去掉行首的 # 让该行生效。",
        "# mlip 选择 genkai.yaml 中的环境和模型；none 只生成结构。",
        "",
        f"method: {method.name}",
        f"mlip: {'default' if method.requires_mlip else 'none'}  # 改为 mace、uma 或配置中的名称即可接入 MLIP",
        f"output: runs/{method.name}          # 输出目录（相对本文件）；目录必须是空的，除非 run 时加 --overwrite",
        "# description: 备注，会记进 manifest.json",
        "",
        "# ---- 必填 ----",
    ]

    def entry(option: Option, value: str, active: bool) -> str:
        body = f"{option.key}: {value}".rstrip()
        prefix = "" if active else "# "
        return f"{prefix}{body:<30s} # {_help_line(method, option)}"

    for option in method.options:
        if option.required and option.key not in grouped:
            lines.append(entry(option, option.example or "", True))
    for group in method.groups:
        if group.mode == "at_most_one":
            continue
        lines.append(f"# {group.help}")
        for position, key in enumerate(group.keys):
            option = method.option(key)
            lines.append(entry(option, option.example or "", position == 0))
    for option in method.options:
        if option.suggested:
            lines.append(entry(option, option.example or "", True))
    lines += ["", "# ---- 可选（弛豫默认读取 genkai.yaml；显式填写以下参数可覆盖）----"]
    for group in method.groups:
        if group.mode == "at_most_one":
            lines.append(f"# {group.help}")
            for key in group.keys:
                option = method.option(key)
                lines.append(entry(option, _yaml_value(option, option_default(method, option)), False))
    for option in method.options:
        if option.required or option.suggested or option.key in grouped:
            continue
        default = option_default(method, option)
        value = _yaml_value(option, default) if default is not None else (option.example or "")
        lines.append(entry(option, value, False))
    return "\n".join(lines) + "\n"


def describe_methods(stream: TextIO = sys.stdout) -> None:
    print("可用的建模方法（结构生成 / 配置化 MLIP 筛选）：\n", file=stream)
    for method in METHODS.values():
        required = [o.key for o in method.options if o.required] + [
            "/".join(g.keys) for g in method.groups if g.mode in {"one", "any"}
        ]
        print(f"  {method.name:<21s} {method.title}" + (" [需要 MLIP 配置]" if method.requires_mlip else ""), file=stream)
        print(f"  {'':<15s} {method.summary}", file=stream)
        print(f"  {'':<15s} 必填：{', '.join(required)}", file=stream)
    print("\n暂未开放：", file=stream)
    for name, text, reason in NOT_OPEN:
        print(f"  {name:<17s} {text}（{reason}）", file=stream)
    print(f"\n查看某个方法的全部参数：{PROG} methods <方法名>", file=stream)
    print(f"生成任务文件模板：      {PROG} template <方法名> -o job.yaml", file=stream)


def describe_method(name: str, stream: TextIO = sys.stdout) -> None:
    method = METHODS[name]
    print(f"{method.name}：{method.title}\n{method.summary}\n", file=stream)
    if method.calculator_flag:
        print("  mlip                 genkai.yaml 中的配置名称；default 使用默认配置。\n", file=stream)
    grouped = {key: group for group in method.groups for key in group.keys}
    for option in method.options:
        if option.required:
            status = "必填"
        elif option.key in grouped and grouped[option.key].mode in {"one", "any"}:
            status = "见下方组合规则"
        else:
            default = option_default(method, option)
            status = f"默认 {_yaml_value(option, default)}" if default is not None else "默认不设置"
        print(f"  {option.key:<20s} {_help_line(method, option)}  [{status}]", file=stream)
    if method.groups:
        print("\n组合规则：", file=stream)
        for group in method.groups:
            print(f"  - {group.help}", file=stream)
    print("\n未启用 MLIP 时的固定设置（启用后自动切换）：" + (" ".join(method.locked) if method.locked else "无"), file=stream)
    print("主要输出：" + ", ".join(method.outputs), file=stream)
    for note in method.notes:
        print(f"注意：{note}", file=stream)


# ---------------------------------------------------------------------------
# Running jobs
# ---------------------------------------------------------------------------


def _package_root() -> Path:
    import genkai

    return Path(genkai.__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version

    info = {"python": sys.version.split()[0], "platform": platform.platform()}
    for package in ("genkai", "ase", "pymatgen", "numpy"):
        try:
            info[package] = version(package)
        except PackageNotFoundError:
            info[package] = "source checkout" if package == "genkai" else "not installed"
    return info


def _directory_has_content(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def _check_outputs(job: Job, since: float = 0.0) -> tuple[str, list[str], list[FileCheck], list[dict[str, Any]]]:
    """Check the structure files this run wrote (files older than ``since`` are left out)."""
    from genkai.modeling.surface.structure_io import CLASH_RATIO, MIN_VACUUM_A, frame_metrics, read_frames

    found = sorted({f for pattern in job.method.outputs for f in job.output.glob(pattern) if f.is_file()})
    files = [f for f in found if f.stat().st_mtime >= since - 1.0]
    stale = len(found) - len(files)
    if not files:
        return "FAIL", [f"没有找到本次生成的结构文件（{', '.join(job.method.outputs)}）"], [], []
    status = "PASS"
    messages: list[str] = []
    checks: list[FileCheck] = []
    records: list[dict[str, Any]] = []
    if stale:
        messages.append(f"输出目录里还有 {stale} 个以前留下的结构文件，本次没有更新，未计入检查和 manifest.json")
    for file in files:
        relative = file.relative_to(job.output).as_posix()
        try:
            frames = read_frames(file)
        except Exception as exc:
            return "FAIL", [f"{relative} 无法读取：{exc}"], checks, records
        metrics = [frame_metrics(frame) for frame in frames]
        if not frames or any(m["n_atoms"] == 0 for m in metrics):
            return "FAIL", [f"{relative} 含有空结构"], checks, records
        ratios = [m["min_contact_ratio"] for m in metrics if "min_contact_ratio" in m]
        gaps = [m["vacuum_gap_A"] for m in metrics if "vacuum_gap_A" in m]
        counts = sorted({m["n_atoms"] for m in metrics})
        keeps_constraints = file.suffix == ".extxyz"
        fixed = [m["n_fixed"] for m in metrics]
        fixed_text = ("有" if all(fixed) else "缺失") if keeps_constraints else "CIF 不保存"
        check = FileCheck(
            name=relative,
            frames=len(frames),
            atoms=str(counts[0]) if len(counts) == 1 else f"{counts[0]}-{counts[-1]}",
            min_contact_ratio=min(ratios) if ratios else None,
            min_vacuum_A=min(gaps) if gaps else None,
            fixed=fixed_text,
        )
        checks.append(check)
        if check.min_contact_ratio is not None and check.min_contact_ratio < CLASH_RATIO:
            status = "WARN"
            messages.append(f"{relative}：有原子过近（最小接触比 {check.min_contact_ratio} < {CLASH_RATIO}）")
        if job.method.vacuum_expected and check.min_vacuum_A is not None and check.min_vacuum_A < MIN_VACUUM_A:
            status = "WARN"
            messages.append(f"{relative}：真空层只有 {check.min_vacuum_A} Å（< {MIN_VACUUM_A} Å）")
        if keeps_constraints and (job.method.fixed_expected or job.values.get("fix_bottom", False)) and not all(fixed):
            status = "WARN"
            messages.append(f"{relative}：有结构没有固定原子")
        records.append({"path": relative, "frames": metrics, "file": file})
    return status, messages, checks, records


def _write_resolved_job(job: Job) -> Path:
    data: dict[str, Any] = {"method": job.method.name}
    if job.profile:
        data["mlip"] = job.profile.name
        data["config"] = str(job.profile.config_path)
    if job.description:
        data["description"] = job.description
    data["output"] = job.output.as_posix()
    for key, value in job.values.items():
        data[key] = value.as_posix() if isinstance(value, Path) else value
    header = (
        f"# {PROG} 实际运行的任务（来源：{job.source.as_posix()}；路径已展开为绝对路径）\n"
        f"# 固定设置：{' '.join(a for a in build_argv(job) if a in job.method.locked) or '无'}\n"
    )
    target = job.output / "job_resolved.yaml"
    target.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target


def _write_manifest(
    job: Job,
    result: JobResult,
    *,
    command: list[str],
    exit_code: int | None,
    started_at: datetime,
    records: list[dict[str, Any]],
    oom_fallback: dict[str, str] | None = None,
) -> Path:
    from genkai.contracts.artifacts import EvidenceLevel, ExecutionState, StructureSetArtifact, ValidationStatus
    from genkai.contracts.provenance import Provenance
    from genkai.contracts.run import RunManifest, StageRecord
    from genkai.contracts.validation import ValidationIssue, ValidationReport
    from genkai.modeling.surface.structure_io import json_ready, sha256_of
    from genkai.workflow.store import save_manifest

    run_id = f"{job.method.name}-{started_at.strftime('%Y%m%dT%H%M%SZ')}"
    producer = f"{PROG}:{job.method.name}"
    environment = _environment()
    if job.profile:
        environment.update({f"mlip_{key}": str(value) for key, value in job.runtime_info.items() if isinstance(value, (str, int, float))})
    parameters = json_ready(job.values)
    inputs = [
        {"key": key, "path": path.as_posix(), "sha256": sha256_of(path) if path.is_file() else None}
        for key, path in job.input_paths()
    ]
    ok = result.status in {"PASS", "WARN"}
    calculating = job.profile is not None
    mode = "energy-screening" if calculating else "structure-only"
    note = f"使用配置 {job.profile.name}（{job.calculator}）的能量筛选；结果适用性需另行验证。" if calculating else STRUCTURE_ONLY_NOTE
    from ..mlip.calculators import evidence_for

    evidence = EvidenceLevel(evidence_for(job.calculator)) if calculating else EvidenceLevel.HEURISTIC
    manifest = RunManifest(run_id=run_id, metadata=json_ready({
        "tool": PROG,
        "method": job.method.name,
        "job_file": job.source.as_posix(),
        "description": job.description,
        "mode": mode,
        "calculator": job.calculator,
        "energies_available": calculating and ok,
        "mlip": job.profile.public_settings() if job.profile else None,
        **({"oom_fallback": oom_fallback} if oom_fallback else {}),
        "runtime": job.runtime_info,
        "note": note,
    }))
    artifact_ids: list[str] = []
    if ok:
        for number, record in enumerate(records):
            path = record["file"]
            artifact = StructureSetArtifact(
                artifact_id=f"{run_id}:structure-set:{number:02d}",
                path=record["path"],
                sha256=sha256_of(path),
                producer=producer,
                execution_state=ExecutionState.SUCCEEDED,
                evidence_level=evidence,
                validation_status=ValidationStatus.PASSED if result.status == "PASS" else ValidationStatus.NEEDS_REVIEW,
                metadata=json_ready({
                    "mode": mode,
                    "calculator": job.calculator,
                    "energies_available": calculating,
                    "frame_count": len(record["frames"]),
                    "frames": record["frames"],
                }),
                provenance=Provenance(
                    source=job.source.as_posix(),
                    software=producer,
                    software_version=environment.get("genkai"),
                    parameters=parameters,
                    environment=environment,
                ),
            )
            manifest.register_artifact(artifact)
            artifact_ids.append(artifact.artifact_id)
    issues = [ValidationIssue(code="structure_check", message=message) for message in result.messages]
    manifest.append_stage(StageRecord(
        stage_id=job.method.name,
        adapter=producer,
        execution_state=ExecutionState.SUCCEEDED if ok else ExecutionState.FAILED,
        output_artifact_ids=artifact_ids,
        validation=ValidationReport(
            errors=[] if ok else issues,
            warnings=issues if result.status == "WARN" else [],
        ),
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        metadata=json_ready({
            "command": command,
            "exit_code": exit_code,
            "seconds": result.seconds,
            "inputs": inputs,
            "parameters": parameters,
            "locked": [a for a in build_argv(job) if a in job.method.locked],
            "log": "run.log",
            "resolved_job": "job_resolved.yaml",
            "status": result.status,
            "notes": [] if calculating else list(job.method.notes),
        }),
    ))
    return save_manifest(job.output, manifest)


def run_job(job: Job, *, overwrite: bool = False, quiet: bool = False, stream: TextIO = sys.stdout) -> JobResult:
    """Run one job; restart it once with the configured UMA profile after a CUDA OOM."""
    result = _run_job(job, overwrite=overwrite, quiet=quiet, stream=stream)
    profile = job.profile
    if not result.cuda_oom or profile is None or profile.oom_fallback is None:
        return result
    try:
        fallback = load_config(profile.config_path).select(profile.oom_fallback)
        probe_profile(fallback, _package_root())
        archive = Path(tempfile.mkdtemp(prefix=f"{job.output.name}.cuda-oom-", dir=job.output.parent)) / "output"
        job.output.rename(archive)
    except (OSError, MlipConfigError) as exc:
        result.messages.append(f"无法准备 CUDA OOM 回退：{exc}")
        return result

    values = {**job.values}
    for key, path in job.input_paths():
        if path.is_relative_to(job.output):
            values[key] = archive / path.relative_to(job.output)
    recovery = {"requested_model": str(profile.checkpoint or profile.model),
                "requested_profile": profile.name, "first_log": str(archive / "run.log")}
    print(f"    CUDA 显存不足，使用 {fallback.name} ({fallback.checkpoint or fallback.model}) 从原始输入重新运行。"
          f"首次日志：{recovery['first_log']}", file=stream, flush=True)
    rerun = replace(job, profile=fallback, values=values, runtime_info={})
    return _run_job(rerun, overwrite=False, quiet=quiet, stream=stream, oom_fallback=recovery)


def _run_job(job: Job, *, overwrite: bool, quiet: bool, stream: TextIO,
             oom_fallback: dict[str, str] | None = None) -> JobResult:
    missing = [f"{key}: {path}" for key, path in job.input_paths() if not path.is_file()]
    if missing:
        return JobResult(job, "FAIL", messages=["输入文件不存在：" + "；".join(missing)])
    if job.profile:
        try:
            job.runtime_info = probe_profile(job.profile, _package_root())
        except MlipConfigError as exc:
            return JobResult(job, "FAIL", messages=[str(exc)])
    if _directory_has_content(job.output) and not overwrite:
        return JobResult(job, "FAIL", messages=[
            f"输出目录 {job.output} 已有内容；请换一个 output，删除该目录，或在 run 时加 --overwrite（旧文件不会被删除）"
        ])
    job.output.mkdir(parents=True, exist_ok=True)
    _write_resolved_job(job)
    argv = build_argv(job)
    command = [
        *(job.profile.command() if job.profile else [sys.executable]), "-c",
        "import importlib, sys; sys.exit(importlib.import_module(sys.argv[1]).main(sys.argv[2:]))",
        job.method.module, *argv,
    ]
    env = job.profile.environment(_package_root()) if job.profile else dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(_package_root()), env.get("PYTHONPATH")]))
    env.update({"MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    started_wall = time.time()
    lines: list[str] = []
    exit_code: int | None = None
    with (job.output / "run.log").open("w", encoding="utf-8") as log:
        log.write(f"$ {display_command(command)}\n")
        process = subprocess.Popen(
            command, cwd=job.output, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                log.write(line)
                lines.append(line.rstrip())
                if not quiet:
                    print(f"    | {line.rstrip()}", file=stream, flush=True)
            exit_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            result = JobResult(job, "FAIL", round(time.perf_counter() - started, 1), ["被用户中断"])
            result.manifest = _write_manifest(job, result, command=command, exit_code=None, started_at=started_at,
                                              records=[], oom_fallback=oom_fallback)
            raise
        log.write(f"[exit {exit_code}]\n")
    seconds = round(time.perf_counter() - started, 1)
    if exit_code != 0:
        tail = [line for line in lines if line.strip()][-4:]
        result = JobResult(job, "FAIL", seconds, [f"方法运行失败（退出码 {exit_code}），最后几行输出：", *tail])
        result.cuda_oom = any(re.search(r"\bCUDA (?:error: )?out of memory\b", line, re.IGNORECASE) for line in lines)
        result.manifest = _write_manifest(job, result, command=command, exit_code=exit_code, started_at=started_at,
                                          records=[], oom_fallback=oom_fallback)
        return result
    status, messages, checks, records = _check_outputs(job, since=started_wall)
    result = JobResult(job, status, seconds, messages, checks)
    result.manifest = _write_manifest(
        job, result, command=command, exit_code=exit_code, started_at=started_at, records=records if status != "FAIL" else [],
        oom_fallback=oom_fallback,
    )
    return result


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


def _print_problems(error: JobFileError, stream: TextIO) -> None:
    print(f"[任务文件有问题] {error.source}", file=stream)
    for problem in error.problems:
        print(f"  - {problem}", file=stream)


def expand_paths(paths: Iterable[Path]) -> list[Path]:
    """Expand ``*.yaml`` patterns ourselves: Windows shells pass them through unexpanded."""
    import glob

    expanded: list[Path] = []
    for path in paths:
        text = str(path)
        matches = sorted(glob.glob(text)) if any(char in text for char in "*?[") and not path.exists() else []
        if matches:
            expanded.extend(Path(match) for match in matches)
        else:
            expanded.append(path)
    return expanded


def _load_all(paths: Iterable[Path], stream: TextIO, config_path: Path | None = None) -> list[Job] | None:
    jobs: list[Job] = []
    failed = False
    for path in expand_paths(paths):
        try:
            jobs.extend(load_job_file(path, config_path=config_path))
        except JobFileError as error:
            _print_problems(error, stream)
            failed = True
    return None if failed else jobs


def _print_result(result: JobResult, stream: TextIO) -> None:
    print(f"    结果：{result.status}，用时 {result.seconds} s", file=stream)
    if result.files:
        name_width = max(12, *(_width(check.name) for check in result.files)) + 2
        header = [("结构文件", name_width, False), ("帧数", 6, True), ("原子数", 12, True),
                  ("最小接触比", 12, True), ("真空/Å", 9, True), ("  固定原子", 12, False)]
        print("    " + "".join(_pad(text, width, right) for text, width, right in header).rstrip(), file=stream)
        for check in result.files:
            ratio = "-" if check.min_contact_ratio is None else f"{check.min_contact_ratio:.3f}"
            vacuum = "-" if check.min_vacuum_A is None else f"{check.min_vacuum_A:.1f}"
            cells = [(check.name, name_width, False), (str(check.frames), 6, True), (check.atoms, 12, True),
                     (ratio, 12, True), (vacuum, 9, True), ("  " + check.fixed, 12, False)]
            print("    " + "".join(_pad(text, width, right) for text, width, right in cells).rstrip(), file=stream)
    for message in result.messages:
        print(f"    ! {message}", file=stream)
    if result.status in {"PASS", "WARN"}:
        note = f"使用 MLIP 配置 {result.job.profile.name}（{result.job.calculator}）。" if result.job.profile else STRUCTURE_ONLY_NOTE
        print(f"    说明：{note}", file=stream)
        for note in (() if result.job.profile else result.job.method.notes):
            print(f"    说明：{note}", file=stream)
    if result.manifest is not None:
        print(f"    记录：{result.manifest}（运行输出见同目录 run.log）", file=stream)


def _split_pipelines(paths: Iterable[Path]) -> tuple[list[Path], list[Path]]:
    """(job files, pipeline files): a file whose top level has ``pipeline`` is a pipeline."""
    from .pipeline import is_pipeline_file

    expanded = expand_paths(paths)
    pipelines = [path for path in expanded if is_pipeline_file(path)]
    return [path for path in expanded if path not in pipelines], pipelines


def command_check(paths: list[Path], stream: TextIO, *, config_path: Path | None = None) -> int:
    job_paths, pipeline_paths = _split_pipelines(paths)
    code = 0
    if pipeline_paths:
        from . import pipeline

        loaded = pipeline.load_all(pipeline_paths, stream, config_path)
        code = 2 if loaded is None else max((pipeline.check_pipeline(p, stream) for p in loaded), default=0)
        if not job_paths:
            return code
    return max(code, _check_jobs(job_paths, stream, config_path=config_path))


def _check_jobs(paths: list[Path], stream: TextIO, *, config_path: Path | None = None) -> int:
    jobs = _load_all(paths, stream, config_path)
    if jobs is None:
        return 2
    planned: list[Path] = []
    missing = 0
    checked_profiles: dict[tuple[Path, str], str | None] = {}
    for job in jobs:
        absent = []
        if job.profile:
            key = (job.profile.config_path, job.profile.name)
            if key not in checked_profiles:
                try:
                    probe_profile(job.profile, _package_root())
                    checked_profiles[key] = None
                except MlipConfigError as exc:
                    checked_profiles[key] = str(exc)
            if checked_profiles[key]:
                absent.append(f"    ! {checked_profiles[key]}")
                missing += 1
        for key, path in job.input_paths():
            if path.is_file():
                continue
            producer = next((o for o in planned if o == path or o in path.parents), None)
            if producer is not None:
                absent.append(f"    {key}：{path} 现在还不存在，会由前面的任务在 {producer} 生成")
            else:
                absent.append(f"    ! {key}：文件不存在 {path}")
                missing += 1
        state = "通过" if not any(line.startswith("    !") for line in absent) else "缺少输入文件"
        print(f"[{state}] {job.label} -> {job.output}", file=stream)
        for line in absent:
            print(line, file=stream)
        if _directory_has_content(job.output):
            print("    注意：输出目录已有内容，运行时需要加 --overwrite 或换一个 output", file=stream)
        print(f"    将运行：{job.method.module} {display_command(build_argv(job))}", file=stream)
        planned.append(job.output)
    if missing:
        print(f"共 {len(jobs)} 个任务，{missing} 个输入文件不存在。", file=stream)
        return 2
    print(f"共 {len(jobs)} 个任务，检查通过。", file=stream)
    return 0


def command_run(paths: list[Path], *, overwrite: bool, quiet: bool, stream: TextIO, config_path: Path | None = None) -> int:
    job_paths, pipeline_paths = _split_pipelines(paths)
    code = 0
    if pipeline_paths:
        from . import pipeline

        loaded = pipeline.load_all(pipeline_paths, stream, config_path)
        if loaded is None:
            print("没有运行任何流水线。请先修改流水线文件（可用 check 命令检查）。", file=stream)
            code = 2
        else:
            code = max((pipeline.run_pipeline(p, overwrite=overwrite, quiet=quiet, stream=stream) for p in loaded),
                       default=0)
        if not job_paths:
            return code
    return max(code, _run_jobs(job_paths, overwrite=overwrite, quiet=quiet, stream=stream, config_path=config_path))


def _run_jobs(paths: list[Path], *, overwrite: bool, quiet: bool, stream: TextIO, config_path: Path | None = None) -> int:
    jobs = _load_all(paths, stream, config_path)
    if jobs is None:
        print("没有运行任何任务。请先修改任务文件（可用 check 命令检查）。", file=stream)
        return 2
    results: list[JobResult] = []
    failed_sources: set[Path] = set()
    for number, job in enumerate(jobs, 1):
        print(f"\n== [{number}/{len(jobs)}] {job.label}：{job.method.title}", file=stream)
        print(f"    输出目录：{job.output}", file=stream)
        if job.source in failed_sources:
            result = JobResult(job, "SKIP", messages=["同一任务文件里前面的任务失败，跳过"])
        else:
            result = run_job(job, overwrite=overwrite, quiet=quiet, stream=stream)
        if result.status == "FAIL":
            failed_sources.add(job.source)
        _print_result(result, stream)
        results.append(result)
    counts = {status: sum(r.status == status for r in results) for status in ("PASS", "WARN", "FAIL", "SKIP")}
    print("\n== 汇总", file=stream)
    for result in results:
        print(f"    {result.status:<5s} {result.job.label}  {result.job.output}", file=stream)
    print(f"PASS {counts['PASS']}  WARN {counts['WARN']}  FAIL {counts['FAIL']}  SKIP {counts['SKIP']}", file=stream)
    return 1 if counts["FAIL"] or counts["SKIP"] else 0


EPILOG = f"""\
示例：
  {PROG} methods                       列出可用的建模方法
  {PROG} methods sam                   查看 SAM 的全部参数
  {PROG} template sam -o sam_job.yaml  生成 SAM 任务文件模板，修改后：
  {PROG} check sam_job.yaml            只检查，不运行
  {PROG} run sam_job.yaml              运行；结果在任务文件里写的 output 目录

原有任务不设置 mlip 时只生成结构；能量筛选通过 genkai.yaml 选择已经安装的 MLIP。
"""


def build_parser() -> argparse.ArgumentParser:
    from .setup import add_setup_arguments

    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Genkai 表面建模：用 YAML 任务文件生成结构或调用已配置的 MLIP 筛选。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")
    setup = commands.add_parser("setup", help="连接已有 MLIP，准备配置与任务文件（不安装 MLIP）")
    add_setup_arguments(setup)
    doctor = commands.add_parser("doctor", help="检查已配置的 MLIP 环境和模型路径，不加载模型")
    doctor.add_argument("--config", type=Path)
    methods = commands.add_parser("methods", help="列出可用的建模方法；加方法名查看该方法的全部参数")
    methods.add_argument("name", nargs="?", choices=list(METHODS), help="方法名")
    template = commands.add_parser("template", help="生成某个方法的任务文件模板")
    template.add_argument("method", choices=list(METHODS), help="方法名")
    template.add_argument("-o", "--output", type=Path, default=None, help="写入这个文件（不写则打印到屏幕）")
    template.add_argument("--force", action="store_true", help="文件已存在时覆盖")
    check = commands.add_parser("check", help="只检查任务文件，不运行")
    check.add_argument("job_files", nargs="+", type=Path, metavar="任务文件")
    check.add_argument("--config", type=Path, help="MLIP 配置文件（默认自动查找 genkai.yaml）")
    run = commands.add_parser("run", help="运行任务文件（可以一次给多个）")
    run.add_argument("job_files", nargs="+", type=Path, metavar="任务文件")
    run.add_argument("--config", type=Path, help="MLIP 配置文件（默认自动查找 genkai.yaml）")
    run.add_argument("--overwrite", action="store_true", help="允许写入已有内容的输出目录（旧文件不会被删除）")
    run.add_argument("--quiet", action="store_true", help="不显示方法本身的运行输出（仍写入 run.log）")
    return parser


def main(argv: list[str] | None = None) -> int:
    for handle in (sys.stdout, sys.stderr):  # never crash on a console that cannot show Chinese
        reconfigure = getattr(handle, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError):
                reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    stream = sys.stdout
    if args.command == "setup":
        from .setup import run_setup

        return run_setup(args)
    if args.command == "doctor":
        try:
            config = load_config(find_config(Path.cwd() / "job.yaml", args.config))
            if not config.profiles:
                print("没有启用 MLIP；请编辑 genkai.yaml 或运行 ./install.sh --configure-only。", file=stream)
                return 2
            for profile in config.profiles.values():
                probe_profile(profile, _package_root())
                print(f"[通过] {profile.name}：{profile.backend}，{profile.device}（未加载模型）", file=stream)
            return 0
        except MlipConfigError as exc:
            print(f"检查未通过：{exc}", file=stream)
            return 2
    if args.command == "methods":
        if args.name:
            describe_method(args.name, stream)
        else:
            describe_methods(stream)
        return 0
    if args.command == "template":
        text = render_template(args.method)
        if args.output is None:
            stream.write(text)
            return 0
        if args.output.exists() and not args.force:
            print(f"{args.output} 已存在；加 --force 覆盖，或换一个文件名。", file=stream)
            return 1
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"已写入 {args.output}。修改必填项后运行：{PROG} check {args.output}", file=stream)
        return 0
    if args.command == "check":
        return command_check(args.job_files, stream, config_path=args.config)
    try:
        return command_run(args.job_files, overwrite=args.overwrite, quiet=args.quiet, stream=stream, config_path=args.config)
    except KeyboardInterrupt:
        print(file=stream)
        print("已中断；当前任务的输出目录里保留了 run.log 和 manifest.json。", file=stream)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
