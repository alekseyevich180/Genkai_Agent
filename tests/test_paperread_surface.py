import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from paperread.surface.extract_surface_conditions import extract_conditions
from paperread.surface.extract_surface_relations import extract_relations
from paperread.surface.ingest_pdf import build_surface_inputs_from_sections, infer_title, split_sections
from paperread.surface.run_surface_pipeline import run_pipeline, run_pipeline_from_pdf
from paperread.surface.standardize_surface_time import standardize_time
from paperread.surface.summarize_surface_outputs import write_summary


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_INPUT = PROJECT_ROOT / "paperread" / "surface" / "examples" / "sample_surface_input.json"


def _run_command(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestPaperreadSurfaceScripts(unittest.TestCase):
    def test_module_entrypoints_show_help(self):
        modules = [
            "paperread.surface.extract_surface_conditions",
            "paperread.surface.standardize_surface_time",
            "paperread.surface.extract_surface_relations",
            "paperread.surface.ingest_pdf",
            "paperread.surface.run_surface_pipeline",
        ]
        for module in modules:
            with self.subTest(module=module):
                result = _run_command([sys.executable, "-m", module, "--help"])
                self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_direct_script_entrypoints_show_help(self):
        scripts = [
            "paperread/surface/extract_surface_conditions.py",
            "paperread/surface/standardize_surface_time.py",
            "paperread/surface/extract_surface_relations.py",
            "paperread/surface/ingest_pdf.py",
            "paperread/surface/run_surface_pipeline.py",
        ]
        for script in scripts:
            with self.subTest(script=script):
                result = _run_command([sys.executable, script, "--help"])
                self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_offline_conditions_and_time_flow(self):
        columns = [
            "Reaction Type",
            "Material",
            "Composition",
            "Phase",
            "Morphology/Size",
            "Surface Area",
            "Surface/Support",
            "Facet",
            "Active Site",
            "Defect",
            "Dopant/Modifier",
            "Adsorbate/Reactant",
            "Feed/Concentration",
            "Atmosphere",
            "Pressure",
            "Gas Flow",
            "Solvent",
            "pH",
            "Temperature",
            "Time",
            "Loading",
            "Potential/Bias",
            "Current Density",
            "Product",
            "Conversion",
            "Selectivity",
            "Yield",
            "Rate/Activity",
            "Stability/Cycles",
        ]
        condition_table = (
            "| " + " | ".join(columns) + " |\n"
            "| " + " | ".join(["---"] * len(columns)) + " |\n"
            "| CO oxidation | Pt/CeO2 | N/A | fluorite | nanoparticles | N/A | CeO2 | (111) | Pt site | oxygen vacancy | N/A | CO, O2 | 1% CO, 10% O2 | N2 | N/A | N/A | N/A | N/A | 150 C | 2 h | 1 wt% | N/A | N/A | CO2 | 95% | 100% | N/A | N/A | N/A |\n"
        )
        time_table = "| Index | Time |\n|---|---|\n| 1_1 | 120 minutes |\n| 2_1 | N/A |\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = str(Path(tmpdir) / "surface")
            with patch("paperread.surface.extract_surface_conditions.chat_completion", return_value=condition_table):
                raw_path, table_path = extract_conditions(str(SAMPLE_INPUT), prefix, model=None)
            with patch("paperread.surface.standardize_surface_time.chat_completion", return_value=time_table):
                time_path = str(Path(tmpdir) / "surface_time.csv")
                standardize_time(table_path, time_path, model=None)

            self.assertIsNone(raw_path)
            self.assertTrue(Path(table_path).is_file())
            self.assertTrue(Path(time_path).is_file())
            table_df = pd.read_csv(table_path)
            self.assertIn("Reaction Type", table_df.columns)
            self.assertIn("Material", table_df.columns)
            self.assertIn("Time", table_df.columns)
            time_df = pd.read_csv(time_path)
            self.assertEqual(list(time_df.columns), ["Index", "Time"])

    def test_offline_relations_and_pipeline_flow(self):
        relation_json = """
```json
{
  "materials": ["Pt/CeO2"],
  "material_parameters": ["1 wt% Pt loading", "CeO2(111) support"],
  "surfaces": ["CeO2"],
  "facets": ["(111)"],
  "dopants": [],
  "defects": ["oxygen vacancy"],
  "active_sites": ["Pt site"],
  "adsorbates": ["CO", "O2"],
  "intermediates": ["methoxy"],
  "products": ["CO2"],
  "properties": ["95% conversion", "100% selectivity"],
  "reaction_parameters": ["150 C", "2 h", "H2 reduction"],
  "applications": ["CO oxidation"],
  "links": [
    {"source": "Pt/CeO2", "relation": "has_facet", "target": "(111)"},
    {"source": "Pt/CeO2", "relation": "has_reaction_parameter", "target": "150 C"}
  ]
}
```
"""
        condition_table = (
            "| Reaction Type | Material | Composition | Phase | Morphology/Size | Surface Area | Surface/Support | Facet | Active Site | Defect | Dopant/Modifier | Adsorbate/Reactant | Feed/Concentration | Atmosphere | Pressure | Gas Flow | Solvent | pH | Temperature | Time | Loading | Potential/Bias | Current Density | Product | Conversion | Selectivity | Yield | Rate/Activity | Stability/Cycles |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| CO oxidation | Pt/CeO2 | N/A | fluorite | nanoparticles | N/A | CeO2 | (111) | Pt site | oxygen vacancy | N/A | CO, O2 | 1% CO, 10% O2 | N2 | N/A | N/A | N/A | N/A | 150 C | 2 h | 1 wt% | N/A | N/A | CO2 | 95% | 100% | N/A | N/A | N/A |\n"
        )
        time_table = "| Index | Time |\n|---|---|\n| doc1_1 | 120 minutes |\n| doc2_1 | N/A |\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("paperread.surface.extract_surface_conditions.chat_completion", return_value=condition_table), \
                 patch("paperread.surface.standardize_surface_time.chat_completion", return_value=time_table), \
                 patch("paperread.surface.extract_surface_relations.chat_completion", return_value=relation_json):
                outputs = run_pipeline(str(SAMPLE_INPUT), tmpdir, model=None)

            self.assertIn("conditions_csv", outputs)
            self.assertIn("time_csv", outputs)
            self.assertIn("relations_jsonl", outputs)
            self.assertIn("summary_txt", outputs)
            self.assertTrue(Path(outputs["relations_jsonl"]).is_file())
            content = Path(outputs["relations_jsonl"]).read_text(encoding="utf-8")
            self.assertIn('"materials": [', content)
            self.assertIn('"Pt/CeO2"', content)
            summary = Path(outputs["summary_txt"]).read_text(encoding="utf-8")
            self.assertIn("这次抽到的关键信息包括", summary)

    def test_pdf_section_routing_helpers(self):
        pdf_text = """
Title line

Abstract
Methanol adsorption on rutile TiO2(110) was studied.

Experimental
Pt was deposited on CeO2(111) and reduced under H2 at 300 C for 2 h.

Results and Discussion
Oxygen vacancies acted as active sites and methoxy was identified.
"""
        title = infer_title(pdf_text, "")
        self.assertEqual(title, "Title line")
        sections = split_sections(pdf_text)
        self.assertIn("abstract", sections)
        self.assertIn("methods", sections)
        self.assertIn("results_discussion", sections)
        conditions_payload, relations_payload = build_surface_inputs_from_sections(title, sections)
        self.assertIn("reduced under H2", conditions_payload["surface_conditions"]["Text"])
        self.assertIn("Methanol adsorption", relations_payload["surface_relations"]["Text"])

    def test_offline_pdf_pipeline_flow(self):
        relation_json = """
```json
{
  "materials": ["Pt/CeO2"],
  "material_parameters": ["1 wt% Pt loading"],
  "surfaces": ["CeO2"],
  "facets": ["(111)"],
  "dopants": [],
  "defects": ["oxygen vacancy"],
  "active_sites": ["Pt site"],
  "adsorbates": ["CO", "O2"],
  "intermediates": [],
  "products": ["CO2"],
  "properties": ["95% conversion"],
  "reaction_parameters": ["150 C"],
  "applications": ["CO oxidation"],
  "links": []
}
```
"""
        condition_table = (
            "| Reaction Type | Material | Composition | Phase | Morphology/Size | Surface Area | Surface/Support | Facet | Active Site | Defect | Dopant/Modifier | Adsorbate/Reactant | Feed/Concentration | Atmosphere | Pressure | Gas Flow | Solvent | pH | Temperature | Time | Loading | Potential/Bias | Current Density | Product | Conversion | Selectivity | Yield | Rate/Activity | Stability/Cycles |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| CO oxidation | Pt/CeO2 | N/A | fluorite | nanoparticles | N/A | CeO2 | (111) | Pt site | oxygen vacancy | N/A | CO, O2 | 1% CO, 10% O2 | N2 | N/A | N/A | N/A | N/A | 150 C | 2 h | 1 wt% | N/A | N/A | CO2 | 95% | 100% | N/A | N/A | N/A |\n"
        )
        time_table = "| Index | Time |\n|---|---|\n| surface_conditions_1 | 120 minutes |\n"
        ingestion_payloads = {
            "title": "Dummy PDF",
            "text": "dummy text",
            "sections": {"full_text": "dummy text"},
            "conditions_payload": {
                "surface_conditions": {
                    "Title": "Dummy PDF",
                    "Text": "dummy conditions",
                }
            },
            "relations_payload": {
                "surface_relations": {
                    "Title": "Dummy PDF",
                    "Text": "dummy relations",
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("paperread.surface.run_surface_pipeline.ingest_pdf_payloads", return_value=ingestion_payloads), \
                 patch("paperread.surface.extract_surface_conditions.chat_completion", return_value=condition_table), \
                 patch("paperread.surface.standardize_surface_time.chat_completion", return_value=time_table), \
                 patch("paperread.surface.extract_surface_relations.chat_completion", return_value=relation_json):
                outputs = run_pipeline_from_pdf("dummy.pdf", tmpdir, model=None)

            self.assertIn("conditions_csv", outputs)
            self.assertIn("relations_jsonl", outputs)
            self.assertIn("summary_txt", outputs)

    def test_summary_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            table_path = Path(tmpdir) / "sample_table.csv"
            relations_path = Path(tmpdir) / "sample_relations.jsonl"
            summary_path = Path(tmpdir) / "sample_summary.txt"
            table_path.write_text(
                "Index,Reaction Type,Material,Composition,Phase,Morphology/Size,Surface Area,Surface/Support,Facet,Active Site,Defect,Dopant/Modifier,Adsorbate/Reactant,Feed/Concentration,Atmosphere,Pressure,Gas Flow,Solvent,pH,Temperature,Time,Loading,Potential/Bias,Current Density,Product,Conversion,Selectivity,Yield,Rate/Activity,Stability/Cycles\n"
                "x1,Annealing,Sn SAs/G,2.93 wt% Sn,N/A,N/A,543 m2 g-1,Graphene oxide,N/A,Sn single atoms,N/A,N/A,N/A,N/A,Ar,N/A,N/A,N/A,N/A,400 C,3 h,N/A,N/A,N/A,N/A,N/A,N/A,N/A,N/A,N/A\n",
                encoding="utf-8",
            )
            relations_path.write_text(
                '{"id":"x1","title":"t","text":"t","extraction":{"materials":["Sn SAs/G"],"material_parameters":[{"composition":"2.93 wt% Sn"}],"reaction_parameters":[{"temperature":"400 C"}],"properties":[{"Coulombic_efficiency":"99.8%"}]}}' + "\n",
                encoding="utf-8",
            )
            write_summary(str(table_path), str(relations_path), str(summary_path))
            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("在 sample_table.csv 里", summary)
            self.assertIn("2.93 wt% Sn", summary)


if __name__ == "__main__":
    unittest.main()
