"""User intent validation tool for the ThinkingAgent.

Mirrors the validate_plan pattern: the agent infers intent inline, then calls
validate_intent to validate the schema and persist the goal to session state.
"""

from __future__ import annotations

import logging

from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class UserIntent(BaseModel):
    """Validated user intent."""

    goal: str = Field(
        ...,
        description="Single-sentence articulation of the user's goal/intent",
        max_length=300,
    )
    reasoning: str = Field(
        ...,
        description="Brief explanation of why you interpreted the goal this way",
    )


def validate_intent(intent: dict, tool_context: ToolContext) -> dict:
    """Validate and store the user's inferred goal to session state.

    Call this after determining the user's goal from the conversation.
    On success the goal is stored under the 'goal' session state key.
    On failure the validation errors are returned so you can fix and retry.

    Args:
        intent: Dict with 'goal' (single-sentence str, max 300 chars) and
                'reasoning' (brief str explaining the interpretation).
    """
    try:
        validated = UserIntent(**intent)
        tool_context.state["goal"] = validated.goal
        return {
            "status": "ok",
            "goal": validated.goal,
            "message": "User intent stored.",
        }
    except ValidationError as exc:
        return {
            "status": "error",
            "errors": exc.errors(),
            "message": "Intent validation failed. Fix the errors and re-call validate_intent.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Unexpected error: {exc}",
        }
