"""Agent, chat and execution-monitor schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AgentRead(ORMModel):
    id: str
    key: str
    name: str
    role: str
    description: str
    stage: str
    order_index: int
    icon: str
    capabilities: list[str]
    output_artifact_types: list[str]
    is_active: bool


class AgentStatusRead(BaseModel):
    """Row of the observability panel."""

    agent_key: str
    name: str
    stage: str
    status: str
    execution_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    result: str = ""
    error: str = ""
    mode: str = ""
    model: str = ""
    total_tokens: int = 0


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000, description="Human message to the agent.")
    #: Which specialist answers — defaults to the Developer Agent.
    agent_key: str = Field(default="developer", max_length=64)
    thread_id: str = Field(default="default", max_length=80)
    #: When true the agent may propose (never apply) file changes.
    allow_code_proposals: bool = True


class ProposedFileChange(BaseModel):
    path: str
    op: str = "update"
    description: str = ""
    diff: str = ""
    content: str = ""
    language: str = ""
    additions: int = 0
    deletions: int = 0


class ChatResponse(BaseModel):
    message_id: str
    agent_key: str
    content: str
    created_at: datetime
    execution_id: str | None = None
    mode: str = "mock"
    model: str = ""
    proposed_changes: list[ProposedFileChange] = Field(default_factory=list)
    approval_id: str | None = None
    references: list[str] = Field(default_factory=list)


class MessageRead(ORMModel):
    id: str
    project_id: str
    agent_key: str | None
    thread_id: str
    role: str
    content: str
    user_id: str | None
    execution_id: str | None
    meta: dict
    created_at: datetime


class ExecutionRead(ORMModel):
    id: str
    project_id: str
    run_id: str | None
    agent_key: str
    stage: str
    trigger: str
    status: str
    mode: str
    provider: str
    llm_model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_summary: str
    output_summary: str
    error: str
    duration_ms: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class TaskRead(ORMModel):
    id: str
    project_id: str
    title: str
    description: str
    status: str
    priority: str
    stage: str
    assigned_agent_key: str | None
    requirement_refs: list[str]
    source: str
    created_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    description: str = Field(default="", max_length=4000)
    priority: str = "MEDIUM"
    stage: str = ""
    assigned_agent_key: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None


class AuditLogRead(ORMModel):
    id: str
    project_id: str | None
    user_id: str | None
    actor_type: str
    actor_label: str
    action: str
    entity_type: str
    entity_id: str
    stage: str
    summary: str
    detail: dict
    created_at: datetime
