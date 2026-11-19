"""Structure-only execution of reviewed surface-modeling plans.

``build_surface_candidates`` only prepares commands. This executor turns a
:class:`ModelingPlanArtifact` into real, ASE-readable structures::

    base surface: crystal slab (reviewed slab file, or cut from a bulk crystal)
                  or an amorphous slab (``amorphous_slab`` without ``ald_overlayer``)
    -> registered surface tasks, in the order
       vacancy_landscape -> ald_overlayer -> sam_functionalization
       -> surface_cluster_builder -> adsorbate_landscape
    -> one ``structures.extxyz`` registered as a ``StructureSetArtifact``

By default every task is built on the same base surface. With ``chain=True``
each task is built on the first structure of the previous task in that order,
e.g. gas adsorption on the SAM-functionalized slab, or a Pt cluster on the
O-vacancy slab. Every frame records the surface it was built on.

No energy model is run: task runners use ``calculator="none"`` and
``max_steps=0``, so every structure is an unrelaxed geometric candidate
(evidence level ``heuristic``). Mock energies used internally for placement are
never written into the structure set.

Inputs that a paper cannot determine — a slab or confirmed exposed facet, the
gas or SAM molecule, an amorphous bulk cell, integer counts — must come from
explicit overrides. Numeric choices (counts, film thickness, cluster size) may
instead take documented defaults when ``accept_defaults=True``; structure files
and the SAM binding mode never do. When an input or a checklist item of a
selected task stays unresolved, :class:`SurfaceExecutionBlocked` is raised and
the run manifest is untouched.
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
        "Termination states (hydroxylated, reduced, O-terminated) are not built; molecular SAMs "
        "are executed as sam_functionalization."
    ),
    "single_atom_site": "Single-atom site construction is not implemented.",
    "doped_surface": "Dopant substitution is not implemented in structure-only mode.",
}

# Order of the surface-modifying tasks; with chain=True each builds on the previous one.
TASK_ORDER = (
    "vacancy_landscape",
    "ald_overlayer",
    "sam_functionalization",
    "surface_cluster_builder",
    "adsorbate_landscape",
)
# Placement tasks whose overlapping candidates are discarded rather than reported.
PLACEMENT_ROLES = {"adsorbate_on_slab", "cluster_on_slab"}

# Values used only with accept_defaults=True; every use is recorded in the report.
EXECUTION_DEFAULTS: dict[str, Any] = {
    "coverage_counts": (1, 2),
    "vacancy_counts": (1, 2),
    "cluster_atoms": 13,
    "sam_counts": (1, 2),
    "ald_coverage": "full",
    "ald_thickness": 5.0,
    "island_atoms": 30,
    "amorphous_thickness": 10.0,
}
VACANCY_SAMPLES = 3  # configurations per vacancy count (sampling setting, not a default)
VACANCY_SURFACE_DEPTH_A = 2.5  # O atoms within this depth of the top atom can be removed
CLUSTER_GAP_A = 2.5  # gap between the slab top and the cluster bottom
MIN_HEADROOM_A = 8.0  # vacuum kept above an added cluster
CLUSTER_STRUCTURES = ("fcc", "hcp", "bcc")

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
    # Build each task on the previous task's first structure (see TASK_ORDER).
    chain: bool = False
    # Fill unresolved numeric choices from EXECUTION_DEFAULTS (recorded in the report).
    accept_defaults: bool = False
    # vacancy_landscape
    vacancy_counts: tuple[int, ...] | None = None
    vacancy_samples: int | None = None
    # surface_cluster_builder
    cluster_element: str | None = None
    cluster_atoms: int | None = None
    cluster_structures: tuple[str, ...] | None = None
    # sam_functionalization
    sam_molecule: Path | None = None
    binding_mode: str | None = None
    sam_counts: tuple[int, ...] | None = None
    anchor_kind: str | None = None
    # ald_overlayer and amorphous_slab
    amorphous: Path | None = None
    ald_coverage: str | None = None
    ald_thickness: float | None = None
    island_atoms: int | None = None
    amorphous_thickness: float | None = None

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
    defaults_used: list[str] = field(default_factory=list)
    # True when the amorphous slab, not a crystal slab, is the base surface.
    amorphous_base: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "tasks": list(self.tasks),
            "skipped_tasks": dict(self.skipped),
            "slab": self.slab,
            "amorphous_base": self.amorphous_base,
            "inputs": self.inputs,
            "defaults_used": list(self.defaults_used),
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
    defaults_used: list[str] | None = None,
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
        elif overrides.accept_defaults:
            inputs["coverage_counts"] = {"value": list(EXECUTION_DEFAULTS["coverage_counts"]), "source": "default"}
            if defaults_used is not None:
                defaults_used.append("coverage_counts")
        else:
            wording = binding.get("source_term")
            hint = f" Paper wording: {wording!r}." if wording else ""
            missing["coverage_counts"] = (
                "Coverage must be an explicit list of adsorbate counts (e.g. 1,2); qualitative "
                f"coverage cannot be converted automatically; use --coverage-counts or --accept-defaults.{hint}"
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


def _pick(
    key: str,
    *,
    override: Any,
    plan: Any,
    overrides: SurfaceExecutionOverrides,
    missing: dict[str, str],
    defaults_used: list[str],
    reason: str,
    default_allowed: bool = True,
) -> dict[str, Any] | None:
    """Override, then plan value, then (with accept_defaults) the documented default."""
    if override is not None:
        return {"value": override, "source": "override"}
    if plan is not None:
        return {"value": plan, "source": "plan"}
    if default_allowed and overrides.accept_defaults and key in EXECUTION_DEFAULTS:
        defaults_used.append(key)
        value = EXECUTION_DEFAULTS[key]
        return {"value": list(value) if isinstance(value, tuple) else value, "source": "default"}
    hint = " or --accept-defaults" if default_allowed and key in EXECUTION_DEFAULTS else ""
    missing[key] = f"{reason} Use --{key.replace('_', '-')}{hint}."
    return None


def _auto(document: dict[str, Any], task: str, parameter: str) -> Any:
    binding = _binding(document, task, parameter)
    return binding.get("value") if binding.get("status") == "auto" else None


def _plan_ints(value: Any) -> list[int] | None:
    if value in (None, ""):
        return None
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    try:
        counts = [int(item) for item in items if str(item).strip()]
    except ValueError:
        return None
    return counts or None


def _positive_ints(key: str, values: tuple[int, ...] | None, missing: dict[str, str]) -> list[int] | None:
    if values is None:
        return None
    counts = [int(value) for value in values]
    if not counts or min(counts) < 1:
        missing[key] = "Counts must be positive integers, e.g. 1,2."
        return None
    return sorted(set(counts))


def _existing_file(key: str, path: Path | None, missing: dict[str, str]) -> str | None:
    if path is None:
        return None
    if not Path(path).is_file():
        missing[key] = f"File {path} does not exist."
        return None
    return str(path)


def _resolve_vacancy_inputs(
    document: dict[str, Any], overrides: SurfaceExecutionOverrides, missing: dict[str, str], defaults_used: list[str]
) -> dict[str, Any]:
    plan_counts = _plan_ints(_auto(document, "vacancy_landscape", "vacancy_counts"))
    counts = _pick(
        "vacancy_counts",
        override=_positive_ints("vacancy_counts", overrides.vacancy_counts, missing),
        plan=plan_counts,
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason="The paper gives no explicit number of O vacancies per cell.",
    )
    samples = overrides.vacancy_samples or VACANCY_SAMPLES
    return {
        "vacancy_counts": counts,
        "samples": {"value": int(samples), "source": "override" if overrides.vacancy_samples else "setting"},
        "element": {"value": "O", "source": "builder"},
    }


def _resolve_cluster_inputs(
    document: dict[str, Any], overrides: SurfaceExecutionOverrides, missing: dict[str, str], defaults_used: list[str]
) -> dict[str, Any]:
    from ase.data import atomic_numbers, reference_states

    element = _pick(
        "cluster_element",
        override=overrides.cluster_element,
        plan=_auto(document, "surface_cluster_builder", "cluster_element"),
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason="The paper names no elemental metal for the cluster.",
        default_allowed=False,
    )
    plan_atoms = _auto(document, "surface_cluster_builder", "cluster_atoms")
    atoms = _pick(
        "cluster_atoms",
        override=overrides.cluster_atoms,
        plan=int(plan_atoms) if plan_atoms else None,
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason="The paper gives no cluster size in atoms.",
    )
    if atoms is not None and int(atoms["value"]) < 2:
        missing["cluster_atoms"] = "A cluster needs at least 2 atoms."
    structures: dict[str, Any] | None = None
    plan_structures = _auto(document, "surface_cluster_builder", "cluster_structures")
    if overrides.cluster_structures:
        structures = {"value": list(overrides.cluster_structures), "source": "override"}
    elif plan_structures:
        structures = {"value": list(plan_structures), "source": "plan"}
    elif element is not None:
        # The element's ground-state lattice (ASE reference data), not a guess.
        state = reference_states[atomic_numbers.get(str(element["value"]).capitalize(), 0)] or {}
        if state.get("symmetry") in CLUSTER_STRUCTURES:
            structures = {"value": [state["symmetry"]], "source": "element_reference_state"}
        else:
            missing["cluster_structures"] = (
                f"{element['value']} has no fcc/hcp/bcc ground state in the reference data; "
                "use --cluster-structures fcc|hcp|bcc."
            )
    if structures is not None:
        unknown = [item for item in structures["value"] if item not in CLUSTER_STRUCTURES]
        if unknown:
            missing["cluster_structures"] = f"Unknown cluster structure(s) {unknown}; use fcc, hcp or bcc."
    return {"cluster_element": element, "cluster_atoms": atoms, "cluster_structures": structures}


def _resolve_sam_inputs(
    document: dict[str, Any], overrides: SurfaceExecutionOverrides, missing: dict[str, str], defaults_used: list[str]
) -> dict[str, Any]:
    task_inputs = (document.get("task_inputs") or {}).get("sam_functionalization") or {}
    named = task_inputs.get("sam_molecules") or task_inputs.get("sam_terms") or []
    mentioned = f" The paper names: {', '.join(named[:4])}." if named else ""
    molecule = _existing_file("sam_molecule", overrides.sam_molecule, missing)
    if molecule is None and "sam_molecule" not in missing:
        missing["sam_molecule"] = f"Provide a 3D structure file of the SAM molecule (--sam-molecule).{mentioned}"
    binding = _pick(
        "binding_mode",
        override=overrides.binding_mode,
        plan=_auto(document, "sam_functionalization", "binding_mode"),
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason=(
            "The paper does not state how the anchor binds (phosphonic: monodentate|bidentate|tridentate; "
            "carboxylic: monodentate|bidentate; thiol: top|bridge|hollow|fcc|hcp)."
        ),
        default_allowed=False,
    )
    counts = _pick(
        "sam_counts",
        override=_positive_ints("sam_counts", overrides.sam_counts, missing),
        plan=None,
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason="Integer SAM molecules per cell cannot be derived from qualitative coverage.",
    )
    anchor = overrides.anchor_kind or _auto(document, "sam_functionalization", "anchor_kind")
    return {
        "sam_molecule": {"value": molecule, "source": "override_file"} if molecule else None,
        "binding_mode": binding,
        "sam_counts": counts,
        "anchor_kind": (
            {"value": anchor, "source": "override" if overrides.anchor_kind else "plan"}
            if anchor
            else {"value": None, "source": "detected_from_molecule"}
        ),
    }


def _resolve_amorphous_file(
    task: str, document: dict[str, Any], overrides: SurfaceExecutionOverrides, missing: dict[str, str]
) -> dict[str, Any] | None:
    path = _existing_file("amorphous", overrides.amorphous, missing)
    if path is None and "amorphous" not in missing:
        inputs = (document.get("task_inputs") or {}).get(task) or {}
        formula = inputs.get("overlayer_formula") or inputs.get("amorphous_formula")
        what = f" of {formula}" if formula else ""
        missing["amorphous"] = f"Provide a periodic amorphous bulk cell{what} (--amorphous)."
    return {"value": path, "source": "override_file"} if path else None


def _resolve_ald_inputs(
    document: dict[str, Any], overrides: SurfaceExecutionOverrides, missing: dict[str, str], defaults_used: list[str]
) -> dict[str, Any]:
    amorphous = _resolve_amorphous_file("ald_overlayer", document, overrides, missing)
    coverage = _pick(
        "ald_coverage",
        override=overrides.ald_coverage,
        plan=_auto(document, "ald_overlayer", "coverage"),
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason="The paper does not say whether the overlayer is a continuous film (full) or islands (partial).",
    )
    if coverage is not None and coverage["value"] not in ("full", "partial"):
        missing["ald_coverage"] = "Use --ald-coverage full or partial."
    size: dict[str, Any] | None = None
    if coverage is not None and coverage["value"] == "partial":
        size = _pick(
            "island_atoms",
            override=overrides.island_atoms,
            plan=None,
            overrides=overrides,
            missing=missing,
            defaults_used=defaults_used,
            reason="Partial coverage needs the island size in atoms.",
        )
    elif coverage is not None:
        size = _pick(
            "ald_thickness",
            override=overrides.ald_thickness,
            plan=_auto(document, "ald_overlayer", "thickness"),
            overrides=overrides,
            missing=missing,
            defaults_used=defaults_used,
            reason="A continuous film needs a model thickness in angstrom.",
        )
    task_inputs = (document.get("task_inputs") or {}).get("ald_overlayer") or {}
    return {
        "amorphous": amorphous,
        "ald_coverage": coverage,
        "island_atoms" if coverage and coverage["value"] == "partial" else "ald_thickness": size,
        "overlayer_formula": {"value": task_inputs.get("overlayer_formula"), "source": "plan"},
    }


def _resolve_amorphous_slab_inputs(
    document: dict[str, Any], overrides: SurfaceExecutionOverrides, missing: dict[str, str], defaults_used: list[str]
) -> dict[str, Any]:
    amorphous = _resolve_amorphous_file("amorphous_slab", document, overrides, missing)
    thickness = _pick(
        "amorphous_thickness",
        override=overrides.amorphous_thickness,
        plan=None,
        overrides=overrides,
        missing=missing,
        defaults_used=defaults_used,
        reason="The amorphous slab thickness is a modeling choice (a paper film thickness is not the model thickness).",
    )
    task_inputs = (document.get("task_inputs") or {}).get("amorphous_slab") or {}
    return {
        "amorphous": amorphous,
        "amorphous_thickness": thickness,
        "amorphous_formula": {"value": task_inputs.get("amorphous_formula"), "source": "plan"},
    }


TASK_INPUT_RESOLVERS: dict[str, Callable[..., dict[str, Any]]] = {
    "vacancy_landscape": _resolve_vacancy_inputs,
    "surface_cluster_builder": _resolve_cluster_inputs,
    "sam_functionalization": _resolve_sam_inputs,
    "ald_overlayer": _resolve_ald_inputs,
    "amorphous_slab": _resolve_amorphous_slab_inputs,
}

RESOLVED_REVIEW_PARAMETERS = {
    "slab_generation": {"facet", "bulk", "formula", "material_id", "surface_facet"},
    "adsorbate_landscape": {"surface", "molecule", "coverage_counts", "site_symbols", "site_group_size"},
    "vacancy_landscape": {"input", "vacancy_counts"},
    "surface_cluster_builder": {
        "surface", "surface_formula", "surface_mp_id", "surface_facet", "cluster_element", "cluster_bulk_file",
        "cluster_from_mp", "cluster_mp_id", "cluster_structures", "cluster_atoms", "cluster_layers", "cluster_radius",
    },
    "sam_functionalization": {"surface", "bulk", "facet", "molecule", "binding_mode", "counts", "anchor_kind"},
    "ald_overlayer": {"surface", "bulk", "facet", "amorphous", "coverage", "thickness", "island_atoms"},
    "amorphous_slab": {"amorphous", "thickness"},
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

    # An amorphous material is its own base surface; an ALD overlayer needs the crystal slab.
    amorphous_base = "amorphous_slab" in tasks and "ald_overlayer" not in tasks
    explicit_slab = bool(overrides.tasks) and "slab_generation" in (overrides.tasks or ())
    if amorphous_base and slab_requested and not explicit_slab:
        skipped["slab_generation"] = (
            "The base surface is the amorphous slab; list slab_generation in --tasks to also cut a crystal slab."
        )
        slab_requested = False
    if not tasks and not slab_requested:
        registered = ", ".join(["slab_generation", *sorted(STRUCTURE_ONLY_RUNNERS)])
        missing["tasks"] = f"No registered structure-only task is selected (registered: {registered})."
    crystal_needed = slab_requested or "ald_overlayer" in tasks or (bool(tasks) and not amorphous_base)

    slab = _resolve_slab(document, overrides, missing, notes) if crystal_needed else None
    inputs: dict[str, dict[str, Any]] = {}
    defaults_used: list[str] = []
    if "adsorbate_landscape" in tasks:
        inputs.update(_resolve_adsorbate_inputs(document, overrides, missing, defaults_used))
    for task in tasks:
        resolver = TASK_INPUT_RESOLVERS.get(task)
        if resolver is not None:
            inputs[task] = resolver(document, overrides, missing, defaults_used)
    if defaults_used:
        notes.append(
            ValidationIssue(
                code="defaults_used",
                message=f"--accept-defaults filled: {', '.join(defaults_used)} (values in resolution.inputs).",
            )
        )
    if overrides.chain:
        order = [task for task in TASK_ORDER if task in tasks]
        base = "amorphous slab" if amorphous_base else "clean slab"
        notes.append(
            ValidationIssue(
                code="chained_tasks",
                message=f"Chained on the {base}: {' -> '.join(order) or 'no modifying task'}; each step uses the "
                "first structure of the previous step.",
            )
        )

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
        defaults_used=defaults_used,
        amorphous_base=amorphous_base,
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
    # A facet typed by the user refers to the user's bulk cell; paper and registry
    # facets (and any Materials Project cell) use the conventional standard setting.
    miller_basis = "auto" if slab_plan.get("facet_source") == "override" and slab_plan["mode"] == "bulk" else "conventional"
    try:
        result = build_slab(
            bulk,
            facet=slab_plan.get("facet"),
            settings=SlabSettings(),
            formula=formula,
            spacegroup_symbol=spacegroup,
            miller_basis=miller_basis,
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
        "miller_basis": manifest["facet"]["miller_basis"],
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


@dataclass
class _Surface:
    """A surface handed to a task runner: the base surface or the previous chain step."""

    atoms: Atoms
    path: Path
    label: str


@dataclass
class _RunContext:
    resolution: SurfaceExecutionResolution
    overrides: SurfaceExecutionOverrides
    root: Path
    stage_dir: Path
    checks: list[ValidationIssue]
    warnings: list[ValidationIssue]
    records: dict[str, Any] = field(default_factory=dict)


def _fixed_mask(atoms: Atoms) -> np.ndarray:
    mask = np.zeros(len(atoms), dtype=bool)
    for constraint in atoms.constraints:
        if isinstance(constraint, FixAtoms):
            mask[constraint.get_indices()] = True
    return mask


def _surface_tags(atoms: Atoms) -> np.ndarray:
    """Existing tags, or 0 = fixed / 1 = free when the surface carries none."""
    tags = atoms.get_tags()
    if tags.any():
        return tags.copy()
    return np.where(_fixed_mask(atoms), 0, 1)


def _write_surface(atoms: Atoms, directory: Path, label: str) -> _Surface:
    """Write a surface as extxyz (keeps FixAtoms and tags) for the next runner."""
    directory.mkdir(parents=True, exist_ok=True)
    surface = atoms.copy()
    surface.calc = None
    path = directory / f"{label.replace(':', '_')}.extxyz"
    write(path, surface, format="extxyz")
    return _Surface(atoms=surface, path=path, label=label)


def _stage_input(ctx: _RunContext, key: str, source: str | Path, prefix: str) -> Path:
    """Copy a reviewed input file into the stage once, so the run is self-contained."""
    if key not in ctx.records:
        directory = ctx.stage_dir / "inputs"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{prefix}{Path(source).name}"
        shutil.copyfile(source, target)
        ctx.records[key] = target
    return ctx.records[key]


def _formula_mismatch(atoms: Atoms, formula: str | None) -> str | None:
    """Reduced-formula mismatch between a structure file and the paper's formula, if both parse."""
    if not formula:
        return None
    try:
        from pymatgen.core import Composition

        expected = Composition(formula).reduced_formula
    except Exception:  # paper wording such as SnOx does not parse
        return None
    actual = Composition(atoms.get_chemical_formula()).reduced_formula
    return None if actual == expected else f"file composition {actual} differs from the paper's {expected}"


def _ensure_headroom(atoms: Atoms, headroom: float = MIN_HEADROOM_A) -> bool:
    """Lengthen c so at least ``headroom`` of vacuum stays above the topmost atom."""
    cell = atoms.cell.array.copy()
    c_z = float(cell[2, 2])
    needed = float(atoms.positions[:, 2].max()) + headroom
    if c_z <= 0 or c_z >= needed:
        return False
    cell[2] *= needed / c_z
    atoms.set_cell(cell, scale_atoms=False)
    return True


def _materialize_gas_molecule(ctx: _RunContext) -> tuple[Path, Atoms]:
    if "gas_molecule_path" not in ctx.records:
        molecule_input = ctx.resolution.inputs["molecule"]
        inputs_dir = ctx.stage_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        if molecule_input["source"] == "builtin_g2":
            _, molecule = resolve_gas_molecule(molecule_input["value"])
            molecule_path = inputs_dir / f"{molecule_input['value']}.xyz"
            write(molecule_path, molecule)
        else:
            source_path = Path(molecule_input["value"])
            molecule_path = inputs_dir / source_path.name
            shutil.copyfile(source_path, molecule_path)
            molecule = read(molecule_path)
        ctx.records["gas_molecule_path"] = molecule_path
        ctx.records["molecule"] = {
            "name": molecule_input["value"],
            "source": molecule_input["source"],
            "formula": molecule.get_chemical_formula(),
            "path": _relative(molecule_path, ctx.root),
        }
    path = ctx.records["gas_molecule_path"]
    return path, read(path)


def _run_adsorbate_landscape(ctx: _RunContext, surface: _Surface, work_dir: Path) -> list[Atoms]:
    from .adsorbate import AdsorbateLandscapeConfig, run_adsorbate_landscape

    inputs = ctx.resolution.inputs
    overrides = ctx.overrides
    molecule_path, molecule = _materialize_gas_molecule(ctx)
    slab_atoms = surface.atoms
    present = set(slab_atoms.get_chemical_symbols())
    symbols = [symbol.strip().capitalize() for symbol in inputs["site_symbols"]["value"]]
    absent = [symbol for symbol in symbols if symbol not in present]
    if absent and inputs["site_symbols"]["source"] == "override":
        raise SurfaceExecutionBlocked(
            {"site_symbols": f"{', '.join(absent)} not present in the slab ({', '.join(sorted(present))})."}
        )
    if absent:
        ctx.checks.append(
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
        "surface": surface.path,
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
    n_slab, n_mol = len(slab_atoms), len(molecule)
    slab_tags, fixed = _surface_tags(slab_atoms), _fixed_mask(slab_atoms)
    frames: list[Atoms] = []
    extended = 0
    for path in result.structure_paths:
        frame = read(path)
        row = rows.get(Path(path).name, {})
        count = (len(frame) - n_slab) // max(n_mol, 1)
        consistent = (
            len(frame) == n_slab + count * n_mol
            and frame.get_chemical_symbols()[:n_slab] == slab_atoms.get_chemical_symbols()
        )
        if not consistent:
            raise RuntimeError("Adsorbate structure does not start with the slab atoms in order.")
        frame.set_tags(np.concatenate([slab_tags, np.full(len(frame) - n_slab, 2, dtype=int)]))
        frame.set_constraint()
        if fixed.any():
            frame.set_constraint(FixAtoms(mask=np.concatenate([fixed, np.zeros(len(frame) - n_slab, dtype=bool)])))
        fragments = np.concatenate(
            [np.zeros(n_slab, dtype=int), 1 + np.arange(len(frame) - n_slab) // max(n_mol, 1)]
        )
        ratio = _fragment_clashes(frame, fragments)
        frame.info.update(
            {
                "task": "adsorbate_landscape",
                "role": "adsorbate_on_slab",
                "source_file": Path(path).name,
                "pattern": row.get("pattern", ""),
                "adsorbate_count": int(row.get("adsorbate_count") or 0),
                "coverage": float(row.get("coverage") or 0.0),
                # -1 marks "no inter-fragment pair"; 0 means coincident atoms.
                "min_contact_ratio": round(ratio, 4) if ratio is not None else -1.0,
            }
        )
        # Molecules on a cluster or SAM can eat into the vacuum; keep MIN_HEADROOM_A above them.
        extended += _ensure_headroom(frame)
        frames.append(frame)
    if extended:
        ctx.checks.append(
            ValidationIssue(
                code="cell_extended_for_adsorbates",
                message=f"c was lengthened in {extended} adsorbate structure(s) to keep {MIN_HEADROOM_A} A of vacuum.",
            )
        )
    return frames


def _run_vacancy_landscape(ctx: _RunContext, surface: _Surface, work_dir: Path) -> list[Atoms]:
    import random

    from .vacancy import sample_vacancy_sets

    inputs = ctx.resolution.inputs["vacancy_landscape"]
    counts = sorted({int(value) for value in inputs["vacancy_counts"]["value"]})
    samples = int(inputs["samples"]["value"])
    atoms = surface.atoms.copy()
    fixed, tags = _fixed_mask(atoms), _surface_tags(atoms)
    atoms.set_constraint()
    top = float(atoms.positions[:, 2].max())
    candidates = [
        index
        for index, symbol in enumerate(atoms.get_chemical_symbols())
        if symbol == "O" and not fixed[index] and atoms.positions[index, 2] >= top - VACANCY_SURFACE_DEPTH_A
    ]
    if not candidates:
        raise SurfaceExecutionBlocked(
            {
                "vacancy_landscape": (
                    f"No free O atom within {VACANCY_SURFACE_DEPTH_A} A of the top of {surface.label}; "
                    "O vacancies need an oxide surface."
                )
            }
        )
    too_many = [count for count in counts if count > len(candidates)]
    if too_many:
        raise SurfaceExecutionBlocked(
            {"vacancy_counts": f"{too_many} exceed the {len(candidates)} removable surface O atoms of {surface.label}."}
        )
    rng = random.Random(ctx.overrides.seed)
    frames: list[Atoms] = []
    removed_sets: list[dict[str, Any]] = []
    for count in counts:
        for sample, removed in enumerate(sample_vacancy_sets(candidates, count, samples, rng)):
            keep = np.ones(len(atoms), dtype=bool)
            keep[list(removed)] = False
            frame = atoms[keep]
            if fixed[keep].any():
                frame.set_constraint(FixAtoms(mask=fixed[keep]))
            frame.set_tags(tags[keep])
            frame.info.update(
                {"task": "vacancy_landscape", "role": "vacancy_slab", "vacancy_count": count, "vacancy_sample": sample}
            )
            frames.append(frame)
            removed_sets.append({"vacancy_count": count, "sample": sample, "removed_indices": [int(i) for i in removed]})
    ctx.records.setdefault("vacancy_landscape", []).append(
        {
            "built_on": surface.label,
            "removable_surface_O": len(candidates),
            "surface_depth_A": VACANCY_SURFACE_DEPTH_A,
            "samples_per_count": samples,
            "removed": removed_sets,
        }
    )
    return frames


def _run_surface_cluster_builder(ctx: _RunContext, surface: _Surface, work_dir: Path) -> list[Atoms]:
    from .metal_cluster.cluster_builder import build_nanocluster
    from .metal_cluster.surface_cluster_builder import get_geometric_center, place_cluster_on_surface
    from .structure_io import frame_metrics

    inputs = ctx.resolution.inputs["surface_cluster_builder"]
    element = str(inputs["cluster_element"]["value"]).capitalize()
    n_atoms = int(inputs["cluster_atoms"]["value"])
    base = surface.atoms.copy()
    fixed, tags = _fixed_mask(base), _surface_tags(base)
    base.set_constraint()
    frames: list[Atoms] = []
    for structure in inputs["cluster_structures"]["value"]:
        try:
            cluster = build_nanocluster(element=element, structure=structure, atom_count=n_atoms)
        except ValueError as exc:
            raise SurfaceExecutionBlocked({"surface_cluster_builder": f"{element} {structure} cluster: {exc}"}) from exc
        cluster.positions -= get_geometric_center(cluster)
        combined = place_cluster_on_surface(base, cluster, 0.5, 0.5, CLUSTER_GAP_A, 0.0, 0.0, 0.0)
        if fixed.any():
            combined.set_constraint(FixAtoms(mask=np.concatenate([fixed, np.zeros(len(cluster), dtype=bool)])))
        combined.set_tags(np.concatenate([tags, np.full(len(cluster), 2, dtype=int)]))
        if _ensure_headroom(combined):
            ctx.checks.append(
                ValidationIssue(
                    code="cell_extended_for_cluster",
                    message=f"c was lengthened to keep {MIN_HEADROOM_A} A of vacuum above the {element} {structure} cluster.",
                )
            )
        fragments = np.concatenate([np.zeros(len(base), dtype=int), np.ones(len(cluster), dtype=int)])
        ratio = _fragment_clashes(combined, fragments)
        # Cluster-cluster periodic images are one fragment, so also check the whole frame.
        overall = frame_metrics(combined).get("min_contact_ratio")
        values = [value for value in (ratio, overall) if value is not None]
        worst = min(values) if values else None
        combined.info.update(
            {
                "task": "surface_cluster_builder",
                "role": "cluster_on_slab",
                "cluster_element": element,
                "cluster_structure": structure,
                "cluster_atoms": len(cluster),
                "min_contact_ratio": round(worst, 4) if worst is not None else -1.0,
            }
        )
        frames.append(combined)
    return frames


def _run_sam_functionalization(ctx: _RunContext, surface: _Surface, work_dir: Path) -> list[Atoms]:
    from .sam import SamBuildError, SamSettings, run_sam
    from .substrate import prepare_substrate

    inputs = ctx.resolution.inputs["sam_functionalization"]
    molecule_path = _stage_input(ctx, "sam_molecule_path", inputs["sam_molecule"]["value"], "sam_")
    try:
        settings = SamSettings(
            binding_mode=str(inputs["binding_mode"]["value"]),
            coverage_counts=tuple(int(value) for value in inputs["sam_counts"]["value"]),
            seed=ctx.overrides.seed,
        )
        substrate = prepare_substrate(surface=surface.path)
        result = run_sam(substrate, molecule_path, settings, work_dir, anchor_kind=inputs["anchor_kind"]["value"], export=())
    except SamBuildError as exc:
        raise SurfaceExecutionBlocked({"sam_functionalization": str(exc)}) from exc
    failed = result.manifest["validation"]["failed_counts"]
    if failed:
        ctx.warnings.append(
            ValidationIssue(
                code="sam_counts_not_built",
                message=f"SAM count(s) {failed} could not be placed on {surface.label}; see {_relative(result.manifest_path, ctx.root)}.",
            )
        )
    frames = [frame for frame in result.frames if frame.info.get("role") != "clean_slab"]
    if not frames:
        raise RuntimeError(f"No SAM structure could be built; see {_relative(result.manifest_path, ctx.root)}.")
    for frame in frames:
        frame.info.update({"task": "sam_functionalization", "role": "sam_on_slab"})
    ctx.records.setdefault("sam_functionalization", []).append(
        {
            "built_on": surface.label,
            "manifest": _relative(result.manifest_path, ctx.root),
            "molecule": _relative(molecule_path, ctx.root),
            "anchor_group": result.manifest["molecule"]["anchor_group"],
            "binding_mode": settings.binding_mode,
            "failed_counts": failed,
        }
    )
    return frames


def _amorphous_input(ctx: _RunContext, task: str) -> tuple[Path, Atoms]:
    from .structure_io import read_structure

    inputs = ctx.resolution.inputs[task]
    path = _stage_input(ctx, "amorphous_path", inputs["amorphous"]["value"], "amorphous_")
    atoms, _ = read_structure(path)
    formula_key = "overlayer_formula" if task == "ald_overlayer" else "amorphous_formula"
    mismatch = _formula_mismatch(atoms, inputs[formula_key]["value"])
    if mismatch:
        ctx.warnings.append(
            ValidationIssue(code="amorphous_composition_mismatch", message=f"{task}: amorphous bulk {mismatch}.")
        )
    return path, atoms


def _run_ald_overlayer(ctx: _RunContext, surface: _Surface, work_dir: Path) -> list[Atoms]:
    from .amorphous_overlayer import OverlayerBuildError, OverlayerSettings, run_overlayer
    from .substrate import prepare_substrate

    inputs = ctx.resolution.inputs["ald_overlayer"]
    amorphous_path, _ = _amorphous_input(ctx, "ald_overlayer")
    coverage = str(inputs["ald_coverage"]["value"])
    size: dict[str, Any]
    try:
        if coverage == "full":
            thickness = float(inputs["ald_thickness"]["value"])
            settings = OverlayerSettings(coverage=coverage, thickness=thickness, seed=ctx.overrides.seed)
            size = {"thickness": thickness}
        else:
            island_atoms = int(inputs["island_atoms"]["value"])
            settings = OverlayerSettings(coverage=coverage, island_atoms=island_atoms, seed=ctx.overrides.seed)
            size = {"island_atoms": island_atoms}
        substrate = prepare_substrate(surface=surface.path)
        result = run_overlayer(substrate, amorphous_path, settings, work_dir, export=())
    except OverlayerBuildError as exc:
        raise SurfaceExecutionBlocked({"ald_overlayer": str(exc)}) from exc
    frames = [frame for frame in result.frames if frame.info.get("role") != "clean_slab"]
    if not frames:
        raise RuntimeError(f"No ALD overlayer could be built; see {_relative(result.manifest_path, ctx.root)}.")
    for frame in frames:
        frame.info["task"] = "ald_overlayer"
    ctx.records.setdefault("ald_overlayer", []).append(
        {"built_on": surface.label, "manifest": _relative(result.manifest_path, ctx.root), "coverage": coverage, **size}
    )
    return frames


def _run_amorphous_slab(ctx: _RunContext, surface: _Surface | None, work_dir: Path) -> list[Atoms]:
    from .amorphous_overlayer import OverlayerBuildError
    from .amorphous_slab import AmorphousSlabSettings, run_amorphous_slab

    inputs = ctx.resolution.inputs["amorphous_slab"]
    amorphous_path, _ = _amorphous_input(ctx, "amorphous_slab")
    try:
        settings = AmorphousSlabSettings(thickness=float(inputs["amorphous_thickness"]["value"]), seed=ctx.overrides.seed)
        result = run_amorphous_slab(amorphous_path, settings, work_dir, export=())
    except OverlayerBuildError as exc:
        raise SurfaceExecutionBlocked({"amorphous_slab": str(exc)}) from exc
    if result.manifest["validation"]["issues"]:
        ctx.warnings.append(
            ValidationIssue(code="amorphous_slab_issues", message="; ".join(result.manifest["validation"]["issues"]))
        )
    for frame in result.frames:
        frame.info.update({"task": "amorphous_slab", "role": "amorphous_slab"})
    ctx.records["amorphous_slab"] = {
        "manifest": _relative(result.manifest_path, ctx.root),
        "thickness_A": settings.thickness,
    }
    return list(result.frames)


STRUCTURE_ONLY_RUNNERS: dict[str, Callable[..., list[Atoms]]] = {
    "vacancy_landscape": _run_vacancy_landscape,
    "ald_overlayer": _run_ald_overlayer,
    "sam_functionalization": _run_sam_functionalization,
    "surface_cluster_builder": _run_surface_cluster_builder,
    "adsorbate_landscape": _run_adsorbate_landscape,
    # The amorphous slab is a base surface; it never builds on another surface.
    "amorphous_slab": _run_amorphous_slab,
}


def _label(frames: list[Atoms], task: str, built_on: str) -> list[Atoms]:
    """Stable frame labels (task:index) and the label of the surface each frame was built on."""
    for index, frame in enumerate(frames):
        frame.calc = None
        frame.info["task"] = frame.info.get("task") or task
        frame.info["label"] = f"{task}:{index}"
        if built_on:  # base surfaces carry no parent; an empty extxyz value would not round-trip
            frame.info["built_on"] = built_on
        else:
            frame.info.pop("built_on", None)
    return frames


def _keep_non_overlapping(frames: list[Atoms], excluded: list[str]) -> list[Atoms]:
    """Drop placement candidates whose fragments overlap (d < CLASH_FRACTION x radii sum)."""
    kept: list[Atoms] = []
    for frame in frames:
        ratio = float(frame.info.get("min_contact_ratio", -1.0))
        if frame.info.get("role") in PLACEMENT_ROLES and 0.0 <= ratio < CLASH_FRACTION:
            excluded.append(str(frame.info.get("source_file") or frame.info.get("label")))
            continue
        kept.append(frame)
    return kept


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
        ctx = _RunContext(resolution, overrides, root, stage_dir, checks, warnings)
        frames: list[Atoms] = []
        slab_record: dict[str, Any] | None = None
        base: _Surface | None = None
        surfaces_dir = stage_dir / "surfaces"
        if resolution.slab is not None:
            slab_path, slab_record, slab_issues = _materialize_slab(resolution.slab, stage_dir, bulk_provider)
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
            frames.extend(_label([clean], "clean_slab", ""))
            base = _write_surface(clean, surfaces_dir, "clean_slab:0")
        if "amorphous_slab" in resolution.tasks:
            amorphous_frames = _label(
                _run_amorphous_slab(ctx, None, stage_dir / "amorphous_slab"), "amorphous_slab", ""
            )
            frames.extend(amorphous_frames)
            if resolution.amorphous_base:
                base = _write_surface(amorphous_frames[0], surfaces_dir, amorphous_frames[0].info["label"])
        if base is None:
            raise RuntimeError("No base surface was built.")

        excluded: list[str] = []
        chain_steps: list[dict[str, Any]] = []
        ordered = [task for task in TASK_ORDER if task in resolution.tasks]
        parent = base
        for position, task in enumerate(ordered):
            surface = parent if overrides.chain else base
            # Resolve the runner by name at call time so a patched module function takes effect.
            runner = globals()[STRUCTURE_ONLY_RUNNERS[task].__name__]
            produced = _label(runner(ctx, surface, stage_dir / task), task, surface.label)
            kept = _keep_non_overlapping(produced, excluded)
            if not kept:
                what = "adsorbate structure overlapped with the slab" if task == "adsorbate_landscape" else f"{task} structure overlapped"
                raise RuntimeError(f"Every generated {what}.")
            frames.extend(kept)
            if overrides.chain:
                is_last = position == len(ordered) - 1
                chain_steps.append(
                    {
                        "task": task,
                        "built_on": surface.label,
                        "structures": len(kept),
                        "next_step_uses": None if is_last else kept[0].info["label"],
                    }
                )
                if not is_last:
                    parent = _write_surface(kept[0], surfaces_dir, kept[0].info["label"])
        molecule_record = ctx.records.get("molecule")

        unique: list[Atoms] = []
        duplicates = 0
        for frame in frames:
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
            "base_surface": base.label,
            "chain": {"enabled": overrides.chain, "steps": chain_steps},
            "task_records": {
                key: value for key, value in ctx.records.items() if not key.endswith("_path") and key != "molecule"
            },
            "frames": [
                {
                    "frame_id": frame_id,
                    "label": frame.info.get("label"),
                    "task": frame.info.get("task"),
                    "role": frame.info.get("role"),
                    "built_on": frame.info.get("built_on") or None,
                    "n_atoms": len(frame),
                    "formula": frame.get_chemical_formula(mode="hill"),
                }
                for frame_id, frame in enumerate(unique)
            ],
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
            "source_tasks": list(
                dict.fromkeys(
                    [
                        *(["slab_generation" if slab_record["mode"] != "file" else "reviewed_slab"] if slab_record else []),
                        *resolution.tasks,
                    ]
                )
            ),
            "skipped_tasks": dict(resolution.skipped),
            "calculator": "none",
            "scientific_calculation_started": False,
            "energies_available": False,
            "slab_source": slab_record["mode"] if slab_record else "amorphous_slab",
            "facet": slab_record.get("facet") if slab_record else None,
            "facet_source": slab_record.get("facet_source") if slab_record else None,
            "base_surface": base.label,
            "chain": overrides.chain,
            "defaults_used": list(resolution.defaults_used),
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
