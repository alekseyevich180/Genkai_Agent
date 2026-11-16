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

Only structure generation is open. Energy models (UMA/EMT), Materials Project
downloads and the energy-screening methods (``sam_search``, ``amorphous_screen``,
``cluster_search``) cannot be reached from a job file yet; keys that would
enable them are rejected with an explanation.

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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, TextIO

import yaml

PROG = "genkai-surface"
STRUCTURE_ONLY_NOTE = "只生成未弛豫的结构，没有计算能量（calculator 固定为 none）。"
UNSET_STRINGS = {"", "null", "Null", "NULL", "~"}
JOB_KEYS = ("method", "output", "description")


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

    def option(self, key: str) -> Option:
        return next(option for option in self.options if option.key == key)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(option.key for option in self.options)


FIXED_FRACTION = Option("fixed_fraction", "--fixed-fraction", "float", "固定 slab 下部这一比例厚度内的原子；0 表示不固定")
SEED = Option("seed", "--seed", "int", "随机数种子；相同种子得到相同结构")
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
    module="genkai.modeling.surface.slab",
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
))

_register(Method(
    name="vacancy",
    title="氧空位",
    summary="在含氧 slab 的表面去掉 O 原子，生成不同空位数的结构",
    module="genkai.modeling.surface.vacancy",
    options=(
        Option("input", "--input", "path", "含氧化物的 slab 文件（只处理 O 空位）", required=True, example="<slab.cif>"),
        Option("vacancy_counts", "--vacancy-counts", "ints", "空位数，如 [1, 2]，每个数生成一组结构"),
        Option("samples_per_count", "--samples-per-count", "int", "每个空位数抽取的构型数"),
        Option("z_frac_min", "--z-frac-min", "float", "可选 O 位点的最小分数坐标 z（0–1，按整个晶胞高度）"),
        Option("z_frac_max", "--z-frac-max", "float", "可选 O 位点的最大分数坐标 z（0–1，按整个晶胞高度）"),
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
))

_register(Method(
    name="adsorbate",
    title="分子吸附",
    summary="把气体或有机分子放到 slab 表面位点上，生成不同覆盖度的结构",
    module="genkai.modeling.surface.adsorbate",
    options=(
        Option("surface", "--surface", "path", "slab 文件", required=True, example="<slab.cif>"),
        Option("molecule", "--molecule", "path", "分子文件（XYZ、CIF、POSCAR 等）", required=True, example="<分子.xyz>"),
        Option("site_symbols", "--site-symbols", "words", "吸附位点的表面元素，如 Ce；多个元素写成列表", required=True, example="Ce"),
        Option("coverage_counts", "--coverage-counts", "ints", "每个晶胞的分子数，如 [1, 2]；不写则从 1 到最多能放下的数"),
        Option("patterns", "--patterns", "words", "多分子排布方式：uniform、clustered、stripe、island、random"),
        Option("random_repeats", "--random-repeats", "int", "random 排布重复几次"),
        Option("n_trials_single", "--n-trials-single", "int", "单个分子位置的采样次数（只影响候选几何）"),
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
))

_register(Method(
    name="cluster",
    title="金属团簇负载",
    summary="构建 fcc/hcp/bcc 金属团簇并放到 slab 表面（几何放置，不优化）",
    module="genkai.modeling.surface.metal_cluster.surface_cluster_builder",
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
    module="genkai.modeling.surface.sam",
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
    module="genkai.modeling.surface.amorphous_overlayer",
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
    module="genkai.modeling.surface.amorphous_slab",
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

NOT_OPEN = (
    ("sam_search", "SAM 锚定参数与覆盖度的能量搜索", "需要 UMA，等服务器基准测试后开放"),
    ("amorphous_screen", "非晶表面能排序、非晶/晶体界面粘附能搜索", "需要 UMA，等服务器基准测试后开放"),
    ("cluster_search", "团簇或非晶岛的 Optuna 负载位置搜索", "需要 UMA，等服务器基准测试后开放"),
    ("Materials Project", "按化学式下载块体结构", "需要联网和 MP_API_KEY；请先下载 CIF 再用 bulk"),
)

ENERGY_KEYS = {
    "calculator", "search_calculator", "uma_model", "task_name", "device", "include_d3", "fmax",
    "max_steps", "relax_steps", "screen_steps", "checkpoint", "mu_o", "max_index", "smoke_test",
}
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
        return f"{key} 不能设置：这个界面目前只开放结构生成，计算器固定为 none（不算能量）"
    if key in NETWORK_KEYS:
        return f"{key} 不能设置：这个界面目前不联网下载结构，请提供本地结构文件"
    if key in RESERVED_KEYS:
        return f"{key} 不能设置：{RESERVED_KEYS[key]}"
    return None


def _default_output(source: Path, index: int | None, method: str) -> Path:
    base = source.parent / "runs" / source.stem
    return (base if index is None else base / f"{index + 1:02d}_{method}").resolve()


def _parse_job(source: Path, index: int | None, mapping: dict[str, Any]) -> tuple[Job | None, list[str]]:
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
    values: dict[str, Any] = {}
    raw: dict[str, Any] = {}
    for key, value in data.items():
        if key in JOB_KEYS:
            continue
        blocked = _blocked_reason(key)
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
    job = Job(source, index, method, values, raw, output, description)
    parser_problem = _parser_problem(job)
    if parser_problem:
        return None, [f"参数检查未通过：{parser_problem}"]
    return job, []


def load_job_file(path: str | Path) -> list[Job]:
    """Parse and validate one job file (a single job or a ``jobs:`` list)."""
    source = Path(path).resolve()
    jobs: list[Job] = []
    problems: list[str] = []
    for index, mapping in _load_documents(source):
        job, issues = _parse_job(source, index, mapping)
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
    module = importlib.import_module(METHODS[name].module)
    return module._build_parser()


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
    argv: list[str] = []
    for option in job.method.options:
        if option.key not in job.values:
            continue
        value = job.values[option.key]
        if isinstance(value, list) and option.nargs:
            argv += [option.flag, *(_format(item) for item in value)]
        elif isinstance(value, list):
            argv.append(f"{option.flag}={','.join(_format(item) for item in value)}")
        else:
            argv.append(f"{option.flag}={_format(value)}")
    argv += list(job.method.locked)
    argv.append(f"{job.method.output_flag}={_format(job.output)}")
    return argv


def _parser_problem(job: Job) -> str | None:
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(buffer):
            method_parser(job.method.name).parse_args(build_argv(job))
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
        f"# {STRUCTURE_ONLY_NOTE}",
        "",
        f"method: {method.name}",
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
    lines += ["", "# ---- 可选（后面的值是默认值）----"]
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
    print("可用的建模方法（只生成结构，不计算能量）：\n", file=stream)
    for method in METHODS.values():
        required = [o.key for o in method.options if o.required] + [
            "/".join(g.keys) for g in method.groups if g.mode in {"one", "any"}
        ]
        print(f"  {method.name:<15s} {method.title}", file=stream)
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
    print("\n固定设置（不能修改）：" + (" ".join(method.locked) if method.locked else "无（纯几何方法）"), file=stream)
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
        if check.min_vacuum_A is not None and check.min_vacuum_A < MIN_VACUUM_A:
            status = "WARN"
            messages.append(f"{relative}：真空层只有 {check.min_vacuum_A} Å（< {MIN_VACUUM_A} Å）")
        if keeps_constraints and not all(fixed):
            status = "WARN"
            messages.append(f"{relative}：有结构没有固定原子")
        records.append({"path": relative, "frames": metrics, "file": file})
    return status, messages, checks, records


def _write_resolved_job(job: Job) -> Path:
    data: dict[str, Any] = {"method": job.method.name}
    if job.description:
        data["description"] = job.description
    data["output"] = job.output.as_posix()
    for key, value in job.values.items():
        data[key] = value.as_posix() if isinstance(value, Path) else value
    header = (
        f"# {PROG} 实际运行的任务（来源：{job.source.as_posix()}；路径已展开为绝对路径）\n"
        f"# 固定设置：{' '.join(job.method.locked) or '无'}\n"
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
    parameters = json_ready(job.values)
    inputs = [
        {"key": key, "path": path.as_posix(), "sha256": sha256_of(path) if path.is_file() else None}
        for key, path in job.input_paths()
    ]
    ok = result.status in {"PASS", "WARN"}
    manifest = RunManifest(run_id=run_id, metadata=json_ready({
        "tool": PROG,
        "method": job.method.name,
        "job_file": job.source.as_posix(),
        "description": job.description,
        "mode": "structure-only",
        "calculator": "none",
        "energies_available": False,
        "note": STRUCTURE_ONLY_NOTE,
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
                evidence_level=EvidenceLevel.HEURISTIC,
                validation_status=ValidationStatus.PASSED if result.status == "PASS" else ValidationStatus.NEEDS_REVIEW,
                metadata=json_ready({
                    "mode": "structure-only",
                    "calculator": "none",
                    "energies_available": False,
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
            "locked": list(job.method.locked),
            "log": "run.log",
            "resolved_job": "job_resolved.yaml",
            "status": result.status,
            "notes": list(job.method.notes),
        }),
    ))
    return save_manifest(job.output, manifest)


def run_job(job: Job, *, overwrite: bool = False, quiet: bool = False, stream: TextIO = sys.stdout) -> JobResult:
    """Run one validated job in a subprocess and check what it wrote."""
    missing = [f"{key}: {path}" for key, path in job.input_paths() if not path.is_file()]
    if missing:
        return JobResult(job, "FAIL", messages=["输入文件不存在：" + "；".join(missing)])
    if _directory_has_content(job.output) and not overwrite:
        return JobResult(job, "FAIL", messages=[
            f"输出目录 {job.output} 已有内容；请换一个 output，删除该目录，或在 run 时加 --overwrite（旧文件不会被删除）"
        ])
    job.output.mkdir(parents=True, exist_ok=True)
    _write_resolved_job(job)
    argv = build_argv(job)
    command = [
        sys.executable, "-c",
        "import importlib, sys; sys.exit(importlib.import_module(sys.argv[1]).main(sys.argv[2:]))",
        job.method.module, *argv,
    ]
    env = dict(os.environ)
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
            result.manifest = _write_manifest(job, result, command=command, exit_code=None, started_at=started_at, records=[])
            raise
        log.write(f"[exit {exit_code}]\n")
    seconds = round(time.perf_counter() - started, 1)
    if exit_code != 0:
        tail = [line for line in lines if line.strip()][-4:]
        result = JobResult(job, "FAIL", seconds, [f"方法运行失败（退出码 {exit_code}），最后几行输出：", *tail])
        result.manifest = _write_manifest(job, result, command=command, exit_code=exit_code, started_at=started_at, records=[])
        return result
    status, messages, checks, records = _check_outputs(job, since=started_wall)
    result = JobResult(job, status, seconds, messages, checks)
    result.manifest = _write_manifest(
        job, result, command=command, exit_code=exit_code, started_at=started_at, records=records if status != "FAIL" else []
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


def _load_all(paths: Iterable[Path], stream: TextIO) -> list[Job] | None:
    jobs: list[Job] = []
    failed = False
    for path in expand_paths(paths):
        try:
            jobs.extend(load_job_file(path))
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
        print(f"    说明：{STRUCTURE_ONLY_NOTE}", file=stream)
        for note in result.job.method.notes:
            print(f"    说明：{note}", file=stream)
    if result.manifest is not None:
        print(f"    记录：{result.manifest}（运行输出见同目录 run.log）", file=stream)


def command_check(paths: list[Path], stream: TextIO) -> int:
    jobs = _load_all(paths, stream)
    if jobs is None:
        return 2
    planned: list[Path] = []
    missing = 0
    for job in jobs:
        absent = []
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


def command_run(paths: list[Path], *, overwrite: bool, quiet: bool, stream: TextIO) -> int:
    jobs = _load_all(paths, stream)
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

{STRUCTURE_ONLY_NOTE}
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Genkai 表面建模：用 YAML 任务文件生成表面结构。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="命令")
    methods = commands.add_parser("methods", help="列出可用的建模方法；加方法名查看该方法的全部参数")
    methods.add_argument("name", nargs="?", choices=list(METHODS), help="方法名")
    template = commands.add_parser("template", help="生成某个方法的任务文件模板")
    template.add_argument("method", choices=list(METHODS), help="方法名")
    template.add_argument("-o", "--output", type=Path, default=None, help="写入这个文件（不写则打印到屏幕）")
    template.add_argument("--force", action="store_true", help="文件已存在时覆盖")
    check = commands.add_parser("check", help="只检查任务文件，不运行")
    check.add_argument("job_files", nargs="+", type=Path, metavar="任务文件")
    run = commands.add_parser("run", help="运行任务文件（可以一次给多个）")
    run.add_argument("job_files", nargs="+", type=Path, metavar="任务文件")
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
        return command_check(args.job_files, stream)
    try:
        return command_run(args.job_files, overwrite=args.overwrite, quiet=args.quiet, stream=stream)
    except KeyboardInterrupt:
        print(file=stream)
        print("已中断；当前任务的输出目录里保留了 run.log 和 manifest.json。", file=stream)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
