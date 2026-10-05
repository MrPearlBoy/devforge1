"""GitHub / git integration schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class RepositoryConnectRequest(BaseModel):
    url: str = Field(min_length=8, max_length=500, description="https://github.com/owner/repo.git")
    default_branch: str = Field(default="main", max_length=120)
    #: Optional personal access token; encrypted at rest, never returned.
    token: str = Field(default="", max_length=400)
    clone: bool = True


class RepositoryRead(ORMModel):
    id: str
    project_id: str
    provider: str
    url: str
    owner: str
    name: str
    default_branch: str
    working_branch: str
    local_path: str
    auth_configured: bool
    status: str
    last_synced_at: datetime | None
    last_commit_sha: str
    meta: dict
    created_at: datetime


class WorkingTreeFile(BaseModel):
    path: str
    status: str
    staged: bool = False


class GitStatusRead(BaseModel):
    connected: bool
    repository: RepositoryRead | None = None
    branch: str = ""
    is_clean: bool = True
    changes: list[WorkingTreeFile] = Field(default_factory=list)
    staged_count: int = 0
    untracked_count: int = 0
    ahead: int = 0
    behind: int = 0
    remote_url: str = ""
    last_operation: dict | None = None
    requires_confirmation: bool = True
    message: str = ""


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=3, max_length=300)
    paths: list[str] = Field(default_factory=list, description="Empty = all pending changes")
    #: Explicit human confirmation gate for remote/destructive operations.
    confirm: bool = True


class GitPushRequest(BaseModel):
    branch: str = Field(default="", max_length=120)
    set_upstream: bool = True
    confirm: bool = True
    create_pull_request: bool = False
    pr_title: str = Field(default="", max_length=200)
    pr_body: str = Field(default="", max_length=4000)
    base_branch: str = Field(default="", max_length=120)


class GitOperationRead(ORMModel):
    id: str
    project_id: str
    repository_id: str | None
    user_id: str | None
    operation: str
    status: str
    branch: str
    commit_sha: str
    message: str
    confirmed_by_user: bool
    detail: dict
    error: str
    created_at: datetime


class GitSyncPlan(BaseModel):
    """What DevForge proposes before any remote operation (human confirms)."""

    branch: str
    base_branch: str
    commit_message: str
    files: list[WorkingTreeFile] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    requires_confirmation: bool = True
