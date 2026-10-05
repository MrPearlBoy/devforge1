"""Workflow state schema (Pydantic v2 models).

The engine serializes the whole :class:`WorkflowState` into the
``projects.artifacts`` column after every transition, which gives us
crash-safe resume plus a single source of truth for the API snapshot.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Agent artifacts
# --------------------------------------------------------------------------
class RequirementSpec(BaseModel):
    project_name: str
    overview: str
    functional_requirements: list[str]
    user_stories: list[dict[str, Any]] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class APIEndpoint(BaseModel):
    method: str
    path: str
    description: str
    request_body: str = ""
    response: str = ""


class ModuleDesign(BaseModel):
    name: str
    responsibility: str
    files: list[str] = Field(default_factory=list)


class ArchitectureSpec(BaseModel):
    summary: str
    tech_stack: dict[str, str] = Field(default_factory=dict)
    directory_structure: str = ""
    api_endpoints: list[APIEndpoint] = Field(default_factory=list)
    modules: list[ModuleDesign] = Field(default_factory=list)
    data_model: str = ""


class CodeFile(BaseModel):
    path: str
    content: str
    description: str = ""


class CodeArtifact(BaseModel):
    summary: str = ""
    files: list[CodeFile] = Field(default_factory=list)
    run_instructions: str = ""


class TestArtifact(BaseModel):
    summary: str = ""
    strategy: str = ""
    files: list[CodeFile] = Field(default_factory=list)


class TestReport(BaseModel):
    passed: bool = False
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    exit_code: int = -1
    duration_s: float = 0.0
    summary: str = ""
    output: str = ""
    failures: list[str] = Field(default_factory=list)


class SecurityFinding(BaseModel):
    severity: str = "INFO"  # HIGH | MEDIUM | LOW | INFO
    category: str = ""
    message: str = ""
    file: str = ""
    line: Optional[int] = None


class SecurityReport(BaseModel):
    clean: bool = True
    tool: str = ""
    findings: list[SecurityFinding] = Field(default_factory=list)
    output: str = ""


class DocsArtifact(BaseModel):
    readme: str = ""
    api_documentation: str = ""
    architecture_summary: str = ""


# --------------------------------------------------------------------------
# Workflow state
# --------------------------------------------------------------------------
GATES = ("requirement", "architecture", "code", "docs")
DECISIONS = ("approved", "rejected", "changes_requested")

GATE_TITLES = {
    "requirement": "Requirement Approved?",
    "architecture": "Architecture Approved?",
    "code": "Code Approved?",
    "docs": "Docs Approved?",
}

STAGES = (
    "created",
    "requirement",
    "architecture",
    "coding",
    "testing",
    "security",
    "documentation",
    "delivery",
    "completed",
    "failed",
)


class WorkflowState(BaseModel):
    """Mutable state carried through the state machine."""

    project_id: str
    stage: str = "created"
    status: str = "idle"  # idle | running | waiting_approval | completed | failed
    awaiting_gate: Optional[str] = None
    #: latest human feedback per stage, injected into the next agent run
    feedback: dict[str, str] = Field(default_factory=dict)
    #: iteration counters: gate rejections, test self-heals, security fix loops
    iterations: dict[str, int] = Field(default_factory=dict)
    #: when True (set by decision loops 4/5) the code gate is skipped so the
    #: CA can self-heal automatically without a human checkpoint
    skip_code_gate: bool = False

    requirement: Optional[RequirementSpec] = None
    architecture: Optional[ArchitectureSpec] = None
    code: Optional[CodeArtifact] = None
    tests: Optional[TestReport] = None
    security: Optional[SecurityReport] = None
    docs: Optional[DocsArtifact] = None
    git: Optional[dict[str, Any]] = None
    error: Optional[str] = None
