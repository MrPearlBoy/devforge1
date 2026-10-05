"""The DevForge orchestration state (shared memory of the agent team).

Every agent reads from and writes to this state through the LangGraph graph, which
is what makes the agents a collaborating team rather than isolated chatbots:

    Requirement Agent ──requirements──▶ Architecture Agent ──architecture──▶
    Developer Agent ──code──▶ Testing Agent ──results──▶ Security Agent ──findings──▶
    Developer Agent (fix loop) ──▶ Documentation Agent ──docs──▶ Delivery

Human decisions enter through ``approval`` and control every transition.
"""
from __future__ import annotations

from typing import Any, TypedDict

from app.models.enums import Stage, StageStatus, WorkflowStatus


class StageRecord(TypedDict, total=False):
    status: str
    iterations: int
    artifact_id: str | None
    artifact_title: str
    approval_id: str | None
    summary: str
    error: str
    started_at: str
    finished_at: str


class DevForgeState(TypedDict, total=False):
    """The graph's shared state."""

    # identity
    project_id: str
    run_id: str
    user_id: str
    thread_id: str

    # human input
    instructions: str

    # workflow position
    current_stage: str
    current_node: str
    status: str
    stage_records: dict[str, StageRecord]
    iterations: dict[str, int]
    max_stage_iterations: int
    total_steps: int

    # artifacts produced by the agents (ids + human-readable content)
    requirements: dict[str, Any]
    approved_requirements: str
    architecture: dict[str, Any]
    approved_architecture: str
    source_changes: dict[str, Any]
    applied_change_set_id: str
    test_results: dict[str, Any]
    security_results: dict[str, Any]
    documentation: dict[str, Any]

    # human control
    approval: dict[str, Any]
    approval_status: str
    pending_approval_id: str
    last_decision: dict[str, Any]

    # diagnostics
    messages: list[dict[str, Any]]
    errors: list[str]
    warnings: list[str]
    delivery: dict[str, Any]


def initial_state(
    *,
    project_id: str,
    run_id: str,
    user_id: str,
    thread_id: str,
    instructions: str = "",
    max_stage_iterations: int = 3,
) -> DevForgeState:
    """Fresh state for a new workflow run."""
    records: dict[str, StageRecord] = {
        stage.value: StageRecord(status=StageStatus.PENDING.value, iterations=0)
        for stage in Stage
    }
    return DevForgeState(
        project_id=project_id,
        run_id=run_id,
        user_id=user_id,
        thread_id=thread_id,
        instructions=instructions,
        current_stage=Stage.REQUIREMENTS.value,
        current_node="",
        status=WorkflowStatus.RUNNING.value,
        stage_records=records,
        iterations={stage.value: 0 for stage in Stage},
        max_stage_iterations=max_stage_iterations,
        total_steps=0,
        requirements={},
        approved_requirements="",
        architecture={},
        approved_architecture="",
        source_changes={},
        applied_change_set_id="",
        test_results={},
        security_results={},
        documentation={},
        approval={},
        approval_status="",
        pending_approval_id="",
        last_decision={},
        messages=[],
        errors=[],
        warnings=[],
        delivery={},
    )


STAGE_LABELS: dict[str, str] = {
    Stage.REQUIREMENTS.value: "Requirements",
    Stage.ARCHITECTURE.value: "Architecture",
    Stage.DEVELOPMENT.value: "Development",
    Stage.TESTING.value: "Testing",
    Stage.SECURITY.value: "Security",
    Stage.DOCUMENTATION.value: "Documentation",
    Stage.DELIVERY.value: "Delivery",
}
