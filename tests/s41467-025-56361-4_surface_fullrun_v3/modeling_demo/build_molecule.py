from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import write
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors


OUTPUT_DIR = Path(__file__).resolve().parent / "inputs"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    molecule = Chem.AddHs(Chem.MolFromSmiles("CC1CCC(=O)CC1"))
    if AllChem.EmbedMolecule(molecule, randomSeed=42) != 0:
        raise RuntimeError("RDKit failed to embed 4-methylcyclohexanone")
    AllChem.MMFFOptimizeMolecule(molecule, maxIters=1000)
    formula = rdMolDescriptors.CalcMolFormula(molecule)
    if formula != "C7H12O":
        raise RuntimeError(f"Unexpected molecular formula: {formula}")

    conformer = molecule.GetConformer()
    atoms = Atoms(
        symbols=[atom.GetSymbol() for atom in molecule.GetAtoms()],
        positions=np.asarray(conformer.GetPositions(), dtype=float),
    )
    path = OUTPUT_DIR / "4-methylcyclohexanone_C7H12O.xyz"
    write(path, atoms)
    print(path)


if __name__ == "__main__":
    main()
