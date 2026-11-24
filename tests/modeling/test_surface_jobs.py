"""genkai-surface job files: option tables, validation, templates, and real structure-only runs."""

from __future__ import annotations

import io
import json
import re
import time
import sys
from pathlib import Path

import pytest
import yaml

from genkai.contracts.run import RunManifest
from genkai.modeling.surface.app import jobs
from genkai.modeling.surface.app.jobs import JobFileError, build_argv, command_check, load_job_file, main, render_template

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "agents" / "Agent" / "skills" / "surface-modeling" / "examples"
SNO2_BULK = ROOT / "tests" / "se4c02105_surface_fullrun" / "automatic_modeling" / "sno2_101" / "bulk_from_materials_project.cif"
CEO2_SLAB = EXAMPLES / "CeO2 (1 1 1).cif"
BUTANOIC = EXAMPLES / "4-acid.vasp"
A_TIO2 = ROOT / "tests" / "amorphous" / "TiO2.vasp"
JOB_EXAMPLES = ROOT / "examples" / "surface_jobs"

# Real files for the placeholders of every template.
PLACEHOLDER_FILES = {
    "bulk": SNO2_BULK,
    "crystal": SNO2_BULK,
    "structures": CEO2_SLAB,
    "surface": CEO2_SLAB,
    "input": CEO2_SLAB,
    "molecule": BUTANOIC,
    "amorphous": A_TIO2,
    "cluster": ROOT / "tests/fixtures/archives/generated/s41563-025-02134-9_surface_fullrun/modeling/structures/Ru_hcp_r7.xyz",
}


def _job(tmp_path: Path, text: str, name: str = "job.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _problems(path: Path) -> list[str]:
    with pytest.raises(JobFileError) as error:
        load_job_file(path)
    return error.value.problems


def test_option_tables_match_the_method_parsers() -> None:
    blocked = (jobs.ENERGY_KEYS - jobs.TASK_ENERGY_KEYS) | jobs.NETWORK_KEYS
    for name, method in jobs.METHODS.items():
        flags = jobs.method_parser(name)._option_string_actions
        for option in method.options:
            assert option.flag in flags, f"{name}: {option.flag} is not an option of {method.module}"
            assert option.key not in blocked, f"{name}: {option.key} must stay locked"
        for locked in method.locked:
            assert locked.split("=", 1)[0] in flags, f"{name}: locked {locked} unknown"
        assert method.output_flag in flags
        for group in method.groups:
            assert set(group.keys) <= set(method.keys)


@pytest.mark.parametrize("name", sorted(jobs.METHODS))
def test_every_template_validates_once_placeholders_are_filled(tmp_path: Path, name: str) -> None:
    text = render_template(name)
    assert text.startswith("# Genkai 表面建模任务文件")

    def fill(match: re.Match[str]) -> str:
        return f"{match.group(1)}: '{PLACEHOLDER_FILES[match.group(1)].as_posix()}'"

    filled = re.sub(r"^(\w+): <[^>]+>", fill, text, flags=re.MULTILINE)
    assert "<" not in "".join(line.split("#", 1)[0] for line in filled.splitlines())
    checkpoint = tmp_path / "interface-only.model"
    checkpoint.touch()
    config = tmp_path / "genkai.yaml"
    config.write_text(yaml.safe_dump({"version": 1, "default": "mace", "profiles": {
        "mace": {"python": sys.executable, "model": str(checkpoint)},
    }}), encoding="utf-8")
    [job] = load_job_file(_job(tmp_path, filled), config_path=config)
    argv = build_argv(job)
    assert job.output == (tmp_path / "runs" / name).resolve()
    assert all(locked in argv for locked in jobs.METHODS[name].locked)


def test_yaml_values_keep_their_text_and_paths_are_relative_to_the_job_file(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "slab.cif").write_text("placeholder", encoding="utf-8")
    path = _job(tmp_path, (
        "method: sam\n"
        "surface: inputs/slab.cif\n"
        "molecule: '" + BUTANOIC.as_posix() + "'\n"
        "binding_mode: monodentate\n"
        "counts: 1, 2\n"
        "anchor_atoms: [3, 4]\n"
        "tilt: -30\n"
    ))
    [job] = load_job_file(path)
    assert job.values["surface"] == (tmp_path / "inputs" / "slab.cif").resolve()
    assert job.values["counts"] == [1, 2]
    assert "--counts=1,2" in build_argv(job) and "--anchor-atoms=3,4" in build_argv(job)
    assert "--tilt=-30.0" in build_argv(job)  # "=" keeps negative numbers from looking like flags

    upper = _job(tmp_path, f"method: Amorphous-Slab\namorphous: '{A_TIO2.as_posix()}'\nthickness: 8\n", "upper.yaml")
    assert load_job_file(upper)[0].method.name == "amorphous_slab"  # SAM / ALD / amorphous-slab spellings

    for raw, expected in (('"0001"', "0001"), ("010", "010"), ("[1, 1, 0]", "1,1,0"), ('"(1-10)"', "(1-10)")):
        facet_job = _job(tmp_path, f"method: slab\nbulk: '{SNO2_BULK.as_posix()}'\nfacet: {raw}\n", "facet.yaml")
        [job] = load_job_file(facet_job)
        assert job.values["facet"] == expected


def test_invalid_jobs_report_every_problem_with_guidance(tmp_path: Path) -> None:
    path = _job(tmp_path, (
        "method: sam\n"
        f"bulk: '{SNO2_BULK.as_posix()}'\n"
        f"surface: '{CEO2_SLAB.as_posix()}'\n"
        f"molecule: '{BUTANOIC.as_posix()}'\n"
        "binding_mod: monodentate\n"
        "counts: [1, 2]\n"
        "calculator: uma\n"
        "formula: SnO2\n"
        "repeat_xy: [2, 2, 1]\n"
        "seed: abc\n"
    ))
    problems = "\n".join(_problems(path))
    assert "binding_mod" in problems and "binding_mode" in problems  # typo with a suggestion
    assert "genkai.yaml" in problems  # calculator details belong to the shared configuration
    assert "不联网" in problems  # Materials Project locked
    assert "二选一" in problems and "bulk, surface" in problems
    assert "需要 2 个数" in problems
    assert "需要整数" in problems
    assert "缺少必填项 binding_mode" in problems

    assert "amorphous_slab" in "\n".join(_problems(_job(tmp_path, "method: amorphus_slab\n", "typo.yaml")))
    assert "缺少必填项 molecule" in "\n".join(_problems(_job(tmp_path, "method: sam_search\n", "search.yaml")))
    windows = _job(tmp_path, 'method: slab\nbulk: "C:\\Users\\me\\SnO2.cif"\n', "windows.yaml")
    assert "正斜杠" in "\n".join(_problems(windows))


def test_parser_level_errors_are_reported_before_running(tmp_path: Path) -> None:
    path = _job(tmp_path, f"method: ald\nbulk: '{SNO2_BULK.as_posix()}'\namorphous: '{A_TIO2.as_posix()}'\ncoverage: some\n")
    problems = "\n".join(_problems(path))
    assert "参数检查未通过" in problems and "some" in problems


def test_check_resolves_chained_inputs_and_flags_missing_files(tmp_path: Path) -> None:
    chained = _job(tmp_path, (
        "jobs:\n"
        "  - method: amorphous_slab\n"
        "    output: runs/a\n"
        f"    amorphous: '{A_TIO2.as_posix()}'\n"
        "    thickness: 10\n"
        "  - method: sam\n"
        "    output: runs/b\n"
        "    surface: runs/a/amorphous_slab_000.extxyz\n"
        f"    molecule: '{BUTANOIC.as_posix()}'\n"
        "    binding_mode: bidentate\n"
        "    counts: [1]\n"
    ))
    out = io.StringIO()
    assert command_check([chained], out) == 0
    assert "由前面的任务" in out.getvalue()

    missing = _job(tmp_path, "method: amorphous_slab\namorphous: nowhere.vasp\nthickness: 8\n", "missing.yaml")
    out = io.StringIO()
    assert command_check([missing], out) == 2
    assert "文件不存在" in out.getvalue()


def test_example_job_files_are_valid() -> None:
    from genkai.modeling.surface.app.pipeline import is_pipeline_file

    files = sorted(JOB_EXAMPLES.glob("*.yaml"))
    assert len(files) >= 8
    out = io.StringIO()
    assert command_check(files, out) == 0, out.getvalue()  # job files and pipeline files together
    job_files = [path for path in files if not is_pipeline_file(path)]
    methods = {job.method.name for path in job_files for job in load_job_file(path)}
    assert methods == {name for name, method in jobs.METHODS.items() if not method.requires_mlip}
    # Windows shells pass "*.yaml" through unexpanded; the CLI expands it itself.
    assert jobs.expand_paths([JOB_EXAMPLES / "*.yaml"]) == files


@pytest.mark.integration
def test_run_writes_structures_manifest_and_refuses_a_used_output(tmp_path: Path, capsys) -> None:
    path = _job(tmp_path, f"method: amorphous_slab\ndescription: test\namorphous: '{A_TIO2.as_posix()}'\nthickness: 10\nsamples: 2\n")
    assert main(["run", "--quiet", str(path)]) == 0
    output = tmp_path / "runs" / "job"
    assert (output / "amorphous_slab_structures.extxyz").is_file()
    assert (output / "run.log").is_file() and (output / "job_resolved.yaml").is_file()
    manifest = RunManifest.model_validate_json((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.metadata["energies_available"] is False and manifest.metadata["description"] == "test"
    [stage] = manifest.stages
    assert stage.execution_state.value == "succeeded" and stage.metadata["exit_code"] == 0
    [artifact] = manifest.artifacts
    assert artifact.path.as_posix() == "amorphous_slab_structures.extxyz"
    assert artifact.evidence_level.value == "heuristic"
    assert artifact.metadata["frame_count"] == 2
    assert all(frame["n_fixed"] > 0 for frame in artifact.metadata["frames"])
    assert stage.metadata["inputs"][0]["sha256"]
    printed = capsys.readouterr().out
    assert "PASS 1" in printed and "没有计算能量" in printed

    # A second run must not mix files into the used output directory.
    assert main(["run", "--quiet", str(path)]) == 1
    assert "--overwrite" in capsys.readouterr().out
    # Structure files older than the run are never reported as its output.
    [job] = load_job_file(path)
    status, messages, _, _ = jobs._check_outputs(job, since=time.time() + 60)
    assert status == "FAIL" and "本次生成" in messages[0]
    assert main(["run", "--quiet", "--overwrite", str(path)]) == 0


@pytest.mark.integration
def test_failed_method_is_recorded_and_later_jobs_in_the_file_are_skipped(tmp_path: Path, capsys) -> None:
    path = _job(tmp_path, (
        "jobs:\n"
        "  - method: sam\n"
        f"    surface: '{CEO2_SLAB.as_posix()}'\n"
        f"    molecule: '{BUTANOIC.as_posix()}'\n"
        "    binding_mode: monodentate\n"
        "    counts: [1]\n"
        "    tilt: 95\n"
        "  - method: amorphous_slab\n"
        f"    amorphous: '{A_TIO2.as_posix()}'\n"
        "    thickness: 10\n"
    ))
    assert main(["run", "--quiet", str(path)]) == 1
    printed = capsys.readouterr().out
    assert "FAIL 1" in printed and "SKIP 1" in printed
    manifest = json.loads((tmp_path / "runs" / "job" / "01_sam" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["stages"][0]["execution_state"] == "failed" and manifest["artifacts"] == []
    assert not (tmp_path / "runs" / "job" / "02_amorphous_slab").exists()


def test_methods_and_template_commands(tmp_path: Path, capsys) -> None:
    assert main(["methods"]) == 0
    listing = capsys.readouterr().out
    assert all(name in listing for name in jobs.METHODS) and "暂未开放" in listing
    assert main(["methods", "ald"]) == 0
    assert "--calculator=none" in capsys.readouterr().out
    target = tmp_path / "ald.yaml"
    assert main(["template", "ald", "-o", str(target)]) == 0
    assert "coverage: full" in target.read_text(encoding="utf-8")
    assert main(["template", "ald", "-o", str(target)]) == 1  # no silent overwrite
    assert main(["template", "ald", "-o", str(target), "--force"]) == 0


def test_cluster_output_check_includes_the_tenth_ranked_candidate(tmp_path):
    from ase import Atoms
    from ase.io import write

    output = tmp_path / "mlip_output"
    output.mkdir()
    structure = Atoms("Cu2", positions=[[0, 0, 1], [0, 0, 3]], cell=[8, 8, 20], pbc=True)
    for index in range(1, 11):
        write(output / f"{index:02d}_trial_001.cif", structure)
    job = jobs.Job(tmp_path / "job.yaml", None, jobs.METHODS["cluster_search"], {}, {}, tmp_path)
    status, _, checks, records = jobs._check_outputs(job)
    assert status in {"PASS", "WARN"}
    assert len(checks) == len(records) == 10
