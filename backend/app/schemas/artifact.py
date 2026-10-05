"""Artifact schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ArtifactRead(ORMModel):
    id: str
    project_id: str
    run_id: str | None
    type: str
    stage: str
    title: str
    summary: str
    content: str
    data: dict
    path: str
    version: int
    status: str
    produced_by_agent_key: str | None
    trace_refs: list[str]
    created_at: datetime
    updated_at: datetime


class ArtifactSummary(ORMModel):
    id: str
    project_id: str
    type: str
    stage: str
    title: str
    summary: str
    path: str
    version: int
    status: str
    produced_by_agent_key: str | None
    trace_refs: list[str]
    created_at: datetime
    updated_at: datetime


class ArtifactVersionRead(ORMModel):
    id: str
    artifact_id: str
    version: int
    content: str
    change_reason: str
    author_type: str
    author_label: str
    created_at: datetime


class ArtifactUpdateRequest(BaseModel):
    """Human edit of an artifact before approval."""

    content: str | None = None
    title: str | None = None
    change_reason: str = Field(default="Edited by human reviewer", max_length=400)


class WorkspaceFile(BaseModel):
    path: str
    size: int
    language: str
    modified_at: datetime | None = None
    is_binary: bool = False
    artifact_id: str | None = None


class WorkspaceFileContent(BaseModel):
    path: str
    content: str
    size: int
    language: str
    truncated: bool = False


class WorkspaceTree(BaseModel):
    """Grouped tree used by the code explorer."""

    root: str
    groups: dict[str, list[WorkspaceFile]]
    total_files: int


class CodeChangeOp(BaseModel):
    op: str  # create | update | delete
    path: str
    description: str = ""
    diff: str = ""
    additions: int = 0
    deletions: int = 0
    language: str = ""
