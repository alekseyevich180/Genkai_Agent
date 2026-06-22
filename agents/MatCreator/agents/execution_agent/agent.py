from __future__ import annotations

import logging
import os
from typing import List, Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from ...constants import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from ...workspace import get_session_workdir
from ..thinking_agent.summarize import validate_summarize
from ..thinking_agent.planning import (
    get_ready_nodes,
    set_node_status,
    mark_dependents_blocked,
)
from .step_executor_runner import run_step_executor

logger = logging.getLogger(__name__)

_model_name = os.environ.get("LLM_MODEL", LLM_MODEL)
_model_api_key = os.environ.get("LLM_API_KEY", LLM_API_KEY)
_model_base_url = os.environ.get("LLM_BASE_URL", LLM_BASE_URL)

# ---------------------------------------------------------------------------
# Instruction
# ---------------------------------------------------------------------------

_EXECUTION_ORCHESTRATOR_INSTRUCTION = """
You are the MatCreator Execution Orchestrator. You manage the full execution of a DAG-based plan.

## Context
- Goal: {goal}
- Execution graph: {execution_graph}
- Workspace directory: {workspace_dir}
- Prior trajectory: {summarize}

## Protocol
1. Call `get_ready_nodes()` to find all pending nodes whose predecessors are all 'success'.
2. For each ready node, call `run_node_executor` with:
   - `node_id`: the node's ID string
   - `action`: the node's action text
   - `suggested_skills`: the list of suggested skill names
   - `workspace_dir`: the workspace directory above
   - `prior_context`: a brief summary of relevant predecessor results (from trajectory, if any)
3. **Parallelize independent nodes**: if multiple nodes are ready and they work on different
   data or use different skills, issue ALL their `run_node_executor` calls in a SINGLE response
   turn so the ADK runtime executes them concurrently. Wait for all results before proceeding.
4. After each `run_node_executor` result:
   - `status == "success"`:
       a. Call `validate_summarize` with key_results, artifacts, concise_summary.
       b. Call `set_node_status(node_id="...", status="success", result=<concise_summary>)`.
   - `status == "needs_replanning"`:
       a. Call `set_node_status(node_id="...", status="failed", result=<replan_reason>)`.
       b. Call `mark_dependents_blocked(failed_node_id="...")`.
       c. Call `to_planner(reason=<replan_reason>)`. STOP — do not run any further nodes.
   - `status == "cancelled"`:
       a. Call `to_planner("execution cancelled by user")`. STOP.
5. After handling all results from a batch, call `get_ready_nodes()` again.
6. Continue until `get_ready_nodes()` returns count == 0. Execution is then complete.

## Rules
- NEVER execute code directly — all work goes through `run_node_executor`.
- When a batch has both successes and one failure, process the success nodes first
  (validate_summarize + set_node_status), then handle the failure last (set_node_status,
  mark_dependents_blocked, to_planner).
- Always use absolute file paths in artifact lists.
"""

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def to_planner(reason: str, tool_context: ToolContext) -> dict:
    """Signal the main orchestrator to abort execution and return to planning.

    Call when a step cannot proceed and replanning or user input is needed.

    Args:
        reason: Short explanation of why replanning is needed.
    """
    tool_context.state["return_to_planner"] = True
    tool_context.state["return_to_planner_reason"] = reason
    logger.info("[execution_orchestrator] to_planner — reason: %s", reason)
    return {"status": "ok", "message": f"Returning to planner: {reason}"}


async def run_node_executor(
    node_id: str,
    action: str,
    suggested_skills: List[str],
    workspace_dir: str,
    prior_context: Optional[str] = None,
    *,
    tool_context: ToolContext,
) -> dict:
    """Run a single graph node as an isolated step executor sub-agent.

    For independent nodes, issue multiple calls in a SINGLE response turn
    to execute them concurrently.

    Args:
        node_id:          The node's ID from the execution graph (e.g. 'step_relax_geometry').
        action:           The node's action text.
        suggested_skills: Skill names from the graph node.
        workspace_dir:    Absolute path to the session workspace.
        prior_context:    Brief summary of predecessor results for context.
    """
    counter = tool_context.state.get("_node_exec_counter", 0) + 1
    tool_context.state["_node_exec_counter"] = counter
    return await run_step_executor(
        step_number=counter,
        action=action,
        suggested_skills=suggested_skills,
        workspace_dir=workspace_dir,
        prior_context=prior_context,
        node_id=node_id,
        tool_context=tool_context,
    )


# ---------------------------------------------------------------------------
# Callback
# ---------------------------------------------------------------------------


def _exec_before_agent_callback(callback_context: CallbackContext) -> None:
    """Initialise execution-phase state before the LLM runs."""
    state = callback_context.state

    for key, default in [
        ("goal", None),
        ("execution_graph", None),
        ("summarize", None),
        ("trajectory_step", 0),
        ("return_to_planner", False),
        ("return_to_planner_reason", None),
        ("_node_exec_counter", 0),
    ]:
        if key not in state:
            state[key] = default

    session_id = state.get("session_id", "default")
    state["workspace_dir"] = str(get_session_workdir(session_id))


# ---------------------------------------------------------------------------
# Agent instance
# ---------------------------------------------------------------------------

execution_agent = LlmAgent(
    name="execution_orchestrator",
    model=LiteLlm(
        model=_model_name,
        base_url=_model_base_url,
        api_key=_model_api_key,
    ),
    include_contents="none",
    description=(
        "Orchestrates execution of a DAG-based plan by spawning isolated step_executor sub-agents. "
        "Handles parallel node dispatch, status tracking, and error escalation to the planner."
    ),
    instruction=_EXECUTION_ORCHESTRATOR_INSTRUCTION,
    tools=[
        FunctionTool(run_node_executor),
        FunctionTool(to_planner),
        FunctionTool(validate_summarize),
        FunctionTool(get_ready_nodes),
        FunctionTool(set_node_status),
        FunctionTool(mark_dependents_blocked),
    ],
    before_agent_callback=_exec_before_agent_callback,
)
