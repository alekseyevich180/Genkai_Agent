import subprocess
import sys
import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path

import pandas as pd

from paperread.surface.extract_surface_conditions import extract_conditions
from paperread.surface.extract_surface_relations import extract_relations
from paperread.surface.collect_experience import collect_experience
from paperread.surface.ingest_pdf import build_surface_inputs_from_sections, infer_title, split_sections
from paperread.surface.ptomodel import build_ptomodel_payload, generate_ptomodel_output
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
            "paperread.surface.collect_experience",
            "paperread.surface.ingest_pdf",
            "paperread.surface.run_surface_pipeline",
            "paperread.surface.ptomodel",
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
            "paperread/surface/collect_experience.py",
            "paperread/surface/ingest_pdf.py",
            "paperread/surface/run_surface_pipeline.py",
            "paperread/surface/ptomodel.py",
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
            "Surface Termination",
            "Active Site",
            "Defect",
            "Dopant/Modifier",
            "Adsorbate/Reactant",
            "Adsorption Site",
            "Coverage",
            "Cluster/Single Atom",
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
            "Modeling Keywords",
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
  "surface_terminations": ["reduced CeO2 surface"],
  "slab_models": ["CeO2(111) slab"],
  "facets": ["(111)"],
  "dopants": [],
  "defects": ["oxygen vacancy"],
  "vacancy_models": ["surface oxygen vacancy"],
  "active_sites": ["Pt site"],
  "adsorbates": ["CO", "O2"],
  "adsorption_sites": ["Pt site"],
  "coverage": ["CO coverage"],
  "intermediates": ["methoxy"],
  "products": ["CO2"],
  "clusters": ["Pt cluster"],
  "single_atoms": [],
  "modifiers": [],
  "properties": ["95% conversion", "100% selectivity"],
  "reaction_parameters": ["150 C", "2 h", "H2 reduction"],
  "modeling_keywords": ["surface", "adsorbate", "oxygen vacancy", "Pt cluster"],
  "recommended_modeling_tasks": ["vacancy_landscape", "adsorbate_landscape", "surface_cluster_builder"],
  "applications": ["CO oxidation"],
  "links": [
    {"source": "Pt/CeO2", "relation": "has_facet", "target": "(111)"},
    {"source": "Pt/CeO2", "relation": "has_reaction_parameter", "target": "150 C"}
  ]
}
```
"""
        condition_table = (
            "| Reaction Type | Material | Composition | Phase | Morphology/Size | Surface Area | Surface/Support | Facet | Surface Termination | Active Site | Defect | Dopant/Modifier | Adsorbate/Reactant | Adsorption Site | Coverage | Cluster/Single Atom | Feed/Concentration | Atmosphere | Pressure | Gas Flow | Solvent | pH | Temperature | Time | Loading | Potential/Bias | Current Density | Product | Conversion | Selectivity | Yield | Rate/Activity | Stability/Cycles | Modeling Keywords |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| CO oxidation | Pt/CeO2 | N/A | fluorite | nanoparticles | N/A | CeO2 | (111) | reduced surface | Pt site | oxygen vacancy | N/A | CO, O2 | Pt site | CO coverage | Pt cluster | 1% CO, 10% O2 | N2 | N/A | N/A | N/A | N/A | 150 C | 2 h | 1 wt% | N/A | N/A | CO2 | 95% | 100% | N/A | N/A | N/A | surface, adsorbate, oxygen vacancy |\n"
        )
        time_table = "| Index | Time |\n|---|---|\n| doc1_1 | 120 minutes |\n| doc2_1 | N/A |\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("paperread.surface.extract_surface_conditions.chat_completion", return_value=condition_table), \
                 patch("paperread.surface.standardize_surface_time.chat_completion", return_value=time_table), \
                 patch("paperread.surface.extract_surface_relations.chat_completion", return_value=relation_json):
                outputs = run_pipeline(
                    str(SAMPLE_INPUT),
                    tmpdir,
                    model=None,
                    collect_experience_output=True,
                )

            self.assertIn("conditions_csv", outputs)
            self.assertIn("time_csv", outputs)
            self.assertIn("relations_jsonl", outputs)
            self.assertIn("summary_txt", outputs)
            self.assertIn("ptomodel_json", outputs)
            self.assertIn("experience_material_classes_dir", outputs)
            self.assertTrue(Path(outputs["relations_jsonl"]).is_file())
            self.assertTrue(Path(outputs["ptomodel_json"]).is_file())
            self.assertTrue(Path(outputs["experience_material_classes_dir"]).is_dir())
            content = Path(outputs["relations_jsonl"]).read_text(encoding="utf-8")
            self.assertIn('"materials": [', content)
            self.assertIn('"Pt/CeO2"', content)
            summary = Path(outputs["summary_txt"]).read_text(encoding="utf-8")
            self.assertIn("这次抽到的关键信息包括", summary)
            self.assertIn("建模关键词", summary)
            self.assertIn("vacancy_landscape", summary)
            ptomodel_json = Path(outputs["ptomodel_json"]).read_text(encoding="utf-8")
            self.assertIn('"global_executable_tasks"', ptomodel_json)
            self.assertIn('"adsorbate_landscape"', ptomodel_json)
            self.assertIn('"surface_facets"', ptomodel_json)

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

    def test_pdf_section_fallback_uses_relevant_snippets_instead_of_full_text(self):
        title = "Long PDF"
        long_prefix = ("Background filler without useful section markers. " * 300).strip()
        sections = {
            "full_text": (
                f"{long_prefix}\n\n"
                "Preparation: Ni catalyst was freeze-dried, annealed at 700 C for 2 h under Ar, and washed.\n\n"
                "The oxygen evolution reaction showed 224 mV overpotential at 10 mA cm-2 with single Ni atoms.\n\n"
                f"{long_prefix}"
            )
        }

        conditions_payload, relations_payload = build_surface_inputs_from_sections(title, sections)
        self.assertIn("annealed at 700 C", conditions_payload["surface_conditions"]["Text"])
        self.assertIn("oxygen evolution reaction", relations_payload["surface_relations"]["Text"])
        self.assertLess(len(conditions_payload["surface_conditions"]["Text"]), len(sections["full_text"]))
        self.assertLess(len(relations_payload["surface_relations"]["Text"]), len(sections["full_text"]))

    def test_offline_pdf_pipeline_flow(self):
        relation_json = """
```json
{
  "materials": ["Pt/CeO2"],
  "material_parameters": ["1 wt% Pt loading"],
  "surfaces": ["CeO2"],
  "surface_terminations": [],
  "slab_models": [],
  "facets": ["(111)"],
  "dopants": [],
  "defects": ["oxygen vacancy"],
  "vacancy_models": ["surface oxygen vacancy"],
  "active_sites": ["Pt site"],
  "adsorbates": ["CO", "O2"],
  "adsorption_sites": ["Pt site"],
  "coverage": [],
  "intermediates": [],
  "products": ["CO2"],
  "clusters": [],
  "single_atoms": [],
  "modifiers": [],
  "properties": ["95% conversion"],
  "reaction_parameters": ["150 C"],
  "modeling_keywords": ["surface", "adsorbate", "oxygen vacancy"],
  "recommended_modeling_tasks": ["vacancy_landscape", "adsorbate_landscape"],
  "applications": ["CO oxidation"],
  "links": []
}
```
"""
        condition_table = (
            "| Reaction Type | Material | Composition | Phase | Morphology/Size | Surface Area | Surface/Support | Facet | Surface Termination | Active Site | Defect | Dopant/Modifier | Adsorbate/Reactant | Adsorption Site | Coverage | Cluster/Single Atom | Feed/Concentration | Atmosphere | Pressure | Gas Flow | Solvent | pH | Temperature | Time | Loading | Potential/Bias | Current Density | Product | Conversion | Selectivity | Yield | Rate/Activity | Stability/Cycles | Modeling Keywords |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| CO oxidation | Pt/CeO2 | N/A | fluorite | nanoparticles | N/A | CeO2 | (111) | reduced surface | Pt site | oxygen vacancy | N/A | CO, O2 | Pt site | N/A | N/A | 1% CO, 10% O2 | N2 | N/A | N/A | N/A | N/A | 150 C | 2 h | 1 wt% | N/A | N/A | CO2 | 95% | 100% | N/A | N/A | N/A | surface, adsorbate, oxygen vacancy |\n"
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
            self.assertIn("ptomodel_json", outputs)

    def test_ptomodel_filters_key_information_and_normalizes_equivalents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            relations_path = Path(tmpdir) / "sample_surface_relations.jsonl"
            table_path = Path(tmpdir) / "sample_table.csv"
            summary_path = Path(tmpdir) / "sample_summary.txt"
            relations_path.write_text(
                json_dumps_for_test(
                    {
                        "id": "doc1",
                        "title": "Pt cluster on CeO2(111)",
                        "extraction": {
                            "materials": ["Pt/CeO2"],
                            "surfaces": ["CeO2"],
                            "surface_terminations": ["reduced surface"],
                            "slab_models": ["CeO2(111) slab"],
                            "facets": ["(111)"],
                            "defects": ["oxygen vacancy"],
                            "vacancy_models": ["surface oxygen vacancy"],
                            "active_sites": ["Pt site"],
                            "adsorbates": ["CO", "O2"],
                            "adsorption_sites": ["Pt site"],
                            "coverage": ["0.25 ML CO"],
                            "clusters": ["Pt13 cluster"],
                            "modeling_keywords": ["surface", "adsorbate", "oxygen vacancy", "Pt cluster"],
                            "recommended_modeling_tasks": [
                                "vacancy_landscape",
                                "adsorbate_landscape",
                                "surface_cluster_builder",
                                "single_atom_site",
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            table_path.write_text(
                "Index,Reaction Type,Material,Surface/Support,Facet,Surface Termination,Active Site,Defect,Adsorbate/Reactant,Adsorption Site,Coverage,Cluster/Single Atom,Temperature,Time,Atmosphere,Product,Modeling Keywords\n"
                "doc1,CO oxidation,Pt/CeO2,CeO2,(1 1 1),reduced surface,Pt site,oxygen vacancy,\"CO, O2\",Pt site,0.25 ML CO,Pt13 cluster,150 C,2 h,N2,CO2,\"surface, adsorbate, oxygen vacancy, Pt cluster\"\n",
                encoding="utf-8",
            )
            summary_path.write_text("这次抽到的关键信息包括：CeO2(111)、氧空位、CO 吸附、Pt 团簇。", encoding="utf-8")

            payload = build_ptomodel_payload(
                str(relations_path),
                table_csv=str(table_path),
                summary_txt=str(summary_path),
            )

            self.assertEqual(payload["global_executable_tasks"], ["vacancy_landscape", "adsorbate_landscape", "surface_cluster_builder"])
            self.assertEqual(payload["global_deferred_tasks"], ["single_atom_site", "surface_functionalization", "slab_generation"])
            doc_payload = payload["documents"][0]
            self.assertEqual(doc_payload["normalized_mapping"]["primary_material"], "Pt/CeO2")
            self.assertEqual(doc_payload["normalized_mapping"]["facet_set"], ["(111)"])
            self.assertEqual(doc_payload["normalized_mapping"]["loaded_species"], ["Pt"])
            self.assertEqual(doc_payload["normalized_mapping"]["reaction_family"], ["CO oxidation"])
            self.assertIn("supported_catalysts", doc_payload["selected_information"]["material_classes"])
            self.assertIn("oxides", doc_payload["selected_information"]["material_classes"])
            self.assertIn("vacancy_landscape", doc_payload["task_inputs"])
            self.assertEqual(doc_payload["task_inputs"]["adsorbate_landscape"]["coverage"], ["0.25 ML CO"])
            self.assertEqual(
                doc_payload["task_argument_template"]["adsorbate_landscape"]["arguments"]["site_symbols"],
                "Pt",
            )
            self.assertEqual(
                doc_payload["task_argument_template"]["surface_cluster_builder"]["arguments"]["cluster_element"],
                "Pt",
            )
            self.assertIn(
                "surface",
                doc_payload["task_argument_template"]["adsorbate_landscape"]["required_missing_parameters"],
            )
            self.assertEqual(
                doc_payload["task_argument_template"]["adsorbate_landscape"]["argument_sources"]["surface"]["status"],
                "needs_upstream_artifact",
            )

            outputs = generate_ptomodel_output(
                str(relations_path),
                output_dir=tmpdir,
                stem="sample",
                table_csv=str(table_path),
                summary_txt=str(summary_path),
            )
            self.assertTrue(Path(outputs["ptomodel_json"]).is_file())

    def test_ptomodel_prefers_application_reaction_over_generic_table_step(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            relations_path = Path(tmpdir) / "sample_surface_relations.jsonl"
            table_path = Path(tmpdir) / "sample_table.csv"
            relations_path.write_text(
                json_dumps_for_test(
                    {
                        "id": "doc1",
                        "title": "Ni single atom OER",
                        "extraction": {
                            "materials": ["Ni-O-G SACs"],
                            "surfaces": ["graphene-like carbon"],
                            "single_atoms": ["single Ni atoms"],
                            "applications": ["oxygen evolution reaction"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            table_path.write_text(
                "Index,Reaction Type,Material,Surface/Support,Cluster/Single Atom\n"
                "doc1,Catalyst Preparation,Ni-O-G SACs,graphene-like carbon,Single Atom\n",
                encoding="utf-8",
            )

            payload = build_ptomodel_payload(str(relations_path), table_csv=str(table_path))
            doc_payload = payload["documents"][0]
            self.assertEqual(doc_payload["normalized_mapping"]["reaction_family"], ["OER"])

    def test_surface_indices_use_structure_aware_software_miller_mapping(self):
        from paperread.surface.surface_indices import canonicalize_surface_index

        zno = canonicalize_surface_index("(10-10)", material_context="ZnO")
        self.assertEqual(zno["software_facet"], "(100)")
        self.assertEqual(zno["space_group"], "P6_3mc (No. 186)")

        ru = canonicalize_surface_index("Ru(0001)")
        self.assertEqual(ru["software_facet"], "(001)")
        self.assertEqual(ru["space_group"], "P6_3/mmc (No. 194)")
        self.assertEqual(canonicalize_surface_index("Pt(111")["software_facet"], "(111)")

        coooh = canonicalize_surface_index("β-CoOOH(0112̅)")
        self.assertEqual(coooh["canonical_input_indices"], [0, 1, -1, 2])
        self.assertEqual(coooh["software_facet"], "(012)")
        self.assertTrue(coooh["warnings"])

    def test_ptomodel_outputs_surface_index_mapping_for_four_index_facets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            relations_path = Path(tmpdir) / "sample_surface_relations.jsonl"
            relations_path.write_text(
                json_dumps_for_test(
                    {
                        "id": "doc1",
                        "title": "beta CoOOH OER",
                        "extraction": {
                            "materials": ["β-CoOOH"],
                            "surfaces": ["β-CoOOH"],
                            "facets": ["(0112̅)"],
                            "applications": ["oxygen evolution reaction"],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            payload = build_ptomodel_payload(str(relations_path))
            doc_payload = payload["documents"][0]
            self.assertEqual(doc_payload["normalized_mapping"]["facet_set"], ["(012)"])
            surface_facet = doc_payload["selected_information"]["surface_facets"][0]
            self.assertEqual(surface_facet["surface_index"]["input_notation"], "miller_bravais_hkil")
            self.assertEqual(surface_facet["surface_index"]["software_miller_index"], [0, 1, 2])

    def test_summary_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            table_path = Path(tmpdir) / "sample_table.csv"
            relations_path = Path(tmpdir) / "sample_relations.jsonl"
            summary_path = Path(tmpdir) / "sample_summary.txt"
            table_path.write_text(
                "Index,Reaction Type,Material,Composition,Phase,Morphology/Size,Surface Area,Surface/Support,Facet,Surface Termination,Active Site,Defect,Dopant/Modifier,Adsorbate/Reactant,Adsorption Site,Coverage,Cluster/Single Atom,Feed/Concentration,Atmosphere,Pressure,Gas Flow,Solvent,pH,Temperature,Time,Loading,Potential/Bias,Current Density,Product,Conversion,Selectivity,Yield,Rate/Activity,Stability/Cycles,Modeling Keywords\n"
                "x1,Annealing,Sn SAs/G,2.93 wt% Sn,N/A,N/A,543 m2 g-1,Graphene oxide,N/A,N/A,Sn single atoms,N/A,N/A,N/A,N/A,N/A,Sn single atom,N/A,Ar,N/A,N/A,N/A,N/A,400 C,3 h,N/A,N/A,N/A,N/A,N/A,N/A,N/A,N/A,N/A,single atom surface\n",
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

    def test_collect_experience_outputs_known_and_unknown_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            relations_path = Path(tmpdir) / "sample_surface_relations.jsonl"
            table_path = Path(tmpdir) / "sample_table.csv"
            relations_path.write_text(
                json_dumps_for_test(
                    {
                        "id": "doc1",
                        "title": "Exsolved Pt on CeO2",
                        "extraction": {
                            "materials": ["Pt/CeO2"],
                            "surfaces": ["CeO2 surface"],
                            "adsorbates": ["CO"],
                            "modifiers": ["exsolved nanoparticle"],
                            "recommended_modeling_tasks": [
                                "adsorbate_landscape",
                                "exsolution_workflow",
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            table_path.write_text(
                "Material,Reaction Type,Loading,Modeling Keywords,Cluster/Single Atom\n"
                "Pt/CeO2,CO oxidation,1 wt%,surface,exsolved nanoparticle\n",
                encoding="utf-8",
            )

            result = collect_experience(
                str(relations_path),
                str(table_path),
                tmpdir,
                stem="sample_experience",
            )

            self.assertEqual(result["json_path"], "")
            self.assertEqual(result["markdown_path"], "")
            material_files = result["material_class_files"]
            self.assertIn("supported_catalysts", material_files)
            payload = json.loads(Path(material_files["supported_catalysts"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "2.0")
            self.assertIn("keyword_inventory", payload)
            self.assertIn("material_descriptors", payload)
            self.assertIn(
                "Pt",
                [item["term"] for item in payload["material_descriptors"]["elements"]],
            )
            self.assertIn(
                {"term": "{Ce, O, Pt}", "count": 2},
                payload["material_descriptors"]["element_sets"],
            )
            self.assertIn(
                "supported_catalyst",
                [item["term"] for item in payload["material_descriptors"]["material_kinds"]],
            )
            self.assertIn(
                "1 wt%",
                [item["term"] for item in payload["material_descriptors"]["approx_loadings"]],
            )
            self.assertIn(
                "Pt/CeO2",
                [item["term"] for item in payload["keyword_inventory"]["materials"]],
            )
            self.assertEqual(payload["class_profile"]["descriptor_schema"], "supported_catalyst_profile")
            self.assertIn(
                "CeO2",
                [item["term"] for item in payload["class_profile"]["support_components"]],
            )

    def test_surface_known_term_filter_removes_generic_unknown_noise(self):
        from paperread.surface.surface_ontology import is_known_surface_experience_term
        from paperread.surface.crystal_structures import match_crystal_structure_term
        from paperread.surface.material_vocabulary import (
            is_material_vocabulary_term,
            research_category_for_material_vocabulary,
        )

        self.assertTrue(is_known_surface_experience_term("Full"))
        self.assertTrue(is_known_surface_experience_term("Yes"))
        self.assertTrue(is_known_surface_experience_term("electronic structure"))
        self.assertTrue(is_known_surface_experience_term("Hubbard-U correction"))
        self.assertTrue(is_known_surface_experience_term("TiO2"))
        self.assertTrue(is_known_surface_experience_term("rutile"))
        self.assertTrue(is_known_surface_experience_term("normal spinel"))
        self.assertEqual(match_crystal_structure_term("rutile TiO2")["typical_space_group"], "P4_2/mnm (No. 136)")
        self.assertEqual(match_crystal_structure_term("normal spinel")["typical_space_group"], "Fd-3m (No. 227)")
        self.assertTrue(is_material_vocabulary_term("g-C3N4"))
        self.assertTrue(is_material_vocabulary_term("NiFe LDH"))
        self.assertTrue(is_material_vocabulary_term("Ba0.5Sr0.5Co0.8Fe0.2O3–d"))
        self.assertTrue(is_material_vocabulary_term("*OOH"))
        self.assertTrue(is_material_vocabulary_term("*H2O2"))
        self.assertTrue(is_material_vocabulary_term("Cr3c"))
        self.assertTrue(is_material_vocabulary_term("Pt-Bi Alloy"))
        self.assertEqual(research_category_for_material_vocabulary("*OOH"), "adsorption_reaction")
        self.assertEqual(research_category_for_material_vocabulary("Sn SAs/G-Na"), "clusters_single_atoms")
        self.assertTrue(is_known_surface_experience_term("Synthesis"))
        self.assertTrue(is_known_surface_experience_term("electrochemical water splitting"))
        from paperread.surface.surface_indices import is_surface_index_term

        self.assertTrue(is_surface_index_term("Pt(111)"))
        self.assertTrue(is_known_surface_experience_term("*OOH"))
        self.assertTrue(is_known_surface_experience_term("carbon doping"))
        self.assertTrue(is_known_surface_experience_term("five-coordinated Cr5c"))
        self.assertTrue(is_known_surface_experience_term("three-coordinated Cr3c"))


def json_dumps_for_test(payload: dict) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
