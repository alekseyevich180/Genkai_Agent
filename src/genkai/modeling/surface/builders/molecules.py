"""Gas molecules by name (ASE G2 reference geometries) or from a structure file.

Builders that place a molecule accept either a file (XYZ, CIF, POSCAR, ...) or the
name of a common sensing gas, so a job file can say ``molecule: NO2`` instead of
shipping a geometry. Geometries are the gas-phase G2 references of ASE (unrelaxed
for any particular model).
"""

from __future__ import annotations

from pathlib import Path

from ase import Atoms

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


def canonical_gas_name(name: str) -> str | None:
    """Canonical formula of a built-in gas name or alias (case-insensitive), else None."""
    text = name.strip()
    if text in BUILTIN_GAS_MOLECULES:
        return text
    lowered = text.casefold()
    return GAS_MOLECULE_ALIASES.get(lowered) or next(
        (key for key in BUILTIN_GAS_MOLECULES if key.casefold() == lowered), None
    )


def resolve_gas_molecule(name: str) -> tuple[str, Atoms]:
    """Canonical formula and G2 reference geometry for a built-in gas name."""
    from ase.build import molecule

    canonical = canonical_gas_name(name)
    if canonical is None:
        supported = ", ".join(sorted(BUILTIN_GAS_MOLECULES))
        raise ValueError(f"Unknown built-in gas molecule {name!r}; supported: {supported}.")
    return canonical, molecule(BUILTIN_GAS_MOLECULES[canonical])


def load_molecule(source: str | Path) -> tuple[Atoms, str]:
    """A molecule from an existing file, or a built-in gas by name; returns (atoms, where it came from)."""
    from ase.io import read

    path = Path(source)
    if path.is_file():
        return read(path), path.as_posix()
    # Only a bare name (no directory part) is read as a gas name; a missing file path stays an error.
    canonical = canonical_gas_name(str(source)) if path.parent == Path(".") else None
    if canonical is None:
        supported = ", ".join(sorted(BUILTIN_GAS_MOLECULES))
        raise FileNotFoundError(
            f"Molecule {source} is neither an existing file nor a built-in gas name ({supported})."
        )
    _, atoms = resolve_gas_molecule(canonical)
    return atoms, f"built-in gas {canonical} (ASE G2 geometry)"
