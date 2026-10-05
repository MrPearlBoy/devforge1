"""Structured output contract of the Developer Agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FileChange(BaseModel):
    path: str = Field(description="Workspace-relative path, e.g. backend/app/main.py")
    operation: str = Field(default="create", description="create | update | delete")
    summary: str = Field(default="", description="One line explaining why this file changes")
    content: str = Field(default="", description="Full new file content (empty for delete)")
    language: str = "python"


class CodeChangePlan(BaseModel):
    """A reviewable proposal — nothing is written to the workspace before approval."""

    analysis: str = Field(description="What was inspected and what the change does")
    affected_files: list[str] = Field(default_factory=list)
    changes: list[FileChange] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list,
                                    description="How the change will be verified")
    notes: list[str] = Field(default_factory=list)
    requirement_refs: list[str] = Field(default_factory=list)
    architecture_refs: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
