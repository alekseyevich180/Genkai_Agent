"""Structure-only execution of reviewed surface-modeling plans.

``build_surface_candidates`` only prepares commands. This executor turns a
:class:`ModelingPlanArtifact` into real, ASE-readable structures::

    slab (reviewed slab file, or a pymatgen slab cut from a bulk crystal)
    -> registered surface tasks (currently ``adsorbate_landscape``)
    -> one ``structures.extxyz`` registered as a ``StructureSetArtifact``

No energy model is run: task runners use ``calculator="none"`` and
``max_steps=0``, so every structure is an unrelaxed geometric candidate
(evidence level ``heuristic``). Mock energies used internally for placement are
never written into the structure set.

Inputs that a paper cannot determine — a slab or confirmed exposed facet, the
gas molecule, integer coverages — must come from explicit overrides. When a
checklist item of a selected task stays unresolved,
:class:`SurfaceExecutionBlocked` is raised and the run manifest is untouched.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
from ase import Atoms
from ase.constraints import FixAtoms
from ase.data import covalent_radii
from ase.io import read, write

from genkai.contracts.artifacts import (
    EvidenceLevel,
    ExecutionState,
    ModelingPlanArtifact,
    StructureSetArtifact,
    ValidationStatus,
)
from genkai.contracts.provenance import Provenance
from genkai.contracts.run import StageRecord
from genkai.contracts.validation import ValidationIssue, ValidationReport
from genkai.workflow.store import load_manifest, save_manifest


STAGE_BASE_ID = "03_surface_structures"
ADAPTER = "genkai.modeling.surface.executor"
CLASH_FRACTION = 0.6  # atoms of different fragments closer than 0.6 * (r_i + r_j) overlap
MIN_VACUUM_GAP_A = 5.0

# Reference gas-phase geometries from ASE's G2 set, keyed by canonical formula.
BUILTIN_GAS_MOLECULES: dict[str, str] = {
    "H2": "H2",
    "O2": "O2",
    "O3": "O3",
    "H2O": "H2O",
    "CO": "CO",
    "CO2": "CO2",
    "NO": "NO",
    "NO2": "NO2",
    "NH3": "NH3",
    "H2S": "SH2",
    "SO2": "SO2",
    "CH4": "CH4",
    "CH3OH": "CH3OH",
    "C2H5OH": "CH3CH2OH",
    "HCHO": "H2CO",
    "CH3CHO": "CH3CHO",
    "CH3COCH3": "CH3COCH3",
    "C6H6": "C6H6",
}
GAS_MOLECULE_ALIASES: dict[str, str] = {
    "hydrogen": "H2",
    "oxygen": "O2",
    "ozone": "O3",
    "water": "H2O",
    "carbon monoxide": "CO",
    "carbon dioxide": "CO2",
    "nitric oxide": "NO",
    "nitrogen monoxide": "NO",
    "nitrogen dioxide": "NO2",
    "ammonia": "NH3",
    "hydrogen sulfide": "H2S",
    "sulfur dioxide": "SO2",
    "methane": "CH4",
    "methanol": "CH3OH",
    "ethanol": "C2H5OH",
    "ch3ch2oh": "C2H5OH",
    "formaldehyde": "HCHO",
    "h2co": "HCHO",
    "acetaldehyde": "CH3CHO",
    "acetone": "CH3COCH3",
    "benzene": "C6H6",
}

UNSUPPORTED_TASK_REASONS: dict[str, str] = {
    "surface_functionalization": (
        "No reviewed SAM/functional-group builder exists; supply functionalized structures manually."
    ),
    "single_atom_site": "Single-atom site construction is not implemented.",
    "doped_surface": "Dopant substitution is not implemented in structure-only mode.",
    "vacancy_landscape": "Not yet registered for structure-only execution.",
    "surface_cluster_builder": "Not yet registered for structure-only execution.",
}

BulkProvider = Callable[..., tuple[Any, dict[str, Any]]]


def resolve_gas_molecule(name: str) -> tuple[str, Atoms]:
    """Canonical formula and G2 reference geometry for a built-in gas name."""
    from ase.build import molecule

    text = name.strip()
    canonical = text if text in BUILTIN_GAS_MOLECULES else None
    if canonical is None:
        lowered = text.casefold()
        canonical = GAS_MOLECULE_ALIASES.get(lowered) or next(
            (key for key in BUILTIN_GAS_MOLECULES if key.casefold() == lowered),
            None,
        )
    if canonical is None:
        supported = ", ".join(sorted(BUILTIN_GAS_MOLECULES))
        raise ValueError(f"Unknown built-in gas molecule {name!r}; supported: {supported}.")
    return canonical, molecule(BUILTIN_GAS_MOLECULES[canonical])


class SurfaceExecutionBlocked(RuntimeError):
    """Raised before any manifest change when required inputs are unresolved."""

    def __init__(self, missing: dict[str, str]):
        self.missing = dict(missing)
        self.parameters = tuple(self.missing)
        details = "; ".join(f"{key}: {reason}" for key, reason in self.missing.items())
        super().__init__(f"surface execution blocked by unresolved inputs -> {details}")


@dataclass(frozen=True)
class SurfaceExecutionOverrides:
    """Reviewed inputs that the paper cannot determine. All fields are optional."""

    surface: Path | None = None
    bulk: Path | None = None
    surface_formula: str | None = None
    surface_facet: str | None = None
    use_facet_registry: bool = False
    allow_materials_project: bool = False
    molecule: Path | None = None
    molecule_name: str | None = None
    coverage_counts: tuple[int, ...] | None = None
    site_symbols: tuple[str, ...] | None = None
    patterns: tuple[str, ...] | None = None
    random_repeats: int | None = None
    seed: int = 42
    document_id: str | None = None
    tasks: tuple[str, ...] | None = None

    def summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Path):
                value = str(value)
            elif isinstance(value, tuple):
                value = list(value)
            summary[key] = value
        return summary


@dataclass
class SurfaceExecutionResolution:
    """What will run, with which inputs, and what is still missing."""

    document_id: str | None
    tasks: list[str]
    skipped: dict[str, str]
    slab: dict[str, Any] | None
    inputs: dict[str, dict[str, Any]]
    missing: dict[str, str]
    notes: list[ValidationIssue] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "tasks": list(self.tasks),
            "skipped_tasks": dict(self.skipped),
            "slab": self.slab,
            "inputs": self.inputs,
            "missing": dict(self.missing),
            "notes": [note.model_dump() for note in self.notes],
        }


# ---------------------------------------------------------------------------
# Resolution (no side effects)
# ---------------------------------------------------------------------------


def _binding(document: dict[str, Any], task: str, parameter: str) -> dict[str, Any]:
    template = (document.get("task_argument_template") or {}).get(task) or {}
    return (template.get("parameter_bindings") or {}).get(parameter) or {}


def _select_document(
    payload: dict[str, Any],
    overrides: SurfaceExecutionOverrides,
    missing: dict[str, str],
) -> dict[str, Any] | None:
    documents = payload.get("documents") or []
    if overrides.document_id is not None:
        for document in documents:
            if document.get("id") == overrides.document_id:
                return document
        missing["document_id"] = f"No plan document has id {overrides.document_id!r}."
        return None
    candidates = [document for document in documents if document.get("executable_tasks")]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        missing["tasks"] = "The modeling plan has no executable surface task."
        return None
    ids = ", ".join(str(document.get("id")) for document in candidates)
    missing["document_id"] = f"The plan has several documents with executable tasks ({ids}); choose one."
    return None


def _largest_gap(atoms: Atoms) -> float:
    from .slab import vacuum_gap_angstrom

    return vacuum_gap_angstrom(atoms)


def _resolve_slab(
    document: dict[str, Any],
    overrides: SurfaceExecutionOverrides,
    missing: dict[str, str],
    notes: list[ValidationIssue],
) -> dict[str, Any] | None:
    if overrides.surface is not None:
        path = Path(overrides.surface)
        if not path.is_file():
            missing["surface"] = f"Slab file {path} does not exist."
            return None
        gap = _largest_gap(read(path))
        if gap < MIN_VACUUM_GAP_A:
            missing["surface"] = (
                f"{path.name} has only a {gap:.2f} A vacuum gap and looks like a bulk cell; "
                "pass it as --bulk or provide a slab."
            )
            return None
        if overrides.surface_facet or overrides.bulk:
            notes.append(
                ValidationIssue(
                    code="slab_file_takes_precedence",
                    message="A reviewed slab file was supplied; bulk/facet overrides are ignored.",
                )
            )
        return {"mode": "file", "path": str(path), "facet": None, "facet_source": "slab_file"}

    formula_binding = _binding(document, "slab_generation", "formula")
    formula = overrides.surface_formula or (
        formula_binding.get("value") if formula_binding.get("status") == "auto" else None
    )
    slab: dict[str, Any] | None = None
    if overrides.bulk is not None:
        bulk_path = Path(overrides.bulk)
        if bulk_path.is_file():
            slab = {"mode": "bulk", "path": str(bulk_path)}
        else:
            missing["bulk"] = f"Bulk file {bulk_path} does not exist."
    elif formula and overrides.allow_materials_project:
        slab = {"mode": "materials_project", "formula": formula}
    elif formula:
        missing["bulk"] = (
            f"Provide a local bulk crystal (--bulk) or a reviewed slab (--surface); fetching the "
            f"plan formula {formula} from Materials Project needs --allow-materials-project."
        )
    else:
        missing["surface"] = (
            "No bulk formula could be taken from the paper; provide a reviewed slab (--surface) "
            "or a bulk crystal (--bulk)."
        )
        return None

    # The facet is checked even when the bulk is missing, so every gap is reported at once.
    facet_binding = _binding(document, "slab_generation", "facet")
    facet: dict[str, Any] = {}
    if overrides.surface_facet:
        facet = {"facet": overrides.surface_facet, "facet_source": "override"}
    elif facet_binding.get("status") == "auto" and facet_binding.get("value"):
        facet = {"facet": facet_binding["value"], "facet_source": "paper_exposed_facet"}
    elif overrides.use_facet_registry:
        facet = {"facet": None, "facet_source": "stable_facet_registry"}
        if slab is not None and slab["mode"] == "bulk":
            try:
                from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

                from .slab import conventional_bulk, load_bulk, resolve_stable_facet

                conventional = conventional_bulk(load_bulk(slab["path"]))
                registry = resolve_stable_facet(
                    conventional.composition.reduced_formula,
                    SpacegroupAnalyzer(conventional, symprec=0.1).get_space_group_symbol(),
                )
                facet["facet_preview"] = list(registry.miller_index)
            except ValueError as exc:
                missing["surface_facet"] = str(exc)
    else:
        reason = facet_binding.get("reason") or "The paper gives no exposed facet."
        missing["surface_facet"] = (
            f"{reason} Provide --surface-facet, or --use-facet-registry to accept the reviewed registry."
        )
    if slab is None or "surface_facet" in missing:
        return None
    slab.update(facet)
    return slab


def _resolve_adsorbate_inputs(
    document: dict[str, Any],
    overrides: SurfaceExecutionOverrides,
    missing: dict[str, str],
) -> dict[str, dict[str, Any]]:
    inputs: dict[str, dict[str, Any]] = {}
    if overrides.molecule is not None:
        path = Path(overrides.molecule)
        if path.is_file():
            inputs["molecule"] = {"value": str(path), "source": "override_file"}
        else:
            missing["molecule"] = f"Molecule file {path} does not exist."
    elif overrides.molecule_name:
        try:
            canonical, _ = resolve_gas_molecule(overrides.molecule_name)
            inputs["molecule"] = {"value": canonical, "source": "builtin_g2"}
        except ValueError as exc:
            missing["molecule"] = str(exc)
    else:
        species = [
            item.get("normalized_species")
            for item in ((document.get("task_inputs") or {}).get("adsorbate_landscape") or {}).get(
                "adsorbate_species", []
            )
            if item.get("normalized_species")
        ]
        mentioned = f" The paper mentions: {', '.join(species)}." if species else ""
        missing["molecule"] = (
            "Choose the target gas explicitly (--molecule-name or --molecule); the paper's list order "
            f"is not a priority.{mentioned}"
        )

    if overrides.coverage_counts:
        counts = tuple(int(value) for value in overrides.coverage_counts)
        if min(counts) < 1:
            missing["coverage_counts"] = "Coverage counts must be positive integers."
        else:
            inputs["coverage_counts"] = {"value": list(counts), "source": "override"}
    else:
        binding = _binding(document, "adsorbate_landscape", "coverage_counts")
        if binding.get("status") == "auto" and binding.get("value"):
            inputs["coverage_counts"] = {"value": binding["value"], "source": "plan"}
        else:
            wording = binding.get("source_term")
            hint = f" Paper wording: {wording!r}." if wording else ""
            missing["coverage_counts"] = (
                "Coverage must be an explicit list of adsorbate counts (e.g. 1,2); qualitative "
                f"coverage cannot be converted automatically.{hint}"
            )

    if overrides.site_symbols:
        inputs["site_symbols"] = {"value": list(overrides.site_symbols), "source": "override"}
    else:
        binding = _binding(document, "adsorbate_landscape", "site_symbols")
        raw = binding.get("value") if binding.get("status") == "auto" else None
        symbols = [item.strip() for item in str(raw or "").split(",") if item.strip()]
        if symbols:
            inputs["site_symbols"] = {"value": symbols, "source": "plan"}
        else:
            missing["site_symbols"] = "Name the adsorption-site element(s), e.g. --site-symbols Sn."

    group_binding = _binding(document, "adsorbate_landscape", "site_group_size")
    group_size = group_binding.get("value") if group_binding.get("status") == "auto" else None
    inputs["site_group_size"] = {
        "value": int(group_size) if group_size else 1,
        "source": "plan" if group_size else "default",
    }
    return inputs


RESOLVED_REVIEW_PARAMETERS = {
    "slab_generation": {"facet", "bulk", "formula", "material_id", "surface_facet"},
    "adsorbate_landscape": {"surface", "molecule", "coverage_counts", "site_symbols", "site_group_size"},
}


def resolve_surface_execution(
    plan: ModelingPlanArtifact,
    run_root: str | Path,
    overrides: SurfaceExecutionOverrides | None = None,
) -> SurfaceExecutionResolution:
    """Decide tasks and inputs for a plan without writing anything."""
    overrides = overrides or SurfaceExecutionOverrides()
    root = Path(run_root)
    payload = json.loads((root / plan.path).read_text(encoding="utf-8"))
    missing: dict[str, str] = {}
    notes: list[ValidationIssue] = []
    document = _select_document(payload, overrides, missing)
    if document is None:
        return SurfaceExecutionResolution(None, [], {}, None, {}, missing, notes)

    executable = list(document.get("executable_tasks") or [])
    deferred = list(document.get("deferred_tasks") or [])
    requested = list(overrides.tasks) if overrides.tasks else executable
    tasks: list[str] = []
    skipped: dict[str, str] = {}
    slab_requested = False
    for task in requested:
        if task == "slab_generation":
            slab_requested = True
        elif task in STRUCTURE_ONLY_RUNNERS:
            tasks.append(task)
        else:
            skipped[task] = UNSUPPORTED_TASK_REASONS.get(task, "Not registered for structure-only execution.")
    for task in deferred:
        if task not in requested:
            skipped.setdefault(task, f"Deferred by PToModel. {UNSUPPORTED_TASK_REASONS.get(task, '')}".strip())
    if not tasks and not slab_requested:
        missing["tasks"] = "No registered structure-only task (slab_generation, adsorbate_landscape) is selected."

    slab = _resolve_slab(document, overrides, missing, notes) if (tasks or slab_requested) else None
    inputs: dict[str, dict[str, Any]] = {}
    if "adsorbate_landscape" in tasks:
        inputs.update(_resolve_adsorbate_inputs(document, overrides, missing))

    # Every checklist item of a selected task must be covered by the resolution.
    checklist_path = root / str(plan.metadata.get("checklist_path", ""))
    if plan.metadata.get("checklist_path") and checklist_path.is_file():
        checklist = json.loads(checklist_path.read_text(encoding="utf-8"))
        selected = set(tasks) | ({"slab_generation"} if slab is not None or slab_requested else set())
        for item in checklist.get("review_items", []):
            if item.get("document_id") not in (None, document.get("id")) or item.get("task") not in selected:
                continue
            parameter = str(item.get("parameter"))
            if parameter in RESOLVED_REVIEW_PARAMETERS.get(str(item.get("task")), set()):
                continue
            missing[f"{item['task']}.{parameter}"] = str(item.get("reason") or "Unresolved checklist item.")

    return SurfaceExecutionResolution(
        document_id=document.get("id"),
        tasks=tasks,
        skipped=skipped,
        slab=slab,
        inputs=inputs,
        missing=missing,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _next_stage_id(manifest: Any, root: Path) -> str:
    existing = {stage.stage_id for stage in manifest.stages}
    index = 1
    while True:
        stage_id = STAGE_BASE_ID if index == 1 else f"{STAGE_BASE_ID}_{index}"
        if stage_id not in existing and not (root / "stages" / stage_id).exists():
            return stage_id
        index += 1


def _slab_tags_and_fixed(slab: Atoms) -> tuple[np.ndarray, list[int]]:
    fixed: list[int] = []
    for constraint in slab.constraints:
        if isinstance(constraint, FixAtoms):
            fixed.extend(int(index) for index in constraint.get_indices())
    tags = np.ones(len(slab), dtype=int)
    tags[fixed] = 0
    return tags, sorted(set(fixed))


def _materialize_slab(
    slab_plan: dict[str, Any],
    stage_dir: Path,
    bulk_provider: BulkProvider | None,
) -> tuple[Path, dict[str, Any], list[ValidationIssue]]:
    """Write the slab into the stage directory and return its path and record."""
    slab_dir = stage_dir / "slab"
    slab_dir.mkdir(parents=True, exist_ok=True)
    issues: list[ValidationIssue] = []
    if slab_plan["mode"] == "file":
        source = Path(slab_plan["path"])
        target = slab_dir / source.name
        shutil.copyfile(source, target)
        record = {"mode": "file", "source": str(source), "facet": None, "facet_source": "slab_file"}
        return target, record, issues

    from .slab import SlabSettings, build_slab, load_bulk, write_slab_outputs

    if slab_plan["mode"] == "bulk":
        bulk = load_bulk(slab_plan["path"])
        formula = spacegroup = None
        source: dict[str, Any] = {"type": "file", "path": slab_plan["path"]}
    else:
        if bulk_provider is None:
            from .materials_project_slab import fetch_bulk_structure as bulk_provider
        bulk, metadata = bulk_provider(formula=slab_plan["formula"])
        formula, spacegroup = metadata.get("formula"), metadata.get("spacegroup_symbol")
        source = {"type": "materials_project", **metadata}
    try:
        result = build_slab(
            bulk,
            facet=slab_plan.get("facet"),
            settings=SlabSettings(),
            formula=formula,
            spacegroup_symbol=spacegroup,
        )
    except ValueError as exc:
        raise SurfaceExecutionBlocked({"surface_facet": str(exc)}) from exc
    manifest = write_slab_outputs(result, slab_dir, prefix="slab", extra_manifest={"source": source})
    if not result.validation.passed:
        codes = ", ".join(issue.code for issue in result.validation.errors)
        raise RuntimeError(f"Generated slab failed validation ({codes}).")
    issues.extend(result.validation.warnings)
    record = {
        "mode": slab_plan["mode"],
        "source": source,
        "facet": manifest["facet"]["miller_index"],
        "facet_source": slab_plan.get("facet_source"),
        "facet_selection": manifest["facet"]["selection_source"],
        "selected_termination": manifest["selected_termination"],
        "geometry": manifest["slab"],
    }
    return Path(manifest["files"]["surface_slab"]), record, issues


def _fragment_clashes(atoms: Atoms, fragments: np.ndarray) -> float | None:
    """Smallest d / (r_i + r_j) over atom pairs of different fragments (minimum image)."""
    if len(atoms) < 2:
        return None
    distances = atoms.get_all_distances(mic=True)
    radii = covalent_radii[atoms.numbers]
    ratio = distances / (radii[:, None] + radii[None, :])
    different = fragments[:, None] != fragments[None, :]
    if not different.any():
        return None
    return float(ratio[different].min())


def _run_adsorbate_landscape(
    slab_path: Path,
    molecule_path: Path,
    inputs: dict[str, dict[str, Any]],
    work_dir: Path,
    overrides: SurfaceExecutionOverrides,
    slab_atoms: Atoms,
    notes: list[ValidationIssue],
) -> list[Atoms]:
    from .adsorbate import AdsorbateLandscapeConfig, run_adsorbate_landscape

    present = set(slab_atoms.get_chemical_symbols())
    symbols = [symbol.strip().capitalize() for symbol in inputs["site_symbols"]["value"]]
    absent = [symbol for symbol in symbols if symbol not in present]
    if absent and inputs["site_symbols"]["source"] == "override":
        raise SurfaceExecutionBlocked(
            {"site_symbols": f"{', '.join(absent)} not present in the slab ({', '.join(sorted(present))})."}
        )
    if absent:
        notes.append(
            ValidationIssue(
                code="plan_site_symbols_filtered",
                message=f"Dropped plan site symbols absent from the slab: {', '.join(absent)}.",
            )
        )
        symbols = [symbol for symbol in symbols if symbol in present]
        if not symbols:
            raise SurfaceExecutionBlocked(
                {"site_symbols": f"No plan site symbol is present in the slab ({', '.join(sorted(present))})."}
            )
    inputs["site_symbols"]["value"] = symbols

    config_kwargs: dict[str, Any] = {
        "surface": slab_path,
        "molecule": molecule_path,
        "output_dir": work_dir,
        "site_symbols": ",".join(symbols),
        "coverage_counts": ",".join(str(value) for value in inputs["coverage_counts"]["value"]),
        "site_group_size": int(inputs["site_group_size"]["value"]),
        "seed": overrides.seed,
        "calculator": "none",
        "max_steps": 0,
    }
    if overrides.patterns:
        config_kwargs["patterns"] = ",".join(overrides.patterns)
    if overrides.random_repeats is not None:
        config_kwargs["random_repeats"] = int(overrides.random_repeats)
    # The runner prints mock-calculator energies; keep them in a log file so they
    # are never presented as results, and silence per-trial Optuna logging.
    import contextlib

    import optuna

    work_dir.mkdir(parents=True, exist_ok=True)
    previous_verbosity = optuna.logging.get_verbosity()
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    try:
        with (work_dir / "runner.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log):
            result = run_adsorbate_landscape(AdsorbateLandscapeConfig(**config_kwargs))
    finally:
        optuna.logging.set_verbosity(previous_verbosity)

    rows: dict[str, dict[str, str]] = {}
    with Path(result.csv_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows[Path(row["structure_path"]).name] = row
    frames: list[Atoms] = []
    for path in result.structure_paths:
        frame = read(path)
        row = rows.get(Path(path).name, {})
        frame.info.update(
            {
                "task": "adsorbate_landscape",
                "role": "adsorbate_on_slab",
                "source_file": Path(path).name,
                "pattern": row.get("pattern", ""),
                "adsorbate_count": int(row.get("adsorbate_count") or 0),
                "coverage": float(row.get("coverage") or 0.0),
            }
        )
        frames.append(frame)
    return frames


STRUCTURE_ONLY_RUNNERS: dict[str, Callable[..., list[Atoms]]] = {
    "adsorbate_landscape": _run_adsorbate_landscape,
}


def execute_surface_plan(
    plan: ModelingPlanArtifact,
    run_root: str | Path,
    overrides: SurfaceExecutionOverrides | None = None,
    *,
    bulk_provider: BulkProvider | None = None,
) -> StructureSetArtifact:
    """Generate and register structures for a reviewed plan (geometry only)."""
    overrides = overrides or SurfaceExecutionOverrides()
    root = Path(run_root)
    resolution = resolve_surface_execution(plan, root, overrides)
    if resolution.missing:
        raise SurfaceExecutionBlocked(resolution.missing)

    manifest = load_manifest(root)
    stage_id = _next_stage_id(manifest, root)
    stage_dir = root / "stages" / stage_id
    stage_dir.mkdir(parents=True)
    started_at = datetime.now(timezone.utc)
    warnings: list[ValidationIssue] = []
    checks: list[ValidationIssue] = list(resolution.notes)
    try:
        slab_path, slab_record, slab_issues = _materialize_slab(resolution.slab or {}, stage_dir, bulk_provider)
        warnings.extend(slab_issues)
        slab_atoms = read(slab_path)
        slab_tags, fixed = _slab_tags_and_fixed(slab_atoms)
        if not fixed:
            checks.append(
                ValidationIssue(code="slab_without_fixed_atoms", message="The slab has no fixed atoms.")
            )
        clean = slab_atoms.copy()
        clean.set_tags(slab_tags)
        clean.info.update(
            {
                "task": "slab_generation" if slab_record["mode"] != "file" else "reviewed_slab",
                "role": "clean_slab",
                "source_file": slab_path.name,
            }
        )
        frames: list[Atoms] = [clean]
        molecule_record: dict[str, Any] | None = None

        for task in resolution.tasks:
            if task == "adsorbate_landscape":
                inputs_dir = stage_dir / "inputs"
                inputs_dir.mkdir(exist_ok=True)
                molecule_input = resolution.inputs["molecule"]
                if molecule_input["source"] == "builtin_g2":
                    _, molecule = resolve_gas_molecule(molecule_input["value"])
                    molecule_path = inputs_dir / f"{molecule_input['value']}.xyz"
                    write(molecule_path, molecule)
                else:
                    source_path = Path(molecule_input["value"])
                    molecule_path = inputs_dir / source_path.name
                    shutil.copyfile(source_path, molecule_path)
                    molecule = read(molecule_path)
                molecule_record = {
                    "name": molecule_input["value"],
                    "source": molecule_input["source"],
                    "formula": molecule.get_chemical_formula(),
                    "path": _relative(molecule_path, root),
                }
                task_frames = _run_adsorbate_landscape(
                    slab_path,
                    molecule_path,
                    resolution.inputs,
                    stage_dir / task,
                    overrides,
                    slab_atoms,
                    checks,
                )
                n_slab, n_mol = len(slab_atoms), len(molecule)
                for frame in task_frames:
                    count = (len(frame) - n_slab) // max(n_mol, 1)
                    consistent = (
                        len(frame) == n_slab + count * n_mol
                        and frame.get_chemical_symbols()[:n_slab] == slab_atoms.get_chemical_symbols()
                    )
                    if not consistent:
                        raise RuntimeError("Adsorbate structure does not start with the slab atoms in order.")
                    tags = np.concatenate([slab_tags, np.full(len(frame) - n_slab, 2, dtype=int)])
                    frame.set_tags(tags)
                    if fixed:
                        frame.set_constraint(FixAtoms(indices=fixed))
                    fragments = np.concatenate(
                        [np.zeros(n_slab, dtype=int), 1 + np.arange(len(frame) - n_slab) // max(n_mol, 1)]
                    )
                    ratio = _fragment_clashes(frame, fragments)
                    # -1 marks "no inter-fragment pair"; 0 means coincident atoms.
                    frame.info["min_contact_ratio"] = round(ratio, 4) if ratio is not None else -1.0
                    frames.append(frame)
            else:
                # A task registered in STRUCTURE_ONLY_RUNNERS without an execution
                # branch must fail loudly instead of being skipped silently.
                raise RuntimeError(f"No structure-only execution branch for task {task!r}.")

        unique: list[Atoms] = []
        duplicates = 0
        excluded: list[str] = []
        for frame in frames:
            if frame.info.get("role") == "adsorbate_on_slab" and 0.0 <= frame.info["min_contact_ratio"] < CLASH_FRACTION:
                excluded.append(str(frame.info.get("source_file")))
                continue
            if any(
                len(kept) == len(frame)
                and kept.get_chemical_symbols() == frame.get_chemical_symbols()
                and np.allclose(kept.positions, frame.positions, atol=1e-6)
                for kept in unique
            ):
                duplicates += 1
                continue
            unique.append(frame)
        for frame_id, frame in enumerate(unique):
            frame.info["frame_id"] = frame_id
        if duplicates:
            checks.append(
                ValidationIssue(
                    code="duplicate_structures_removed",
                    message=f"Removed {duplicates} structure(s) identical to an earlier one.",
                )
            )
        if excluded:
            warnings.append(
                ValidationIssue(
                    code="overlapping_structures_excluded",
                    message=(
                        f"Excluded {len(excluded)} structure(s) with interatomic overlap "
                        f"(< {CLASH_FRACTION} x covalent-radius sum): {', '.join(excluded)}."
                    ),
                )
            )
        if resolution.tasks and not any(frame.info.get("role") == "adsorbate_on_slab" for frame in unique):
            raise RuntimeError("Every generated adsorbate structure overlapped with the slab.")

        structures_path = stage_dir / "structures.extxyz"
        write(structures_path, unique, format="extxyz")
        structure_sha = _sha256(structures_path)
        report_path = stage_dir / "execution_report.json"
        validation = ValidationReport(errors=[], warnings=warnings, checks=checks)
        roles: dict[str, int] = {}
        for frame in unique:
            roles[str(frame.info.get("role"))] = roles.get(str(frame.info.get("role")), 0) + 1
        report = {
            "schema_version": "1.0",
            "mode": "structure-only",
            "calculator": "none",
            "scientific_calculation_started": False,
            "energies_available": False,
            "note": (
                "Unrelaxed geometric candidates. Placements were chosen with a mock calculator; "
                "no energies are reported."
            ),
            "plan": {"artifact_id": plan.artifact_id, "path": plan.path.as_posix()},
            "resolution": resolution.summary(),
            "overrides": overrides.summary(),
            "slab": slab_record,
            "molecule": molecule_record,
            "structures": {
                "path": _relative(structures_path, root),
                "sha256": structure_sha,
                "count": len(unique),
                "roles": roles,
                "duplicates_removed": duplicates,
                "excluded_overlapping": excluded,
            },
            "validation": validation.model_dump(),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output_files = [
            {"path": _relative(path, root), "sha256": _sha256(path)}
            for path in sorted(stage_dir.rglob("*"))
            if path.is_file()
        ]
    except SurfaceExecutionBlocked:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    except Exception as exc:
        manifest.append_stage(
            StageRecord(
                stage_id=stage_id,
                adapter=ADAPTER,
                execution_state=ExecutionState.FAILED,
                input_artifact_ids=[plan.artifact_id],
                validation=ValidationReport(
                    errors=[ValidationIssue(code="surface_execution_failed", message=str(exc))]
                ),
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                metadata={"mode": "structure-only", "tasks": list(resolution.tasks)},
            )
        )
        save_manifest(root, manifest)
        raise

    artifact = StructureSetArtifact(
        artifact_id=f"{manifest.run_id}:structure-set:{stage_id}",
        path=_relative(structures_path, root),
        sha256=structure_sha,
        producer=ADAPTER,
        parent_ids=[plan.artifact_id],
        execution_state=ExecutionState.SUCCEEDED,
        evidence_level=EvidenceLevel.HEURISTIC,
        validation_status=ValidationStatus.PASSED if not warnings else ValidationStatus.NEEDS_REVIEW,
        metadata={
            "mode": "structure-only",
            "structure_count": len(unique),
            "structure_inventory": [
                {"path": _relative(structures_path, root), "sha256": structure_sha, "frames": len(unique)}
            ],
            "roles": roles,
            "source_tasks": ["slab_generation" if slab_record["mode"] != "file" else "reviewed_slab"]
            + list(resolution.tasks),
            "skipped_tasks": dict(resolution.skipped),
            "calculator": "none",
            "scientific_calculation_started": False,
            "energies_available": False,
            "slab_source": slab_record["mode"],
            "facet": slab_record.get("facet"),
            "facet_source": slab_record.get("facet_source"),
            "molecule": molecule_record,
            "coverage_counts": (resolution.inputs.get("coverage_counts") or {}).get("value"),
            "site_symbols": (resolution.inputs.get("site_symbols") or {}).get("value"),
            "execution_report": _relative(report_path, root),
            "output_files": output_files,
        },
        provenance=Provenance(
            source=plan.path.as_posix(),
            software=ADAPTER,
            parameters=overrides.summary(),
        ),
    )
    manifest.register_artifact(artifact)
    manifest.append_stage(
        StageRecord(
            stage_id=stage_id,
            adapter=ADAPTER,
            execution_state=ExecutionState.SUCCEEDED,
            input_artifact_ids=[plan.artifact_id],
            output_artifact_ids=[artifact.artifact_id],
            validation=validation,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            metadata={
                "mode": "structure-only",
                "tasks": list(resolution.tasks),
                "skipped_tasks": dict(resolution.skipped),
            },
        )
    )
    save_manifest(root, manifest)
    return artifact
