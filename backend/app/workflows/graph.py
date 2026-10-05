"""The DevForge SDLC graph (LangGraph).

    START
      -> requirement_agent -> requirements_approval ──approve──▶ architecture_agent
                                       ▲                              │
                                       └────────changes/reject────────┘
      architecture_agent -> architecture_approval ──approve──▶ developer_agent
                                       ▲                              │
                                       └────────changes/reject────────┘
      developer_agent -> code_review ──approve──▶ testing_agent
                                       ▲                  │
                                       └──changes─────────┘
      testing_agent ──failures──▶ developer_agent (bounded fix loop)
                     └──green───▶ test_review ──approve──▶ security_agent
      security_agent -> security_review ──approve──▶ documentation_agent
                                       └──changes──▶ developer_agent (remediation)
      documentation_agent -> documentation_approval ──approve──▶ delivery -> finalize -> END

Every approval node suspends the graph with ``interrupt`` — no stage can advance
without a recorded human decision, and each stage has a bounded revision budget
after which the graph escalates to the human instead of looping forever.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.models.enums import ApprovalDecision, Stage, StageStatus
from app.workflows import nodes
from app.workflows.state import DevForgeState

logger = get_logger("devforge.workflow.graph")

CHECKPOINTER_SINGLETON: Any = None


def get_checkpointer() -> Any:
    """Return the orchestration checkpointer (durable when configured).

    ``sqlite`` keeps suspended runs across backend restarts; ``memory`` is used for
    tests and single-shot CLI runs; ``postgres`` requires the optional
    ``langgraph-checkpoint-postgres`` package (see requirements.txt).
    """
    global CHECKPOINTER_SINGLETON
    if CHECKPOINTER_SINGLETON is not None:
        return CHECKPOINTER_SINGLETON

    backend = (settings.checkpoint_backend or "sqlite").lower()
    if backend == "memory":
        logger.info("Workflow checkpointer: in-memory (runs do not survive a restart)")
        CHECKPOINTER_SINGLETON = InMemorySaver()
        return CHECKPOINTER_SINGLETON

    if backend == "postgres":
        try:  # pragma: no cover - optional dependency
            from langgraph.checkpoint.postgres import PostgresSaver

            logger.info("Workflow checkpointer: postgres")
            CHECKPOINTER_SINGLETON = PostgresSaver.from_conn_string(settings.database_url)
            return CHECKPOINTER_SINGLETON
        except Exception as exc:  # pragma: no cover
            raise ConfigurationError(
                "CHECKPOINT_BACKEND=postgres requires langgraph-checkpoint-postgres to be installed."
            ) from exc

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        connection = sqlite3.connect(settings.checkpoint_path, check_same_thread=False)
        saver = SqliteSaver(connection)
        saver.setup()
        logger.info("Workflow checkpointer: sqlite (%s)", settings.checkpoint_path)
        CHECKPOINTER_SINGLETON = saver
    except Exception as exc:  # pragma: no cover - fallback path
        logger.warning("SQLite checkpointer unavailable (%s) — using in-memory checkpoints.", exc)
        CHECKPOINTER_SINGLETON = InMemorySaver()
    return CHECKPOINTER_SINGLETON


def reset_checkpointer() -> None:
    global CHECKPOINTER_SINGLETON
    CHECKPOINTER_SINGLETON = None


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
def _revision_route(state: DevForgeState, *, rework_node: str, forward_node: str) -> str:
    """Approve → forward; otherwise re-run the agent, or escalate when out of budget."""
    decision = state.get("approval_status", "")
    stage = state.get("current_stage", "")
    iterations = (state.get("iterations") or {}).get(stage, 0)
    budget = int(state.get("max_stage_iterations", 3) or 3)

    if decision == ApprovalDecision.APPROVE.value:
        return forward_node
    if iterations >= budget:
        logger.warning("Stage %s exhausted its revision budget (%s)", stage, iterations)
        return "escalate"
    return rework_node


def after_requirements_approval(state: DevForgeState) -> str:
    return _revision_route(state, rework_node="requirement_agent", forward_node="architecture_agent")


def after_architecture_approval(state: DevForgeState) -> str:
    return _revision_route(state, rework_node="architecture_agent", forward_node="developer_agent")


def after_code_review(state: DevForgeState) -> str:
    results = state.get("test_results") or {}
    source_changes = state.get("source_changes") or {}
    if (
        state.get("approval_status") == ApprovalDecision.APPROVE.value
        and (results.get("status") or "").upper() in {"FAILED", "ERROR"}
        and not (source_changes.get("additions") or source_changes.get("deletions"))
    ):
        logger.warning(
            "Developer Agent proposed no effective changes for a failing test run; escalating "
            "instead of rerunning the same tests"
        )
        return "escalate"
    return _revision_route(state, rework_node="developer_agent", forward_node="testing_agent")


def after_testing(state: DevForgeState) -> str:
    """Failures go back to the Developer Agent automatically (bounded)."""
    results = state.get("test_results") or {}
    status = (results.get("status") or "").upper()
    iterations = (state.get("iterations") or {}).get(Stage.TESTING.value, 0)
    budget = int(state.get("max_stage_iterations", 3) or 3)
    if status in {"FAILED", "ERROR"} and iterations < budget:
        return "developer_agent"
    if status in {"FAILED", "ERROR"}:
        return "escalate"
    return "test_review"


def after_test_review(state: DevForgeState) -> str:
    return _revision_route(state, rework_node="developer_agent", forward_node="security_agent")


def after_security_review(state: DevForgeState) -> str:
    return _revision_route(state, rework_node="developer_agent",
                           forward_node="documentation_agent")


def after_documentation_approval(state: DevForgeState) -> str:
    return _revision_route(state, rework_node="documentation_agent", forward_node="delivery")


def after_finalize(state: DevForgeState) -> str:  # pragma: no cover - terminal
    return END


# --------------------------------------------------------------------------- #
# graph construction
# --------------------------------------------------------------------------- #
def build_workflow_graph(checkpointer: Any | None = None):
    """Compile the DevForge SDLC graph."""
    graph = StateGraph(DevForgeState)

    # stages
    graph.add_node("requirement_agent", nodes.requirement_agent_node)
    graph.add_node("architecture_agent", nodes.architecture_agent_node)
    graph.add_node("developer_agent", nodes.developer_agent_node)
    graph.add_node("testing_agent", nodes.testing_agent_node)
    graph.add_node("security_agent", nodes.security_agent_node)
    graph.add_node("documentation_agent", nodes.documentation_agent_node)
    # human gates
    graph.add_node("requirements_approval", nodes.requirements_approval_node)
    graph.add_node("architecture_approval", nodes.architecture_approval_node)
    graph.add_node("code_review", nodes.code_review_node)
    graph.add_node("test_review", nodes.test_review_node)
    graph.add_node("security_review", nodes.security_review_node)
    graph.add_node("documentation_approval", nodes.documentation_approval_node)
    # delivery and control
    graph.add_node("delivery", nodes.delivery_node)
    graph.add_node("finalize", nodes.finalize_node)
    graph.add_node("escalate", nodes.escalate_node)

    graph.add_edge(START, "requirement_agent")
    graph.add_edge("requirement_agent", "requirements_approval")
    graph.add_conditional_edges("requirements_approval", after_requirements_approval, {
        "architecture_agent": "architecture_agent",
        "requirement_agent": "requirement_agent",
        "escalate": "escalate",
    })
    graph.add_edge("architecture_agent", "architecture_approval")
    graph.add_conditional_edges("architecture_approval", after_architecture_approval, {
        "developer_agent": "developer_agent",
        "architecture_agent": "architecture_agent",
        "escalate": "escalate",
    })
    graph.add_edge("developer_agent", "code_review")
    graph.add_conditional_edges("code_review", after_code_review, {
        "testing_agent": "testing_agent",
        "developer_agent": "developer_agent",
        "escalate": "escalate",
    })
    graph.add_conditional_edges("testing_agent", after_testing, {
        "developer_agent": "developer_agent",
        "test_review": "test_review",
        "escalate": "escalate",
    })
    graph.add_conditional_edges("test_review", after_test_review, {
        "security_agent": "security_agent",
        "developer_agent": "developer_agent",
        "escalate": "escalate",
    })
    graph.add_edge("security_agent", "security_review")
    graph.add_conditional_edges("security_review", after_security_review, {
        "documentation_agent": "documentation_agent",
        "developer_agent": "developer_agent",
        "escalate": "escalate",
    })
    graph.add_edge("documentation_agent", "documentation_approval")
    graph.add_conditional_edges("documentation_approval", after_documentation_approval, {
        "delivery": "delivery",
        "documentation_agent": "documentation_agent",
        "escalate": "escalate",
    })
    graph.add_edge("delivery", "finalize")
    graph.add_edge("finalize", END)
    graph.add_edge("escalate", END)

    return graph.compile(checkpointer=checkpointer or get_checkpointer())


STAGE_FOR_NODE = {
    "requirement_agent": Stage.REQUIREMENTS.value,
    "architecture_agent": Stage.ARCHITECTURE.value,
    "developer_agent": Stage.DEVELOPMENT.value,
    "testing_agent": Stage.TESTING.value,
    "security_agent": Stage.SECURITY.value,
    "documentation_agent": Stage.DOCUMENTATION.value,
}
