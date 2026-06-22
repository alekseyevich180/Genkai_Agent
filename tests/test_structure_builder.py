from pathlib import Path
import unittest

from ase.io import read

from matcreator.tools.structure_builder.structure_builder import build_bulk_crystal


class TestBuildBulkCrystal(unittest.TestCase):
    """Unit tests for build_bulk_crystal."""

    def test_build_bulk_crystal_creates_file(self) -> None:
        """build_bulk_crystal should write a valid structure file and return metadata."""
        tmp_dir = Path(".").resolve() / "tmp_test_build_bulk_crystal"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        out_file = tmp_dir / "al_fcc.extxyz"
        result = build_bulk_crystal(
            formula="Al",
            crystal_structure="fcc",
            size=1,
            output_format="extxyz",
            output_path=out_file,
        )

        self.assertEqual(result["status"], "success")
        self.assertTrue(Path(result["structure_path"]).is_file())
        self.assertGreater(result["num_atoms"], 0)

        atoms = read(result["structure_path"], index=0)
        self.assertEqual(
            atoms.get_chemical_formula(empirical=True),
            result["chemical_formula"],
        )
        self.assertEqual(len(atoms), result["num_atoms"])


if __name__ == "__main__":
    unittest.main()