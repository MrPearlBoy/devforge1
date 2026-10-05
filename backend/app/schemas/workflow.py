"""Approval + workflow schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ApprovalDecision
from app.schemas.common import ORMModel


class ApprovalRead(ORMModel):
    id: str
    project_id: str
    run_id: str | None
    artifact_id: str | None
    stage: str
    gate: str
    status: str
    requested_by_agent_key: str | None
    requested_at: datetime | None
    decided_by_user_id: str | None
    decided_at: datetime | None
    comments: str
    decision_meta: dict
    created_at: datetime


class ApprovalDetail(ApprovalRead):
    artifact_title: str = ""
    artifact_type: str = ""
    artifact_preview: str = ""
    requested_by_user_name: str = ""
    decided_by_user_name: str = ""


class ApprovalDecisionRequest(BaseModel):
    #: Required by the generic endpoint; /approve, /reject and /changes set it server side.
    decision: ApprovalDecision = ApprovalDecision.APPROVE
    comments: str = Field(default="", max_length=4000)
    #: Optional free-form instructions handed to the agent when changes are requested.
    instructions: str = Field(default="", max_length=4000)
    #: Optional inline edit of the artifact content applied before approval.
    edited_content: str | None = None


class StageRead(BaseModel):
    stage: str
    label: str
    status: str
    order: int
    iterations: int = 0
    artifact_id: str | None = None
    artifact_title: str = ""
    approval_id: str | None = None
    approval_status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: str = ""


class WorkflowRunRead(ORMModel):
    id: str
    project_id: str
    run_number: int
    status: str
    engine: str
    thread_id: str
    current_stage: str
    current_node: str
    awaiting_approval: bool
    pending_approval_id: str | None
    stage_iterations: dict
    total_steps: int
    max_stage_iterations: int
    started_at: datetime | None
    finished_at: datetime | None
    last_error: str
    created_at: datetime


class WorkflowOverview(BaseModel):
    run: WorkflowRunRead | None
    project_status: str
    current_stage: str
    stages: list[StageRead]
    pending_approval: ApprovalDetail | None = None
    can_resume: bool = False
    iteration_budget: dict = Field(default_factory=dict)


class StartWorkflowRequest(BaseModel):
    #: Optional guidance injected as human instructions for the first stage.
    instructions: str = Field(default="", max_length=4000)
    restart: bool = False


class ResumeWorkflowRequest(BaseModel):
    comments: str = Field(default="", max_length=2000)


class WorkflowStateRead(ORMModel):
    id: str
    run_id: str
    step_index: int
    node: str
    stage: str
    status: str
    summary: str
    state: dict
    created_at: datetime
