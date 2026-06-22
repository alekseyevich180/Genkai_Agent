"""Markdown-backed workflow skills and search utilities for MatCreator.

Skills are now loaded in standard ADK format via the top-level skill.py
(google.adk.skills.load_skill_from_dir).  This module bridges ADK Skill
objects to the interface expected by the planning/execution agents and keeps
the guide system unchanged.
"""


import logging

from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
from google.adk.tools.function_tool import FunctionTool
from .workspace import workspace_skills_dir
from .tools.workspace_tools import list_workspace_skills, run_skill_script
from .config import get_planning_skills
from pathlib import Path

logger = logging.getLogger(__name__)


def _discover_skill_dirs(skills_root: Path) -> list[Path]:
    """Return every directory under *skills_root* that contains ``SKILL.md``.

    This supports both the original one-level layout::

        skills/<name>/SKILL.md

    and nested skill bundles such as::

        skills/mattergen/mattergen_generation/SKILL.md
    """
    if not skills_root.exists():
        return []

    skill_dirs = {
        skill_md.parent
        for skill_md in skills_root.rglob("SKILL.md")
        if skill_md.is_file()
    }
    return sorted(skill_dirs, key=lambda path: path.relative_to(skills_root).as_posix())


_MODULE_SKILLS_ROOT = Path(__file__).parent / "skills"


def get_default_skill_names() -> set[str]:
    """Return the set of skill names bundled with the module (not workspace overrides)."""
    return {p.name for p in _discover_skill_dirs(_MODULE_SKILLS_ROOT)}


def load_skills() -> list:
    """Load default module skills plus workspace custom skills.

    Custom skills whose name collides with a default skill are rejected with a warning.
    """
    default_names: set[str] = set()
    skills = []
    for path in _discover_skill_dirs(_MODULE_SKILLS_ROOT):
        default_names.add(path.name)
        try:
            skills.append(load_skill_from_dir(path))
        except Exception as exc:
            logger.error("Failed to load default skill '%s', skipping: %s", path.name, exc)
    for path in _discover_skill_dirs(workspace_skills_dir()):
        if path.name in default_names:
            logger.warning(
                "Custom skill '%s' in workspace conflicts with a default skill and will be ignored.",
                path.name,
            )
            continue
        try:
            skills.append(load_skill_from_dir(path))
        except Exception as exc:
            logger.error("Failed to load custom skill '%s', skipping: %s", path.name, exc)
    return skills


ALL_SKILLS = load_skills()

_PLANNING_CATEGORIES = frozenset({"concepts", "guides"})


def _build_planning_skill_names() -> frozenset[str]:
    names: set[str] = set()
    for root in [_MODULE_SKILLS_ROOT, workspace_skills_dir()]:
        for path in _discover_skill_dirs(root):
            if path.parent.name in _PLANNING_CATEGORIES:
                names.add(path.name)
    for name in get_planning_skills():
        names.add(name)
    return frozenset(names)


PLANNING_SKILL_NAMES: set[str] = set(_build_planning_skill_names())


class MatCreatorSkillToolset(skill_toolset.SkillToolset):
    """SkillToolset with workspace-aware list and run tools."""

    def __init__(self, skills: list):
        super().__init__(skills=skills)
        kept = [t for t in self._tools
                if t.__class__.__name__ in ('LoadSkillTool', 'LoadSkillResourceTool')]
        self._tools = [
            #FunctionTool(list_workspace_skills),
            *kept,
            FunctionTool(run_skill_script),
        ]

    async def process_llm_request(self, *, tool_context, llm_request) -> None:
        # Suppress the default XML skill-list injection; agents use search_skills instead.
        pass


ALL_SKILLS_TOOLSET = MatCreatorSkillToolset(ALL_SKILLS)


def seed_skills_to_graph() -> dict:
    """Upsert all workspace skills and guides into Know-Do Graph.

    Each node stores only name + description (from SKILL.md / guide frontmatter).
    Full instructions remain in the source files and are loaded via `load_skill`.
    Skill and guide nodes are marked immutable — they are dev-maintained and will
    not be silently updated by the extractor or synthesizer.

    After all nodes are seeded, ``depends_on`` edges are created between skill
    nodes based on the ``dependent_skills`` field in each SKILL.md's metadata.
    """
    from know_do_graph import (
        EdgeRelation,
        EntryMetadata,
        EntryType,
        RefinementStatus,
        VerificationStatus,
    )
    from .knowledge.kdg_memory import connect_once, upsert_entry
    from .knowledge.query import _get_kg
    from .guide import ALL_GUIDES

    kg = _get_kg()
    seeded = 0
    skill_node_ids: dict[str, str] = {}

    for skill in ALL_SKILLS:
        node, created = upsert_entry(
            kg,
            title=skill.name,
            content=skill.description or "",
            entry_type=EntryType.capability,
            tags=["matcreator-skill", "managed"],
            metadata=EntryMetadata(
                source_provenance="SKILL.md",
                refinement_status=RefinementStatus.validated,
                verification_status=VerificationStatus.peer_reviewed,
                custom={"managed_by": "matcreator", "kind": "skill"},
            ),
        )
        skill_node_ids[skill.name] = node.id
        seeded += int(created)

    for guide in ALL_GUIDES:
        _, created = upsert_entry(
            kg,
            title=guide.name,
            content=guide.description or "",
            entry_type=EntryType.procedure,
            tags=["matcreator-skill", "matcreator-guide", "managed"],
            metadata=EntryMetadata(
                source_provenance="guide",
                refinement_status=RefinementStatus.validated,
                verification_status=VerificationStatus.peer_reviewed,
                custom={"managed_by": "matcreator", "kind": "guide"},
            ),
        )
        seeded += int(created)

    # Create dependency edges from dependent_skills metadata
    edges_created = 0
    for skill in ALL_SKILLS:
        deps = (skill.frontmatter.metadata or {}).get("dependent_skills", [])
        src_id = skill_node_ids.get(skill.name)
        for dep_name in deps:
            tgt_id = skill_node_ids.get(dep_name)
            if src_id and tgt_id:
                edges_created += int(
                    connect_once(
                        kg,
                        src_id,
                        tgt_id,
                        relation=EdgeRelation.dependency,
                    )
                )
            else:
                logger.warning(
                    "dependent_skills: '%s' references unknown skill '%s'",
                    skill.name, dep_name,
                )

    kg.refresh()
    return {"status": "ok", "seeded": seeded, "edges_created": edges_created}


def refresh_skills() -> dict:
    """Reload all skills from the workspace and re-seed the knowledge graph.

    Call this after creating or modifying a skill to make it available
    in the current session without restarting.
    """
    new_skills = load_skills()
    ALL_SKILLS.clear()
    ALL_SKILLS.extend(new_skills)
    PLANNING_SKILL_NAMES.clear()
    PLANNING_SKILL_NAMES.update(_build_planning_skill_names())
    seed_result = seed_skills_to_graph()
    return {
        "status": "ok",
        "skills": [s.name for s in new_skills],
        "count": len(new_skills),
        "message": f"Refreshed {len(new_skills)} skills; seeded {seed_result['seeded']} nodes into knowledge graph.",
    }
