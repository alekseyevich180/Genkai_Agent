"""Pipelines: chain surface-modeling methods in one job file (``genkai-surface check/run``).

A pipeline file lists steps instead of jobs::

    output: runs/pt_on_reduced_sno2    # optional; default runs/<file name>
    mlip: uma                          # optional; energy model for relax steps and energy picks
    pipeline:
      - method: slab
        bulk: inputs/SnO2.cif
        facet: "110"
        repeat_xy: [2, 4]
      - method: vacancy
        vacancy_counts: [1]
        samples_per_count: 6
        pick: lowest_energy            # relax every candidate with the MLIP, keep the lowest
      - method: cluster
        cluster_element: Pt
        cluster_atoms: 13
        cluster_structures: [fcc, hcp]
        pick: lowest_energy
      - method: relax                  # optional intermediate relaxation
      - method: adsorbate
        molecule: inputs/CO.xyz
        site_symbols: [Pt]

Each step is an ordinary job of that method; the pipeline wires the structure of
the previous step into its input (``surface``, ``input``, ``amorphous`` or
``structures``), so no output file names are written by hand. ``pick`` chooses
which candidates of a step continue:

* ``first`` (default), an index or a list of indices, or ``all`` (every candidate
  becomes a branch; ``max_branches`` caps the total);
* ``lowest_energy``: the candidates are relaxed with the ``mlip`` profile (method
  ``relax``), grouped by composition, and the ``pick_count`` (default 1) lowest of
  every group continue as relaxed structures. Energies are never taken from the
  mock calculator, and they are compared only within one step of one branch.

Steps must follow the modeling order (``STEP_KINDS``): bulk phase -> surface ->
lattice defects -> ALD overlayer -> supported clusters -> SAM -> gas adsorbates;
``relax`` may appear anywhere after the first step. ``allow_order: true`` accepts
another order on purpose (e.g. vacancies in an ALD film: vacancy after ald with
``components: [overlayer]``).

Between steps every candidate is checked and normalised: atoms carry a
``component`` label (substrate, overlayer, cluster, sam, adsorbate) so later
builders keep clear of what earlier steps added; the vacuum above the top atom is
restored to ``min_vacuum``; fixed atoms are kept. The pipeline writes
``pipeline_structures.extxyz`` (the final structures, each with its lineage label)
and ``pipeline_manifest.json`` (steps, runs, picks, energies and lineage).
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import numpy as np
import yaml
from ase import Atoms

from ..structure_io import (
    components,
    has_components,
    label_components,
    read_frames,
    write_frames,
    write_manifest,
)
from . import jobs

GENERATOR = "genkai.modeling.surface.app.pipeline"
DEFAULT_MIN_VACUUM_A = 10.0
DEFAULT_MAX_BRANCHES = 20
TOP_KEYS = {"pipeline", "output", "description", "allow_order", "min_vacuum", "max_branches", "config", "mlip"}
STEP_ONLY_KEYS = {"pick", "pick_count"}
STEP_FORBIDDEN_KEYS = {"output": "步骤的输出目录由流水线自动安排", "config": "MLIP 配置文件写在流水线顶层 config"}


@dataclass(frozen=True)
class StepKind:
    stage: int  # -1: does not change the modeling stage (relax)
    stage_name: str
    input_key: str | None  # option that receives the previous structure
    needs: str | None  # what the previous step must produce: surface | amorphous_bulk | any; None = first step only
    makes: str  # surface | amorphous_bulk | same (as its input)
    candidates: str  # output file holding every candidate
    skip_roles: frozenset[str] = frozenset()
    component: str | None = None  # label of the atoms this step adds
    blocked_keys: tuple[str, ...] = ()  # other inputs that conflict with the wired one


STEP_KINDS: dict[str, StepKind] = {
    "amorphous_bulk": StepKind(0, "体相", None, None, "amorphous_bulk", "amorphous_bulk_structures.extxyz", component="substrate"),
    "slab": StepKind(1, "表面", None, None, "surface", "slab.extxyz", component="substrate"),
    "amorphous_slab": StepKind(1, "表面", "amorphous", "amorphous_bulk", "surface", "amorphous_slab_structures.extxyz",
                               component="substrate"),
    "vacancy": StepKind(2, "晶格缺陷", "input", "surface", "surface", "vacancy_structures.extxyz"),
    "ald": StepKind(3, "覆盖层", "surface", "surface", "surface", "ald_structures.extxyz", frozenset({"clean_slab"}),
                    "overlayer", ("bulk",)),
    "cluster": StepKind(4, "负载团簇", "surface", "surface", "surface", "cluster_structures.extxyz", component="cluster"),
    "sam": StepKind(5, "有机修饰", "surface", "surface", "surface", "sam_structures.extxyz", frozenset({"clean_slab"}),
                    "sam", ("bulk",)),
    "adsorbate": StepKind(6, "气体吸附", "surface", "surface", "surface", "adsorbate_structures.extxyz", component="adsorbate"),
    "relax": StepKind(-1, "弛豫", "structures", "any", "same", "relaxed_structures.extxyz"),
}
ORDER_TEXT = "amorphous_bulk → slab/amorphous_slab → vacancy → ald → cluster → sam → adsorbate（relax 可放在任意一步之后）"
# Applied when a step does not set them; recorded in the pipeline manifest.
STEP_DEFAULTS: dict[str, dict[str, str]] = {
    # Surface vacancies: the vacancy method alone samples every O of the slab by default.
    "vacancy": {"surface_depth": "2.5"},
}
VACANCY_WINDOW_KEYS = {"surface_depth", "z_frac_min", "z_frac_max"}


class PipelineError(jobs.JobFileError):
    """A pipeline file that cannot be run; ``problems`` holds one message per issue."""


@dataclass(frozen=True)
class Pick:
    mode: str  # first | all | index | lowest_energy
    indices: tuple[int, ...] = ()
    count: int = 1  # lowest_energy: kept per composition

    @property
    def by_energy(self) -> bool:
        return self.mode == "lowest_energy"

    def text(self) -> str:
        if self.mode == "index":
            return ",".join(map(str, self.indices))
        if self.by_energy:
            return f"lowest_energy（每种组成 {self.count} 个）"
        return self.mode

    def select(self, count: int) -> list[int]:
        if self.mode == "first":
            return [0] if count else []
        if self.mode == "all":
            return list(range(count))
        if self.by_energy:
            raise ValueError("lowest_energy is selected from energies, not by position")
        bad = [i for i in self.indices if i >= count]
        if bad:
            raise IndexError(f"pick 的序号 {bad} 超出范围（本步只有 {count} 个候选，序号从 0 开始）")
        return list(self.indices)


def select_lowest(records: list[dict[str, Any]], count: int) -> list[int]:
    """Indices of the ``count`` lowest-energy records of every composition, by group then energy."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["formula"], []).append(record)
    chosen: list[int] = []
    for formula in sorted(groups):
        ranked = sorted(groups[formula], key=lambda r: r["energy_eV"])
        chosen.extend(r["index"] for r in ranked[:count])
    return chosen


@dataclass
class Step:
    index: int
    method: str
    kind: StepKind
    mapping: dict[str, Any]
    pick: Pick
    defaults_applied: dict[str, str]
    template: jobs.Job
    makes: str = "surface"  # what this step hands on (resolved for relax steps)
    energy_template: jobs.Job | None = None  # the relax job that ranks candidates (pick: lowest_energy)

    @property
    def title(self) -> str:
        return f"第 {self.index + 1} 步 {self.method}"

    def directory(self, output: Path) -> Path:
        return output / f"{self.index + 1:02d}_{self.method}"


@dataclass
class Pipeline:
    source: Path
    output: Path
    steps: list[Step]
    min_vacuum: float
    max_branches: int
    allow_order: bool
    description: str | None
    config_path: Path | None
    mlip: str | None = None


@dataclass
class Branch:
    lineage: tuple[int, ...]
    structure: Path | None
    chain: list[dict[str, Any]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "root" if not self.lineage else "c" + "-".join(map(str, self.lineage))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _read_mapping(path: Path) -> Any:
    return yaml.load(jobs._read_text(path), Loader=yaml.BaseLoader)


def is_pipeline_file(path: Path) -> bool:
    try:
        data = _read_mapping(path) if path.is_file() else None
    except (yaml.YAMLError, jobs.JobFileError):
        return False
    return isinstance(data, dict) and "pipeline" in data


def _parse_pick(value: Any, count: Any = None) -> Pick:
    if count is not None and not jobs._unset(count):
        try:
            number = int(str(count).strip())
        except ValueError:
            raise ValueError(f"pick_count 需要正整数，写的是 {count!r}") from None
        if number < 1:
            raise ValueError("pick_count 需要正整数")
        if not (isinstance(value, str) and value.strip().lower() == "lowest_energy"):
            raise ValueError("pick_count 只和 pick: lowest_energy 一起用")
        return Pick("lowest_energy", count=number)
    if value is None or (isinstance(value, str) and value.strip().lower() in {"", "first"}):
        return Pick("first")
    if isinstance(value, str) and value.strip().lower() == "all":
        return Pick("all")
    if isinstance(value, str) and value.strip().lower() == "lowest_energy":
        return Pick("lowest_energy")
    items = value if isinstance(value, list) else [value]
    try:
        indices = tuple(int(str(item).strip()) for item in items)
    except ValueError:
        raise ValueError(f"pick 只能是 first、all、lowest_energy、一个序号或序号列表，写的是 {value!r}") from None
    if not indices or min(indices) < 0 or len(set(indices)) != len(indices):
        raise ValueError("pick 的序号从 0 开始，不能重复")
    return Pick("index", indices)


def _number(data: dict[str, Any], key: str, default: float, kind: type, problems: list[str]) -> Any:
    if key not in data or jobs._unset(data[key]):
        return default
    try:
        value = kind(str(data[key]).strip())
    except ValueError:
        problems.append(f"{key} 需要{'整数' if kind is int else '数字'}，写的是 {data[key]!r}")
        return default
    if value <= 0:
        problems.append(f"{key} 必须大于 0")
    return value


def _placeholder(output: Path, step_index: int, method: str) -> Path:
    return output / f"{step_index:02d}_{method}" / "<由上一步生成>" / "candidate.extxyz"


def _energy_job_mapping(structures: Path, output: Path, mlip: str | None) -> dict[str, Any]:
    return {"method": "relax", "mlip": mlip or "default", "structures": str(structures), "output": str(output)}


def load_pipeline(path: str | Path, *, config_path: Path | None = None) -> Pipeline:
    source = Path(path).resolve()
    if not source.is_file():
        raise PipelineError(source, ["流水线文件不存在"])
    try:
        data = _read_mapping(source)
    except yaml.YAMLError as exc:
        raise PipelineError(source, [f"YAML 格式错误：{exc}"]) from None
    problems: list[str] = []
    extra = sorted(set(data) - TOP_KEYS)
    if extra:
        problems.append(f"流水线顶层只能写 {', '.join(sorted(TOP_KEYS))}；多出了：{', '.join(extra)}")
    raw_steps = data.get("pipeline")
    if not isinstance(raw_steps, list) or not raw_steps or not all(isinstance(s, dict) for s in raw_steps):
        raise PipelineError(source, ["pipeline 需要是步骤列表，每一步以 “- method: ...” 开头"])
    output_raw = data.get("output")
    if jobs._unset(output_raw):
        output = (source.parent / "runs" / source.stem).resolve()
    else:
        output = Path(os.path.expanduser(str(output_raw).strip()))
        output = (output if output.is_absolute() else source.parent / output).resolve()
    allow = str(data.get("allow_order", "false")).strip().lower()
    if allow not in {"true", "false"}:
        problems.append("allow_order 需要 true 或 false")
    min_vacuum = _number(data, "min_vacuum", DEFAULT_MIN_VACUUM_A, float, problems)
    max_branches = _number(data, "max_branches", DEFAULT_MAX_BRANCHES, int, problems)
    if config_path is None and not jobs._unset(data.get("config")):
        config_path = (source.parent / Path(os.path.expanduser(str(data["config"]).strip()))).absolute()
    mlip = None if jobs._unset(data.get("mlip")) else str(data["mlip"]).strip()
    if mlip is not None and mlip.lower() == "none":
        problems.append("顶层 mlip 是能量模型的配置名（如 uma、mace、default）；不需要能量时不写这一项")
        mlip = None

    steps: list[Step] = []
    previous: Step | None = None  # last valid step
    previous_stage: Step | None = None  # last valid step that sets a modeling stage
    for index, raw in enumerate(raw_steps):
        prefix = f"第 {index + 1} 步："
        mapping = {str(k).strip().replace("-", "_"): v for k, v in raw.items()}
        method = str(mapping.get("method", "")).strip().lower().replace("-", "_")
        kind = STEP_KINDS.get(method)
        if kind is None:
            hint = "（能量筛选方法以后接入；可在流水线结果上单独运行）" if method in jobs.METHODS else ""
            problems.append(f"{prefix}method {mapping.get('method')!r} 不能用于流水线；可用：{', '.join(STEP_KINDS)}{hint}")
            previous = previous_stage = None
            continue
        for key, reason in STEP_FORBIDDEN_KEYS.items():
            if key in mapping:
                problems.append(f"{prefix}不能写 {key}：{reason}")
                mapping.pop(key)
        try:
            pick = _parse_pick(mapping.pop("pick", None), mapping.pop("pick_count", None))
        except ValueError as exc:
            problems.append(f"{prefix}{exc}")
            pick = Pick("first")
        makes = kind.makes
        if index == 0:
            if kind.needs is not None and kind.input_key not in mapping:
                problems.append(f"{prefix}第一步要自己提供 {kind.input_key}（后面的步骤会自动接上一步的结构）")
            if makes == "same":
                makes = "surface"
        else:
            wired = [key for key in (kind.input_key, *kind.blocked_keys) if key and key in mapping]
            if wired:
                problems.append(f"{prefix}不要写 {', '.join(wired)}：流水线会把上一步的结构接到 {kind.input_key}")
            if kind.needs is None:
                problems.append(f"{prefix}{method} 只能是第一步")
            elif previous is not None and kind.needs not in ("any", previous.makes):
                need = "表面（先用 slab 或 amorphous_slab）" if kind.needs == "surface" else "非晶块体（amorphous_bulk）"
                problems.append(f"{prefix}{method} 需要上一步给出{need}，但上一步 {previous.method} 不是")
            elif (previous_stage is not None and kind.stage >= 0 and kind.stage < previous_stage.kind.stage
                  and allow != "true"):
                problems.append(
                    f"{prefix}{method}（{kind.stage_name}）不能放在 {previous_stage.method}（{previous_stage.kind.stage_name}）之后；"
                    f"建议顺序 {ORDER_TEXT}。确实需要这样做时在顶层写 allow_order: true"
                )
            if makes == "same":
                makes = previous.makes if previous is not None else "surface"
        if method == "relax" and "mlip" not in mapping and mlip:
            mapping["mlip"] = mlip
        defaults_applied: dict[str, str] = {}
        for key, value in STEP_DEFAULTS.get(method, {}).items():
            if method == "vacancy" and VACANCY_WINDOW_KEYS & set(mapping):
                continue
            if key not in mapping:
                mapping[key] = value
                defaults_applied[key] = value
        probe = dict(mapping)
        probe["output"] = str(_placeholder(output, index + 1, method).parent)
        if index > 0 and kind.input_key:
            probe[kind.input_key] = str(_placeholder(output, index + 1, method))
        job, issues = jobs._parse_job(source, index, probe, config_path)
        problems.extend(prefix + issue for issue in issues)
        energy_job = None
        if pick.by_energy and method != "relax":
            # Energies come from relaxing the candidates with the pipeline's MLIP profile.
            placeholder = _placeholder(output, index + 1, method)
            energy_job, energy_issues = jobs._parse_job(
                source, index, _energy_job_mapping(placeholder, placeholder.parent / "energy", mlip), config_path
            )
            problems.extend(f"{prefix}pick: lowest_energy 需要能量模型：{issue}" for issue in energy_issues)
        if job is None:
            previous = previous_stage = None
            continue
        step = Step(index, method, kind, mapping, pick, defaults_applied, job, makes, energy_job)
        steps.append(step)
        previous = step
        if kind.stage >= 0:
            previous_stage = step
    if problems:
        raise PipelineError(source, problems)
    description = None if jobs._unset(data.get("description")) else str(data["description"]).strip()
    return Pipeline(source, output, steps, float(min_vacuum), int(max_branches), allow == "true", description,
                    config_path, mlip)


# ---------------------------------------------------------------------------
# Between steps
# ---------------------------------------------------------------------------


def ensure_vacuum(atoms: Atoms, min_vacuum: float) -> float:
    """Raise the cell top so ``min_vacuum`` A of vacuum lie above the top atom; return the added height."""
    cell = atoms.cell.array.copy()
    if np.abs(cell[2, :2]).max() > 1e-4 or np.abs(cell[:2, 2]).max() > 1e-4:
        return 0.0  # c is not the surface normal; leave the cell alone
    needed = float(atoms.positions[:, 2].max()) + min_vacuum
    if needed <= cell[2, 2] + 1e-9:
        return 0.0
    added = needed - float(cell[2, 2])
    cell[2, 2] = needed
    atoms.set_cell(cell, scale_atoms=False)
    return added


def finalize_candidate(frame: Atoms, step: Step, *, first: bool, min_vacuum: float) -> tuple[Atoms, dict[str, Any]]:
    """Check labels, restore vacuum and wrap in-plane; return the frame and what was changed."""
    atoms = frame.copy()
    notes: list[str] = []
    if not has_components(atoms):
        if not first and step.kind.stage != 0 and step.kind.stage != 1:
            raise RuntimeError(f"{step.method} 的输出丢失了原子来源标签（component），无法继续串联")
        label_components(atoms, "substrate")
    labels = components(atoms)
    unknown = np.flatnonzero(labels == "")
    if len(unknown):
        label = step.kind.component or "substrate"
        label_components(atoms, label, unknown)
        notes.append(f"{len(unknown)} 个原子没有来源标签，按本步记为 {label}")
    surface = step.makes == "surface"
    added = ensure_vacuum(atoms, min_vacuum) if surface else 0.0
    if surface:
        atoms.wrap(pbc=[True, True, False])
    record = {
        "n_atoms": len(atoms),
        "formula": atoms.get_chemical_formula(mode="hill"),
        "components": dict(Counter(components(atoms).tolist())),
        "vacuum_added_A": round(added, 3),
        "notes": notes,
    }
    return atoms, record


def _candidates(job: jobs.Job, kind: StepKind) -> list[Atoms]:
    path = job.output / kind.candidates
    if not path.is_file():
        raise FileNotFoundError(f"{job.method.name} 没有写出候选结构文件 {path.name}")
    return [frame for frame in read_frames(path) if frame.info.get("role") not in kind.skip_roles]


def _energies_from_relax(output: Path) -> tuple[list[Atoms], list[dict[str, Any]]]:
    manifest = json.loads((output / "relax_manifest.json").read_text(encoding="utf-8"))
    return read_frames(output / "relaxed_structures.extxyz"), manifest["frames"]


# ---------------------------------------------------------------------------
# Check and run
# ---------------------------------------------------------------------------


def check_pipeline(pipeline: Pipeline, stream: TextIO) -> int:
    print(f"[流水线] {pipeline.source} -> {pipeline.output}", file=stream)
    print(f"    顺序：{' → '.join(step.method for step in pipeline.steps)}"
          + ("（allow_order: true）" if pipeline.allow_order else ""), file=stream)
    if pipeline.mlip:
        print(f"    能量模型（relax 步和 lowest_energy）：{pipeline.mlip}", file=stream)
    missing = 0
    probed: dict[tuple[Path, str], str | None] = {}
    for step in pipeline.steps:
        job = step.template
        print(f"  [{step.title}] {step.kind.stage_name}  pick: {step.pick.text()}", file=stream)
        for candidate in (job, step.energy_template):
            profile = candidate.profile if candidate is not None else None
            if profile is None:
                continue
            key = (profile.config_path, profile.name)
            if key in probed:
                continue  # each profile is checked and reported once
            try:
                jobs.probe_profile(profile, jobs._package_root())
                probed[key] = None
            except jobs.MlipConfigError as exc:
                probed[key] = str(exc)
                print(f"    ! MLIP 配置 {profile.name}：{exc}", file=stream)
                missing += 1
        for key, path in job.input_paths():
            if step.index > 0 and key == step.kind.input_key:
                print(f"    {key} ← 第 {step.index} 步选出的结构", file=stream)
            elif not path.is_file():
                print(f"    ! {key}：文件不存在 {path}", file=stream)
                missing += 1
        if step.defaults_applied:
            print(f"    流水线默认：{', '.join(f'{k}={v}' for k, v in step.defaults_applied.items())}", file=stream)
        if step.pick.by_energy and step.method != "relax":
            print(f"    按能量挑选：先用 {pipeline.mlip or 'default'} 弛豫全部候选，再按组成取最低", file=stream)
        print(f"    将运行：{job.method.module} {jobs.display_command(jobs.build_argv(job))}", file=stream)
    if jobs._directory_has_content(pipeline.output):
        print("    注意：输出目录已有内容，运行时需要加 --overwrite 或换一个 output", file=stream)
    if missing:
        print(f"流水线共 {len(pipeline.steps)} 步，{missing} 个输入文件或 MLIP 环境有问题。", file=stream)
        return 2
    print(f"流水线共 {len(pipeline.steps)} 步，检查通过。", file=stream)
    return 0


def _pick_by_energy(
    pipeline: Pipeline, step: Step, job: jobs.Job, run_dir: Path, finalized: list[Atoms],
    *, overwrite: bool, quiet: bool, stream: TextIO,
) -> tuple[list[int], list[Atoms], list[dict[str, Any]], str | None, str]:
    """Relax every candidate (unless the step is a relax step), then keep the lowest per composition."""
    if step.method == "relax":
        relaxed, records = _energies_from_relax(job.output)
        energy_manifest = (job.output / "relax_manifest.json").as_posix()
        model = _model_text(job)
    else:
        structures = write_frames(run_dir / "pipeline" / "all_candidates.extxyz", finalized)
        energy_dir = run_dir / "energy"
        energy_job, issues = jobs._parse_job(
            pipeline.source, step.index, _energy_job_mapping(structures, energy_dir, pipeline.mlip), pipeline.config_path
        )
        if energy_job is None:
            raise RuntimeError("无法准备能量计算：" + "；".join(issues))
        print(f"    流水线：用 {energy_job.profile.name if energy_job.profile else '?'} 弛豫 {len(finalized)} 个候选以比较能量",
              file=stream)
        result = jobs.run_job(energy_job, overwrite=overwrite, quiet=quiet, stream=stream)
        jobs._print_result(result, stream)
        if result.status == "FAIL":
            raise RuntimeError(f"候选的能量计算失败，见 {energy_dir / 'run.log'}")
        relaxed, records = _energies_from_relax(energy_dir)
        energy_manifest = (energy_dir / "relax_manifest.json").as_posix()
        model = _model_text(energy_job)
    chosen = select_lowest(records, step.pick.count)
    return chosen, relaxed, records, energy_manifest, model


def _model_text(job: jobs.Job) -> str:
    return f"{job.profile.name} ({job.calculator})" if job.profile else "none"


def run_pipeline(pipeline: Pipeline, *, overwrite: bool = False, quiet: bool = False, stream: TextIO = sys.stdout) -> int:
    if jobs._directory_has_content(pipeline.output) and not overwrite:
        print(f"输出目录 {pipeline.output} 已有内容；请换一个 output、删除该目录，或加 --overwrite。", file=stream)
        return 1
    print(f"\n== 流水线 {pipeline.source.name}：{' → '.join(s.method for s in pipeline.steps)}", file=stream)
    print(f"    输出目录：{pipeline.output}", file=stream)
    branches = [Branch((), None)]
    step_records: list[dict[str, Any]] = []
    failures: list[str] = []
    statuses: list[str] = []
    evidence: set[str] = set()
    for step in pipeline.steps:
        runs: list[dict[str, Any]] = []
        next_branches: list[Branch] = []
        for branch in branches:
            run_dir = step.directory(pipeline.output) / branch.name
            mapping = dict(step.mapping)
            mapping["output"] = str(run_dir)
            if step.index > 0 and step.kind.input_key:
                mapping[step.kind.input_key] = str(branch.structure)
            job, issues = jobs._parse_job(pipeline.source, step.index, mapping, pipeline.config_path)
            print(f"\n== [{step.title}] {branch.name}  →  {run_dir}", file=stream)
            run: dict[str, Any] = {"branch": branch.name, "run_dir": run_dir.as_posix(), "input": (
                branch.structure.as_posix() if branch.structure else None)}
            if job is None:
                run.update(status="FAIL", messages=issues)
                failures.append(f"{step.title} {branch.name}：" + "；".join(issues))
                runs.append(run)
                continue
            result = jobs.run_job(job, overwrite=overwrite, quiet=quiet, stream=stream)
            jobs._print_result(result, stream)
            statuses.append(result.status)
            run.update(status=result.status, manifest=result.manifest.as_posix() if result.manifest else None,
                       calculator=job.calculator)
            if job.profile:
                evidence.add(_model_text(job))
            if result.status == "FAIL":
                failures.append(f"{step.title} {branch.name}：方法运行失败，见 {run_dir / 'run.log'}")
                runs.append(run)
                continue
            try:
                frames = _candidates(job, step.kind)
                if not frames:
                    raise IndexError("本步没有生成候选结构")
                finalized = [finalize_candidate(frame, step, first=step.index == 0, min_vacuum=pipeline.min_vacuum)
                             for frame in frames]
                energies: list[dict[str, Any]] | None = None
                if step.pick.by_energy:
                    chosen, relaxed, energies, energy_manifest, model = _pick_by_energy(
                        pipeline, step, job, run_dir, [atoms for atoms, _ in finalized],
                        overwrite=overwrite, quiet=quiet, stream=stream,
                    )
                    run["energy_manifest"] = energy_manifest
                    run["energy_model"] = model
                    evidence.add(model)
                    finalized = [finalize_candidate(atoms, step, first=step.index == 0, min_vacuum=pipeline.min_vacuum)
                                 for atoms in relaxed]
                else:
                    chosen = step.pick.select(len(frames))
                if not chosen:
                    raise IndexError("本步没有生成候选结构")
            except (FileNotFoundError, IndexError, RuntimeError) as exc:
                run.update(status="FAIL", messages=[str(exc)])
                failures.append(f"{step.title} {branch.name}：{exc}")
                runs.append(run)
                continue
            picked = []
            for candidate in chosen:
                atoms, record = finalized[candidate]
                label = " > ".join([*(f"{c['method']}#{c['candidate']}" for c in branch.chain), f"{step.method}#{candidate}"])
                atoms.info = {"pipeline_label": label, "pipeline_step": step.index + 1}
                path = write_frames(run_dir / "pipeline" / f"candidate_{candidate:03d}.extxyz", [atoms])
                link = {"step": step.index + 1, "method": step.method, "candidate": candidate,
                        "run_dir": run_dir.as_posix(), "file": path.as_posix(), **record}
                if energies is not None:
                    link["energy_eV"] = energies[candidate]["energy_eV"]
                    link["relaxed_for_pick"] = step.method != "relax"
                picked.append(link)
                next_branches.append(Branch((*branch.lineage, candidate), path, [*branch.chain, link]))
            run.update(candidates=len(frames), picked=[p["candidate"] for p in picked])
            if energies is not None:
                run["energies"] = [{"candidate": r["index"], "formula": r["formula"], "energy_eV": r["energy_eV"],
                                    "converged": r["converged"], "picked": r["index"] in chosen} for r in energies]
            runs.append(run)
            text = f"    流水线：{len(frames)} 个候选，选中 {[p['candidate'] for p in picked]}"
            if energies is not None:
                text += "（按能量：" + "，".join(f"#{p['candidate']} {p['energy_eV']:.4f} eV" for p in picked) + "）"
            text += "".join(f"；候选 {p['candidate']} 真空补足 {p['vacuum_added_A']} Å" for p in picked if p["vacuum_added_A"] > 0)
            print(text, file=stream)
        step_records.append({
            "step": step.index + 1, "method": step.method, "stage": step.kind.stage, "stage_name": step.kind.stage_name,
            "pick": step.pick.text(), "defaults_applied": step.defaults_applied, "runs": runs,
        })
        if len(next_branches) > pipeline.max_branches:
            failures.append(
                f"{step.title} 之后有 {len(next_branches)} 个分支，超过 max_branches={pipeline.max_branches}；"
                "请减少 pick 选中的候选，或调大 max_branches"
            )
            next_branches = []
        branches = next_branches
        if not branches:
            break

    complete = len(step_records) == len(pipeline.steps) and bool(branches)
    leaves: list[dict[str, Any]] = []
    frames_out: list[Atoms] = []
    if complete:
        for branch in branches:
            [atoms] = read_frames(branch.structure)  # type: ignore[arg-type]
            frames_out.append(atoms)
            leaves.append({"label": atoms.info.get("pipeline_label"), "file": branch.structure.as_posix(),  # type: ignore[union-attr]
                           "components": dict(Counter(components(atoms).tolist())), "lineage": branch.chain})
    structures_path = write_frames(pipeline.output / "pipeline_structures.extxyz", frames_out) if frames_out else None
    status = "FAIL" if failures or not complete else ("WARN" if "WARN" in statuses else "PASS")
    manifest = {
        "schema_version": "1.0",
        "generator": GENERATOR,
        "source": pipeline.source.as_posix(),
        "description": pipeline.description,
        "status": status,
        "order": [step.method for step in pipeline.steps],
        "settings": {"min_vacuum_A": pipeline.min_vacuum, "max_branches": pipeline.max_branches,
                     "allow_order": pipeline.allow_order, "mlip": pipeline.mlip},
        "energy_models_used": sorted(evidence),
        "steps": step_records,
        "structures": leaves,
        "files": {"structures": structures_path.as_posix() if structures_path else None},
        "failures": failures,
        "conventions": {
            "component": "per-atom array: substrate, overlayer (ALD), cluster, sam, adsorbate",
            "pipeline_label": "method#candidate for every step, in order",
            "energies": "lowest_energy compares MLIP energies of one step of one branch, grouped by composition; "
                        "see each step's manifest.json and energy/relax_manifest.json. Geometric steps carry no energies.",
        },
    }
    manifest_path = write_manifest(pipeline.output / "pipeline_manifest.json", manifest)
    print("\n== 流水线汇总", file=stream)
    for leaf in leaves:
        print(f"    {leaf['label']}  ({', '.join(f'{k} {v}' for k, v in leaf['components'].items())})", file=stream)
    for failure in failures:
        print(f"    ! {failure}", file=stream)
    print(f"    结果：{status}；最终结构 {len(leaves)} 个：{structures_path or '无'}", file=stream)
    print(f"    记录：{manifest_path}", file=stream)
    return 0 if status in {"PASS", "WARN"} else 1


def load_all(paths: list[Path], stream: TextIO, config_path: Path | None = None) -> list[Pipeline] | None:
    pipelines: list[Pipeline] = []
    failed = False
    for path in paths:
        try:
            pipelines.append(load_pipeline(path, config_path=config_path))
        except jobs.JobFileError as error:
            jobs._print_problems(error, stream)
            failed = True
    return None if failed else pipelines
