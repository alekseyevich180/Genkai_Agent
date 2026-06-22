"""Tester agent: creates, tests, and validates skills.

Responsibilities:
  1. Creating new skills from scratch (YAML frontmatter + instruction body)
  2. Writing self-contained test code for each skill
  3. Running tests and validating output quality
  4. Updating skills based on test outcomes (up to 3 retry attempts)
"""

from __future__ import annotations

import logging
import os

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.skills import models
from ...skill import ALL_SKILLS, ALL_SKILLS_TOOLSET, MatCreatorSkillToolset, refresh_skills
from ...constants import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from ...tools.workspace_tools import (
    create_skill,
    read_workspace_file,
    run_bash,
    run_python,
    write_workspace_file,
)

logger = logging.getLogger(__name__)

_model_name = os.environ.get("LLM_MODEL", LLM_MODEL)
_model_api_key = os.environ.get("LLM_API_KEY", LLM_API_KEY)
_model_base_url = os.environ.get("LLM_BASE_URL", LLM_BASE_URL)

# ---------------------------------------------------------------------------
# Instruction
# ---------------------------------------------------------------------------

_TESTER_AGENT_INSTRUCTION = """
You are the MatCreator Skill Tester. Your job is to create, test, and validate skills.

## Context
- Goal: {goal}
- Testing request: {tester_request}

## Workflow

### Creating a new skill
1. Call `list_skill_name_descriptions` to check if the skill already exists.
2. If any requirement, command, API, file format, scientific fact, or expected output is uncertain, you are able to use an available Tavily skill from `ALL_SKILLS_TOOLSET` to search for authoritative evidence.
3. Summarize the evidence you found and use it to ground the skill design. Do not invent unsupported details when search results are missing or ambiguous.
4. Design the skill: YAML frontmatter (name, description, tools, dependent_skills) + instruction body.
5. Call `create_skill(name, description, instruction)` to scaffold the skill file.
6. Write a small self-contained Python test to `skills/<name>/test_<name>.py` using `write_workspace_file`.
7. Run the test with `run_python` or `run_bash` and inspect the output.
8. If the test passes, report success with the skill file path.
9. If the test fails, update the skill instruction with `write_workspace_file` and retry (max 3 attempts).

### Testing an existing skill
1. Call `load_skill_content(skill_name)` to read the current instruction.
2. If the skill relies on uncertain external facts, commands, APIs, or recent information, you are able to use an available Tavily skill from `ALL_SKILLS_TOOLSET` to verify them before modifying the skill or its test.
3. Write a targeted test script that exercises the skill's key operations.
4. Run the test and analyse the output.
5. Report a clear pass/fail verdict with supporting evidence.

## Skill file format
```
---
name: <snake_case_name>
description: <one-sentence description for the planner>
tools: [<tool1>, <tool2>]
dependent_skills: []
---
<Markdown instruction body>
```

## Rules
- Skills must use snake_case names with no spaces.
- Test code must be self-contained and reproducible.
- Always report the absolute file path of created or modified skills.
- Keep skill instructions concise and tool-specific.
- Do not overwrite an existing skill — use `write_workspace_file` to update the `.md` file directly.
- When unsure, search first with Tavily and ground your answer in the retrieved evidence.
- Never fabricate commands, flags, APIs, data formats, URLs, or scientific claims.
"""

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


def _tester_before_agent_callback(callback_context: CallbackContext) -> None:
    """Ensure tester_request is present in state."""
    if "tester_request" not in callback_context.state:
        callback_context.state["tester_request"] = ""


# ---------------------------------------------------------------------------
# Agent instance
# ---------------------------------------------------------------------------



## Create a "skill creator" skill.

skill_creator = models.Skill(
    frontmatter=models.Frontmatter(
        name="skill-creator",
        description=(
            "Creates new ADK-compatible skill definitions from requirements."
            " Generates complete SKILL.md files following the Agent Skills"
            " specification at agentskills.io."
        ),
    ),
    instructions=(
        "When asked to create a new skill, generate a complete SKILL.md file.\n\n"
        "Read `references/skill-spec.md` for the format specification.\n"
        "Read `references/example-skill.md` for a working example.\n\n"
        "Follow these rules:\n"
        "1. Name must be kebab-case, max 64 characters\n"
        "2. Description must be under 1024 characters\n"
        "3. Instructions should be clear, step-by-step\n"
        "4. Reference files in references/ for detailed domain knowledge\n"
        "5. Keep SKILL.md under 500 lines, put details in references/\n"
        "6. Output the complete file content the user can save directly\n"
    ),
    resources=models.Resources(
        references={
            "skill-spec.md": "# Agent Skills Specification (agentskills.io)...",
            "example-skill.md": "# Example: Code Review Skill...",
        }
    ),
)

skill_creator_tool = MatCreatorSkillToolset([skill_creator])



tester_agent = LlmAgent(
    name="tester_agent",
    model=LiteLlm(
        model=_model_name,
        base_url=_model_base_url,
        api_key=_model_api_key,
    ),
    description=(
        "Creates new skills from scratch, writes test code, executes tests, and validates "
        "that skills work correctly. Invoked when a skill needs to be developed or validated."
    ),
    instruction=_TESTER_AGENT_INSTRUCTION,
    tools=[
        FunctionTool(create_skill),
        FunctionTool(write_workspace_file),
        FunctionTool(read_workspace_file),
        FunctionTool(run_python),
        FunctionTool(run_bash),
        skill_creator_tool,
        ALL_SKILLS_TOOLSET,
        FunctionTool(refresh_skills),
    ],
    before_agent_callback=_tester_before_agent_callback,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
