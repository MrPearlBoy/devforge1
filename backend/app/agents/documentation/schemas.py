"""Structured output contract of the Documentation Agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentationFile(BaseModel):
    path: str
    title: str
    content: str
    summary: str = ""
    requirement_refs: list[str] = Field(default_factory=list)


class DocumentationPlan(BaseModel):
    overview: str = ""
    files: list[DocumentationFile] = Field(default_factory=list)
    documented_facts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list,
                            description="Features that exist but are not documented, or vice versa")
    notes: list[str] = Field(default_factory=list)
