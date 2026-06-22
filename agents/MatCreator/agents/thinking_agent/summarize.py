"""Step summary validation tool shared by ThinkingAgent and ExecutionAgent.

Mirrors the validate_plan pattern: the agent generates the summary inline, then
calls validate_summarize to validate the schema, persist to session state, and
append a trajectory entry.
"""

from __future__ import annotations

import logging
from typing import List

from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field, ValidationError

from .trajectory import append_trajectory_entry

logger = logging.getLogger(__name__)


class StepSummary(BaseModel):
    """Validated outcome summary for a completed execution step."""

    key_results: str = Field(
        ...,
        description="Concise summary of what was produced or learned",
    )
    artifacts: List[str] = Field(
        default_factory=list,
        description="Absolute paths or IDs of important generated files",
    )
    concise_summary: str = Field(
        ...,
        description="User-facing one-paragraph summary of the step outcome",
    )


def validate_summarize(summarize: dict, tool_context: ToolContext) -> dict:
    """Validate and store the step summary to session state.

    Call this after completing a significant execution step. Provide the key
    results, artifact paths, and a user-facing summary. On success the data is
    stored under the 'summarize' session state key and a trajectory entry is
    appended. On failure validation errors are returned so you can fix and retry.

    Args:
        summarize: Dict with 'key_results' (str), 'artifacts' (list of str),
                   and 'concise_summary' (str).
    """
    try:
        validated = StepSummary(**summarize)
        data = validated.model_dump()
        tool_context.state["summarize"] = data

        try:
            session_id = tool_context._invocation_context.session.id
            step_index = (tool_context.state.get("trajectory_step") or 0) + 1
            tool_context.state["trajectory_step"] = step_index
            log_path = append_trajectory_entry(
                session_id=session_id,
                step_index=step_index,
                goal=tool_context.state.get("goal"),
                active_skill=tool_context.state.get("active_skill"),
                summarize_response=data,
            )
            logger.info("Trajectory entry %d written to %s", step_index, log_path)
        except Exception as exc:
            logger.warning("Failed to write trajectory entry: %s", exc)

        return {
            "status": "ok",
            "summarize": data,
            "message": "Step summary stored.",
        }
    except ValidationError as exc:
        return {
            "status": "error",
            "errors": exc.errors(),
            "message": "Summary validation failed. Fix the errors and re-call validate_summarize.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Unexpected error: {exc}",
        }
