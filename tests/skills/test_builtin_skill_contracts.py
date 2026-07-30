from pathlib import Path

from google.adk.skills import load_skill_from_dir

from genkai.skills.contract import load_skill_contract, validate_skill_contract


ROOT = Path(__file__).parents[2]
SKILLS_ROOT = ROOT / "agents" / "Agent" / "skills"
CORE_SKILLS = {
    "paperread",
    "ptomodel",
    "surface-modeling",
    "vasp",
    "mace",
    "deepmd",
    "uma",
}


def test_core_skills_remain_loadable_and_uniquely_named() -> None:
    loaded = [
        load_skill_from_dir(SKILLS_ROOT / name)
        for name in sorted(CORE_SKILLS)
    ]

    assert {skill.name for skill in loaded} == CORE_SKILLS


def test_core_skill_contracts_and_evaluations_are_valid() -> None:
    known_skills = {
        path.name for path in SKILLS_ROOT.iterdir() if (path / "SKILL.md").is_file()
    }
    for name in CORE_SKILLS:
        contract = load_skill_contract(SKILLS_ROOT / name)
        report = validate_skill_contract(contract, known_skills)
        assert report.passed, (name, report.errors)
        assert set(contract.evaluations) == {"positive", "negative", "boundary"}
        assert all(contract.evaluations[kind] for kind in contract.evaluations)
