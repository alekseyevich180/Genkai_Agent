"""Planning-Execution Orchestrator for MatCreator.

Every invocation runs a planning-first loop:

  1. Planning phase  — always runs first. planning_agent (thinking_agent) handles
                       user intent and sets one of two routing flags:
                         • state["execution_approved"] = True  → execution phase
                         • state["testing_requested"]  = True  → testing phase
                       If neither flag is set the turn was conversational; the loop
                       exits and control returns to the user.

  2. Execution phase — delegates the full plan to execution_agent (an LlmAgent that
                       spawns isolated step_executor sub-agents and may run steps in
                       parallel). Terminates early if execution_agent calls `to_planner`
                       (sets state["return_to_planner"] = True).
                       After all steps complete (or on early exit), loops back to
                       the planning phase within the same invocation.

  3. Testing phase   — delegates to tester_agent for skill creation/validation, then
                       loops back to the planning phase.
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event
from pydantic import Field

from ...workspace import init_session_workdir
from ..graph_logger import AgentGraphLogger
from ..cancellation import clear_cancellation
from ...knowledge.extractor import run_knowledge_extractor
from ...knowledge.synthesizer import run_knowledge_synthesizer
from ...knowledge.kg_state import increment_exec_count, record_synthesizer_run

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_agent_mode(state: dict) -> str:
    """Return the active agent mode: 'flash', 'bench', or 'normal'."""
    mode = state.get("agent_mode")
    if mode in ("normal", "bench", "flash"):
        return mode
    return "bench" if state.get("benchmark_mode", False) else "normal"


def _validate_graph_ready(state: dict) -> tuple[bool, str]:
    """Return (ready, reason) — ready=True when at least one pending node exists."""
    graph = state.get("execution_graph")
    if not graph or not isinstance(graph, dict):
        return False, "No execution_graph in session state."
    nodes = graph.get("nodes") or {}
    if not nodes:
        return False, "Execution graph has no nodes."
    pending = [nid for nid, n in nodes.items() if n.get("status") == "pending"]
    if not pending:
        return False, f"No pending nodes (all {len(nodes)} node(s) are complete or blocked)."
    return True, f"{len(pending)} pending node(s) ready."


def _is_graph_complete(state: dict) -> bool:
    """Return True when every node in the graph reached 'success'."""
    nodes = (state.get("execution_graph") or {}).get("nodes") or {}
    return bool(nodes) and all(n.get("status") == "success" for n in nodes.values())


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class PlanningExecutionOrchestrator(BaseAgent):
    """Orchestrates the planning → execution loop.

    Attributes:
        planning_agent: Handles user intent, plan creation, and approval signalling.
        execution_agent: Executes one plan step at a time (skill load + tool calls).
        tester_agent: Creates and validates skills on demand (optional).
    """

    planning_agent: BaseAgent
    execution_agent: BaseAgent
    tester_agent: Optional[BaseAgent] = Field(default=None)

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if not state.get("session_workdir_initialized"):
            init_session_workdir(ctx.session.id)
            state["session_id"] = ctx.session.id
            state["session_workdir_initialized"] = True

        graph = AgentGraphLogger(ctx.session.id)
        graph.log_node_start("orchestrator", "orchestrator", "Orchestrator")

        loop_idx = graph.count_nodes_of_type("execution")

        while True:
            # ── Planning phase (always runs first) ───────────────────────────
            state["execution_approved"] = False
            has_execution = loop_idx > 0
            planning_id = f"planning_{loop_idx}" if has_execution else "planning_0"
            logger.info("[orchestrator] entering planning phase")
            graph.log_node_start(planning_id, "planning", f"Planning {loop_idx + 1}", "orchestrator")
            async for event in self.planning_agent.run_async(ctx):
                yield event
            graph.log_node_complete(planning_id, "success")

            # Flash mode: thinking agent handles everything; skip execution/testing phases
            if _get_agent_mode(state) == "flash":
                graph.log_node_complete("orchestrator", "success")
                break

            testing_requested: bool = state.get("testing_requested", False)
            execution_approved: bool = state.get("execution_approved", False)

            # ── Testing phase ─────────────────────────────────────────────────
            if testing_requested and self.tester_agent is not None:
                tester_id = f"tester_{loop_idx}" if has_execution else "tester_0"
                logger.info("[orchestrator] entering testing phase")
                graph.log_node_start(tester_id, "tester", f"Testing {loop_idx + 1}", "orchestrator")
                async for event in self.tester_agent.run_async(ctx):
                    yield event
                graph.log_node_complete(tester_id, "success")
                state["testing_requested"] = False
                continue  # loop back to planner

            # ── Execution phase ───────────────────────────────────────────────
            if execution_approved:
                ready, reason = _validate_graph_ready(state)
                if not ready:
                    logger.warning("[orchestrator] execution approved but: %s", reason)
                    state["execution_approved"] = False
                    continue  # loop back to planner

                total_nodes = len((state.get("execution_graph") or {}).get("nodes") or {})
                pending_count = sum(
                    1 for n in (state.get("execution_graph") or {}).get("nodes", {}).values()
                    if n.get("status") == "pending"
                )
                logger.info(
                    "[orchestrator] delegating %d/%d pending nodes to execution_orchestrator",
                    pending_count, total_nodes,
                )

                exec_id = f"execution_{loop_idx}"
                graph.log_node_start(exec_id, "execution", f"Execution {loop_idx + 1}", "orchestrator")
                state["_graph_exec_node_id"] = exec_id

                async for event in self.execution_agent.run_async(ctx):
                    yield event

                interrupted = state.get("return_to_planner", False)
                if interrupted:
                    reason = state.get("return_to_planner_reason", "unspecified")
                    logger.info(
                        "[orchestrator] execution interrupted — returning to planner (reason: %s)",
                        reason,
                    )
                    graph.log_node_complete(exec_id, "failed", summary=f"Interrupted: {reason}")
                    state["return_to_planner"] = False
                    state["return_to_planner_reason"] = None
                    clear_cancellation(state.get("session_id", ""))
                    if "cancel" in reason:
                        logger.warning(
                            "[CANCEL COMPLETE] Execution fully stopped for session %s — returning to planner",
                            state.get("session_id", ""),
                        )
                else:
                    logger.info("[orchestrator] all %d nodes complete", total_nodes)
                    graph.log_node_complete(exec_id, "success")
                    state["_node_exec_counter"] = 0

                    # Extract knowledge from the completed session
                    try:
                        extraction_result = run_knowledge_extractor(ctx.session.id)
                        logger.info("[orchestrator] knowledge extractor: %s", extraction_result.get("message"))

                        # Run synthesizer every 10 completed executions (counted across sessions)
                        exec_count = increment_exec_count()
                        if exec_count % 10 == 0:
                            synth_result = run_knowledge_synthesizer()
                            record_synthesizer_run()
                            logger.info("[orchestrator] knowledge synthesizer: %s", synth_result.get("message"))
                    except Exception as _kg_exc:
                        logger.warning("[orchestrator] knowledge extraction failed: %s", _kg_exc)

                state["execution_approved"] = False
                state["current_step"] = None
                loop_idx += 1
                continue  # loop back to planner

            # ── No flag set — planner handled the turn conversationally ───────
            # Exit the loop; in benchmark mode the planning agent is instructed to
            # call confirm_plan_and_start_execution directly, so no fallback needed.
            graph.log_node_complete("orchestrator", "success")
            break
