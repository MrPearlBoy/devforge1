"""Project + dashboard schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=4000)
    requirement_input: str = Field(
        default="", max_length=20000,
        description="Natural language description of what should be built.",
    )
    tech_stack: str = Field(default="", max_length=400)
    tags: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    requirement_input: str | None = Field(default=None, max_length=20000)
    tech_stack: str | None = Field(default=None, max_length=400)
    tags: list[str] | None = None
    is_archived: bool | None = None


class StageProgress(BaseModel):
    stage: str
    label: str
    status: str
    order: int
    artifact_id: str | None = None
    approval_id: str | None = None


class ProjectRead(ORMModel):
    id: str
    name: str
    description: str
    slug: str
    requirement_input: str
    current_stage: str
    workflow_status: str
    stage_status: str
    progress_percent: int
    tech_stack: str
    tags: list[str]
    workspace_path: str
    owner_id: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ProjectSummary(ProjectRead):
    owner_name: str = ""
    active_run_id: str | None = None
    pending_approvals: int = 0
    open_findings: int = 0
    last_test_status: str | None = None
    github_connected: bool = False


class ProjectDashboard(BaseModel):
    """Everything the project dashboard needs in a single round trip."""

    project: ProjectRead
    stages: list[StageProgress]
    active_run: dict | None = None
    pending_approval: dict | None = None
    approvals: list[dict] = Field(default_factory=list)
    agent_activity: list[dict] = Field(default_factory=list)
    recent_activity: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)
    latest_test_run: dict | None = None
    security_summary: dict = Field(default_factory=dict)
    repository: dict | None = None
    ai_config: dict = Field(default_factory=dict)
