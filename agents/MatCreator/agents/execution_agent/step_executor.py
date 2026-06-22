from __future__ import annotations

import logging
import os
from typing import List, Literal, Optional

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field, ValidationError, model_validator

from ...constants import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from ...skill import ALL_SKILLS_TOOLSET
from ...knowledge.query import search_skills,get_related_skills
from ...tools.remoteagent_tool import load_remote_a2a_agents
from ...tools.util_tools import show_artifact, show_plot, show_structure
from ...tools.workspace_tools import run_bash, run_python

logger = logging.getLogger(__name__)

_model_name = os.environ.get("LLM_MODEL", LLM_MODEL)
_model_api_key = os.environ.get("LLM_API_KEY", LLM_API_KEY)
_model_base_url = os.environ.get("LLM_BASE_URL", LLM_BASE_URL)


class StepExecutorInput(BaseModel):
    step_number: int = Field(description="1-based index of this step in the plan")
    action: str = Field(description="Action description from the plan step")
    suggested_skills: List[str] = Field(description="Ordered list of skill names suggested by the planner for this step")
    workspace_dir: str = Field(description="Absolute path to the session workspace directory")
    prior_context: Optional[str] = Field(
        default=None,
        description="Condensed summaries of prior completed steps for context",
    )


class StepExecutorResult(BaseModel):
    status: Literal["success", "needs_replanning"]
    key_results: str = Field(
        default="",
        description="Bullet-point list of key findings, values, and produced files",
    )
    artifacts: list[str] = Field(
        default_factory=list,
        description="Absolute paths of generated files or artifacts",
    )
    concise_summary: str = Field(
        default="",
        description="Short user-facing paragraph describing what was done",
    )
    replan_reason: Optional[str] = Field(
        default=None,
        description="Why replanning is needed (only set when status=needs_replanning)",
    )

    @model_validator(mode="after")
    def _fill_missing_fields(self) -> "StepExecutorResult":
        # If the LLM returned only one of the two summary fields, mirror it to the other.
        if not self.key_results and self.concise_summary:
            self.key_results = self.concise_summary
        elif not self.concise_summary and self.key_results:
            self.concise_summary = self.key_results
        return self


_STEP_EXECUTOR_INSTRUCTION = """
You are a focused step executor. Execute the single plan step provided in your input.

## Your task
1. Review `suggested_skills` from your input. Call `load_skill` for each skill you deem
   relevant to the action. Use `search_skills` to discover additional skills if the
   suggested list is insufficient.
2. Decompose task into sub-tasks. Directly execute them (**simple** cases) or **Delegate** them to child executors by calling `run_sub_agent` tool (**complex** cases).
       
## Reporting results (REQUIRED)
When done, call `submit_step_result` with:
- `status`: "success" or "needs_replanning"
- `key_results`: bullet-point list of key findings, values, and produced files
- `concise_summary`: short user-facing paragraph describing what was done
- `artifacts`: list of absolute paths of all generated files
- `replan_reason`: why replanning is needed (only when status=needs_replanning, else omit)

If `submit_step_result` returns a validation error, fix the fields and call it again.

## Execution rules
- Work inside `workspace_dir` for all file operations.
- Use `run_python` or `run_bash` for computation. Do not fabricate outputs.
- Include ALL generated files with their absolute paths in `artifacts`.
- Do not retry indefinitely on failure — call `submit_step_result` with needs_replanning.
"""


async def run_sub_agent(
    step_number: int,
    action: str,
    suggested_skills: List[str],
    tool_context: ToolContext,
    prior_context: Optional[str] = None,
) -> dict:
    """Spawn a child step executor to handle a sub-task.

    Call once per sub-task. For truly independent sub-tasks, issue multiple
    `run_sub_agent` calls in a SINGLE response turn — the runtime executes them
    concurrently. For dependent sub-tasks, call sequentially and pass the returned
    result as `prior_context` to the next call.

    Returns a result dict with keys: status, key_results, concise_summary, artifacts.
    If status is "cancelled", call submit_step_result with needs_replanning immediately.

    Args:
        step_number: Sub-task index (1-based, unique within this step)
        action: What the sub-task should do
        suggested_skills: Skills to preload in the child executor
        prior_context: Summary of earlier sub-tasks' results (for sequential chains)
    """
    from .step_executor_runner import run_step_executor  # lazy import avoids circular dep

    return await run_step_executor(
        step_number=step_number,
        action=action,
        suggested_skills=suggested_skills,
        workspace_dir="",  # computed internally by run_step_executor
        prior_context=prior_context,
        tool_context=tool_context,
    )


def submit_step_result(
    status: str,
    key_results: str,
    concise_summary: str,
    tool_context: ToolContext,
    artifacts: Optional[List[str]] = None,
    replan_reason: Optional[str] = None,
) -> dict:
    """Submit the result of this step execution.

    Call this tool when you have finished executing the step. Replaces writing
    a JSON response. If validation fails, fix the reported fields and retry.

    Args:
        status: "success" or "needs_replanning"
        key_results: Bullet-point list of key findings and produced files
        concise_summary: Short user-facing paragraph describing what was done
        artifacts: Absolute paths of all generated files (empty list if none)
        replan_reason: Why replanning is needed (only when status=needs_replanning)
    """
    try:
        result = StepExecutorResult(
            status=status,  # type: ignore[arg-type]
            key_results=key_results,
            concise_summary=concise_summary,
            artifacts=artifacts or [],
            replan_reason=replan_reason,
        )
        tool_context.state["_step_result"] = result.model_dump()
        return {"status": "ok", "message": "Step result submitted successfully."}
    except ValidationError as exc:
        return {
            "status": "error",
            "errors": exc.errors(),
            "message": "Validation failed. Fix the errors and call submit_step_result again.",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Unexpected error: {exc}"}


step_executor_agent = LlmAgent(
    name="step_executor",
    model=LiteLlm(
        model=_model_name,
        base_url=_model_base_url,
        api_key=_model_api_key,
    ),
    description=(
        "Executes a single plan step in an isolated session. "
        "Receives structured input with action and skill name; loads skill instructions autonomously."
    ),
    instruction=_STEP_EXECUTOR_INSTRUCTION,
    input_schema=StepExecutorInput,
    tools=[
        FunctionTool(run_sub_agent),
        FunctionTool(submit_step_result),
        FunctionTool(search_skills),
        FunctionTool(get_related_skills),
        FunctionTool(run_python),
        FunctionTool(run_bash),
        ALL_SKILLS_TOOLSET,
        FunctionTool(show_plot),
        FunctionTool(show_structure),
        FunctionTool(show_artifact),
    ],
    sub_agents=load_remote_a2a_agents(),
)
