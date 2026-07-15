import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ase.build import bulk, surface
from pymatgen.core import Lattice, Structure

from paperread.surface.modeling.job_bundle import write_compact_job_bundle


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = (
    PROJECT_ROOT
    / "agents/Agent/skills/surface-modeling/scripts/surface/materials_project_slab.py"
)
SPEC = importlib.util.spec_from_file_location("materials_project_slab", MODULE_PATH)
mp_slab = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = mp_slab
SPEC.loader.exec_module(mp_slab)


class TestMaterialsProjectSurfaceWorkflow(unittest.TestCase):
    def test_stable_facet_priority(self):
        explicit = mp_slab.resolve_stable_facet("CeO2", "Fm-3m", "1,0,0")
        self.assertEqual(explicit.miller_index, (1, 0, 0))
        self.assertEqual(explicit.source, "explicit")

        ceria = mp_slab.resolve_stable_facet("CeO2", "Fm-3m")
        self.assertEqual(ceria.miller_index, (1, 1, 1))
        self.assertEqual(ceria.source, "stable_facet_registry")

        tungsten = mp_slab.resolve_stable_facet("W", "Im-3m")
        self.assertEqual(tungsten.miller_index, (1, 1, 0))
        self.assertEqual(tungsten.source, "structure_family_registry")
        self.assertEqual(mp_slab.parse_miller_index("0,0,0,1"), (0, 0, 1))

    def test_unknown_stable_facet_requires_review(self):
        with self.assertRaisesRegex(ValueError, "No stable facet is registered"):
            mp_slab.resolve_stable_facet("SiO2", "P3_121")

    def test_bulk_cell_is_rejected_and_vacuum_slab_is_accepted(self):
        copper = bulk("Cu", "fcc", a=3.6)
        with self.assertRaisesRegex(ValueError, "bulk unit cell"):
            mp_slab.validate_surface_slab(copper)

        slab = surface(copper, (1, 1, 1), layers=4, vacuum=10.0)
        check = mp_slab.validate_surface_slab(slab)
        self.assertTrue(check["is_slab"])
        self.assertGreaterEqual(check["vacuum_gap_A"], 5.0)

    def test_mp_bulk_selection_prefers_stable_low_hull_entry(self):
        docs = [
            SimpleNamespace(material_id="mp-high", is_stable=False, energy_above_hull=0.2, theoretical=False),
            SimpleNamespace(material_id="mp-stable", is_stable=True, energy_above_hull=0.0, theoretical=False),
        ]
        selected = mp_slab._select_bulk_document(docs)
        self.assertEqual(selected.material_id, "mp-stable")

    def test_download_workflow_builds_slab_without_persisting_key(self):
        ceria = Structure.from_spacegroup(
            "Fm-3m",
            Lattice.cubic(5.411),
            ["Ce", "O"],
            [[0, 0, 0], [0.25, 0.25, 0.25]],
        )
        metadata = {
            "material_id": "mp-test",
            "formula": "CeO2",
            "spacegroup_symbol": "Fm-3m",
            "energy_above_hull_eV_per_atom": 0.0,
            "is_stable": True,
            "theoretical": False,
        }
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            mp_slab,
            "fetch_bulk_structure",
            return_value=(ceria, metadata),
        ):
            manifest = mp_slab.download_stable_surface(
                tmpdir,
                formula="CeO2",
                api_key="not-persisted-test-key",
                min_slab_size=8.0,
                min_vacuum_size=10.0,
                repeat_xy=(1, 1),
            )
            self.assertEqual(manifest["facet"]["miller_index"], [1, 1, 1])
            self.assertTrue(manifest["checks"]["surface_is_slab"]["is_slab"])
            serialized = Path(manifest["files"]["surface_manifest"]).read_text(encoding="utf-8")
            self.assertNotIn("not-persisted-test-key", serialized)

    def test_compact_job_bundle_consolidates_generated_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            table = root / "conditions.csv"
            table.write_text("Index,Material,Facet\ndoc1,Pt/CeO2,(111)\n", encoding="utf-8")
            time = root / "time.csv"
            time.write_text("Index,Time\ndoc1,120 minutes\n", encoding="utf-8")
            relations = root / "relations.jsonl"
            relations.write_text(
                json.dumps({"id": "doc1", "title": "Paper", "extraction": {"materials": ["Pt/CeO2"]}}),
                encoding="utf-8",
            )
            summary = root / "summary.txt"
            summary.write_text("summary", encoding="utf-8")
            plan = root / "ptomodel.json"
            plan.write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "id": "doc1",
                                "recommended_modeling_tasks": ["surface_cluster_builder"],
                                "executable_tasks": ["surface_cluster_builder"],
                                "task_argument_template": {
                                    "surface_cluster_builder": {
                                        "arguments": {"surface_formula": "CeO2", "cluster_atoms": None},
                                        "auto_mapped_parameters": ["surface_formula"],
                                        "parameter_bindings": {
                                            "cluster_atoms": {
                                                "status": "needs_manual_decision",
                                                "source_term": "Pt nanoparticle",
                                                "reason": "size missing",
                                                "depends_on": [],
                                            }
                                        },
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            outputs = {
                "conditions_csv": str(table),
                "time_csv": str(time),
                "relations_jsonl": str(relations),
                "summary_txt": str(summary),
                "ptomodel_json": str(plan),
            }
            compact = write_compact_job_bundle(
                output_dir=tmpdir,
                outputs=outputs,
                source_path="paper.pdf",
                cleanup_generated=True,
            )

            self.assertTrue(Path(compact["article_json"]).exists())
            self.assertTrue(Path(compact["modeling_plan_json"]).exists())
            checklist = json.loads(Path(compact["modeling_checklist_json"]).read_text(encoding="utf-8"))
            self.assertEqual(checklist["status"], "needs_review")
            self.assertEqual(checklist["review_items"][0]["parameter"], "cluster_atoms")
            self.assertFalse(table.exists())
            self.assertTrue((root / "modeling/structures").is_dir())


if __name__ == "__main__":
    unittest.main()
