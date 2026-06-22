"""Plan validation tools for the ThinkingAgent.

Provides Pydantic-backed tool functions for creating and managing
DAG-based execution graphs and (legacy) linear execution plans.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional

from google.adk.tools.tool_context import ToolContext
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ...skill import ALL_SKILLS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy schemas (linear plan — kept for backward compatibility)
# ---------------------------------------------------------------------------


class PlanStep(BaseModel):
    """Single step in a linear execution plan."""

    step_number: int = Field(..., description="Sequential step number (1, 2, 3, ...)")
    suggested_skills: List[str] = Field(
        ...,
        description="Ordered list of skill names likely needed for this step. The executor may load additional skills as needed.",
        min_items=1,
    )
    action: str = Field(
        ...,
        description="Clear, concise description of what this step does (1-2 sentences). Each step should cover a meaningful chunk of work — avoid splitting a single logical operation into multiple steps.",
        max_length=500,
    )

    @field_validator("suggested_skills")
    @classmethod
    def _validate_skill_names(cls, values: List[str]) -> List[str]:
        allowed_names = {s.name for s in ALL_SKILLS}
        invalid = [v for v in values if v not in allowed_names]
        if invalid:
            allowed = ", ".join(sorted(allowed_names)) or "<none loaded>"
            raise ValueError(
                f"Invalid skill(s) {invalid}. Allowed skills are: {allowed}"
            )
        return values


class ExecutionPlan(BaseModel):
    """Structured linear execution plan for user approval (legacy)."""

    steps: List[PlanStep] = Field(
        ...,
        description="Ordered list of detailed steps in the CURRENT stage, ONLY includes DETERMINED steps",
        min_items=1,
        max_items=10,
    )
    additional_notes: str = Field(
        ...,
        description="Any extra information or considerations for the user",
        max_length=500,
    )


# ---------------------------------------------------------------------------
# DAG schemas
# ---------------------------------------------------------------------------


class NodeStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    blocked = "blocked"   # a predecessor failed; this node cannot run


class GraphNode(BaseModel):
    """A single node in an ExecutionGraph DAG."""

    node_id: str = Field(
        ...,
        description="Unique snake_case identifier, e.g. 'step_relax_geometry'",
    )
    label: str = Field(..., description="Short display name shown in the UI")
    action: str = Field(
        ...,
        max_length=500,
        description="1-2 sentence description of what this node does",
    )
    suggested_skills: List[str] = Field(..., min_items=1)
    status: NodeStatus = Field(default=NodeStatus.pending)
    result: Optional[str] = Field(default=None, description="Brief summary after completion or failure reason")

    @field_validator("suggested_skills")
    @classmethod
    def _validate_skill_names(cls, values: List[str]) -> List[str]:
        allowed_names = {s.name for s in ALL_SKILLS}
        invalid = [v for v in values if v not in allowed_names]
        if invalid:
            allowed = ", ".join(sorted(allowed_names)) or "<none loaded>"
            raise ValueError(
                f"Invalid skill(s) {invalid}. Allowed skills are: {allowed}"
            )
        return values


def _has_cycle(node_ids: list[str], edges: list[list[str]]) -> bool:
    """DFS cycle detection on a directed graph."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_ids}
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for edge in edges:
        adj[edge[0]].append(edge[1])

    def dfs(n: str) -> bool:
        color[n] = GRAY
        for nb in adj[n]:
            if color.get(nb) == GRAY:
                return True
            if color.get(nb) == WHITE and dfs(nb):
                return True
        color[n] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in node_ids)


class ExecutionGraph(BaseModel):
    """DAG-based execution plan where each node executes once all predecessors succeed."""

    nodes: Dict[str, GraphNode] = Field(
        ...,
        description="Mapping of node_id → GraphNode. All node_ids must be unique.",
        min_length=1,
        max_length=20,
    )
    edges: List[List[str]] = Field(
        default_factory=list,
        description="List of [predecessor_id, successor_id] pairs. predecessor must complete before successor starts.",
    )
    additional_notes: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _validate_graph_structure(self) -> "ExecutionGraph":
        for edge in self.edges:
            if len(edge) != 2:
                raise ValueError(f"Each edge must be a [from_id, to_id] pair, got: {edge}")
            if edge[0] not in self.nodes:
                raise ValueError(f"Edge references unknown node: '{edge[0]}'")
            if edge[1] not in self.nodes:
                raise ValueError(f"Edge references unknown node: '{edge[1]}'")
        if _has_cycle(list(self.nodes.keys()), self.edges):
            raise ValueError("Graph contains a cycle — ExecutionGraph must be a DAG.")
        return self


# ---------------------------------------------------------------------------
# validate_graph tool
# ---------------------------------------------------------------------------


def validate_graph(graph: dict, tool_context: ToolContext) -> dict:
    """Validate and commit an execution graph (DAG) to session state.

    Call after drafting the DAG plan to validate schema and persist it.
    On success the graph is stored under 'execution_graph' in session state.

    Args:
        graph: Dict with:
          - 'nodes': mapping of node_id → {node_id, label, action, suggested_skills}
          - 'edges': list of [predecessor_id, successor_id] pairs
                     (predecessor must complete before successor starts)
          - 'additional_notes': optional string
    """
    try:
        validated = ExecutionGraph(**graph)
        tool_context.state["execution_graph"] = validated.model_dump()
        tool_context.state["plan_exec_id"] = None  # force new execution namespace
        return {
            "status": "ok",
            "execution_graph": validated.model_dump(),
            "message": f"Graph validated: {len(validated.nodes)} nodes, {len(validated.edges)} edges.",
        }
    except ValidationError as exc:
        return {
            "status": "error",
            "errors": f"{exc}",
            "message": "Graph validation failed. Fix the errors and re-call validate_graph.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Unexpected error: {exc}",
        }


# ---------------------------------------------------------------------------
# get_ready_nodes tool
# ---------------------------------------------------------------------------


def get_ready_nodes(tool_context: ToolContext) -> dict:
    """Return all nodes whose predecessors are all 'success' and own status is 'pending'.

    Call at the start of each execution batch. Dispatch ALL returned nodes in a
    single response turn to enable concurrent parallel execution.
    """
    graph = tool_context.state.get("execution_graph") or {}
    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []

    predecessors: dict[str, set] = {nid: set() for nid in nodes}
    for edge in edges:
        if len(edge) == 2:
            predecessors.setdefault(edge[1], set()).add(edge[0])

    ready = []
    for node_id, node in nodes.items():
        if node.get("status") != "pending":
            continue
        if all(
            nodes.get(pred, {}).get("status") == "success"
            for pred in predecessors.get(node_id, set())
        ):
            ready.append({
                "node_id": node_id,
                "label": node.get("label", node_id),
                "action": node.get("action", ""),
                "suggested_skills": node.get("suggested_skills", []),
            })

    return {"status": "ok", "ready_nodes": ready, "count": len(ready)}


# ---------------------------------------------------------------------------
# set_node_status tool
# ---------------------------------------------------------------------------


def set_node_status(
    node_id: str,
    status: str,
    result: Optional[str] = None,
    *,
    tool_context: ToolContext,
) -> dict:
    """Update a graph node's status after execution.

    Call after each run_node_executor result to record the outcome.

    Args:
        node_id: The node's ID string in the execution graph.
        status:  New status: 'success', 'failed', 'running', 'blocked', or 'cancelled'.
        result:  Optional concise summary (success) or failure reason.
    """
    graph = tool_context.state.get("execution_graph")
    if not graph or node_id not in (graph.get("nodes") or {}):
        return {"status": "error", "message": f"Node '{node_id}' not found in execution_graph."}
    graph["nodes"][node_id]["status"] = status
    if result is not None:
        graph["nodes"][node_id]["result"] = result
    tool_context.state["execution_graph"] = graph
    logger.debug("[set_node_status] %s → %s", node_id, status)
    return {"status": "ok", "node_id": node_id, "new_status": status}


# ---------------------------------------------------------------------------
# mark_dependents_blocked tool
# ---------------------------------------------------------------------------


def mark_dependents_blocked(failed_node_id: str, tool_context: ToolContext) -> dict:
    """Mark all transitive successors of a failed node as 'blocked'.

    Call immediately after set_node_status(status='failed') and before to_planner.

    Args:
        failed_node_id: The node_id of the node that failed.
    """
    graph = tool_context.state.get("execution_graph") or {}
    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []

    successors: dict[str, list] = {nid: [] for nid in nodes}
    for edge in edges:
        if len(edge) == 2:
            successors.setdefault(edge[0], []).append(edge[1])

    blocked: set[str] = set()
    queue = list(successors.get(failed_node_id, []))
    while queue:
        nid = queue.pop(0)
        if nid in blocked:
            continue
        blocked.add(nid)
        queue.extend(successors.get(nid, []))

    for nid in blocked:
        if nodes.get(nid, {}).get("status") == "pending":
            nodes[nid]["status"] = "blocked"
    tool_context.state["execution_graph"] = graph
    return {
        "status": "ok",
        "blocked_count": len(blocked),
        "blocked_nodes": sorted(blocked),
    }


# ---------------------------------------------------------------------------
# Legacy validate_plan tool
# ---------------------------------------------------------------------------


def validate_plan(plan: dict, tool_context: ToolContext) -> dict:
    """Validate and commit a linear plan to session state.

    Deprecated: prefer validate_graph for DAG-based planning.

    Args:
        plan: Dict with 'steps' (list of {step_number, suggested_skills, action}) and
              'additional_notes' (str).
    """
    try:
        validated = ExecutionPlan(**plan)
        tool_context.state["plan"] = validated.model_dump()
        tool_context.state["plan_exec_id"] = None
        return {
            "status": "ok",
            "plan": validated.model_dump(),
            "message": f"Plan validated and saved with {len(validated.steps)} steps.",
        }
    except ValidationError as exc:
        return {
            "status": "error",
            "errors": f"{exc}",
            "message": "Plan validation failed. Fix the errors and re-call validate_plan.",
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Unexpected error: {exc}",
        }
