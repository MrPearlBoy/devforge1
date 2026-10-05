"""Structured output contract of the Testing Agent."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    id: str = Field(description="Stable id such as TEST-TASK-001")
    name: str
    type: str = Field(default="unit", description="unit | integration | api | security")
    target: str = Field(default="", description="File or endpoint under test")
    description: str = ""
    steps: list[str] = Field(default_factory=list)
    expected: str = ""
    requirement_refs: list[str] = Field(default_factory=list)


class TestFile(BaseModel):
    path: str
    content: str
    summary: str = ""
    requirement_refs: list[str] = Field(default_factory=list)


class TestPlan(BaseModel):
    strategy: str = ""
    scope: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    files: list[TestFile] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
