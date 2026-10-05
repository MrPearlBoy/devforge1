"""Test-run, security-scan and sandbox schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class TestResultRead(ORMModel):
    id: str
    test_run_id: str
    name: str
    file_path: str
    status: str
    duration_ms: int
    message: str
    requirement_refs: list[str]


class TestRunRead(ORMModel):
    id: str
    project_id: str
    run_id: str | None
    artifact_id: str | None
    status: str
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    command: str
    provider: str
    duration_ms: int
    triggered_by: str
    confirmed_by_user: bool
    report: dict
    created_at: datetime


class TestRunDetail(TestRunRead):
    results: list[TestResultRead] = Field(default_factory=list)
    raw_output: str = ""


class RunTestsRequest(BaseModel):
    #: Optional explicit pytest target pattern inside the project workspace.
    target: str = Field(default="", max_length=300)
    #: Human confirmation flag required for executing code in the sandbox.
    confirm_execution: bool = True


class SecurityFindingRead(ORMModel):
    id: str
    project_id: str
    run_id: str | None
    scan_id: str
    rule_id: str
    severity: str
    category: str
    title: str
    description: str
    file_path: str
    line: int | None
    evidence: str
    recommendation: str
    status: str
    detected_by: str
    trace_refs: list[str]
    created_at: datetime


class SecurityScanRequest(BaseModel):
    include_ai_review: bool = True


class SecuritySummary(BaseModel):
    scan_id: str
    artifact_id: str | None = None
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0
    open_total: int = 0
    files_scanned: int = 0
    created_at: datetime | None = None
    disclaimer: str = ""


class FindingUpdateRequest(BaseModel):
    status: str = Field(description="OPEN | ACKNOWLEDGED | FIXED | FALSE_POSITIVE")
    comment: str = Field(default="", max_length=1000)


class ExecutionRequest(BaseModel):
    """Generic sandbox invocation (restricted by allow-list)."""

    command: str = Field(description="Allow-listed executable name, e.g. 'pytest'")
    args: list[str] = Field(default_factory=list)
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)
    confirm_execution: bool = True


class ExecutionResultRead(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    provider: str = ""
    command: str = ""
    sandboxed: bool = True
    truncated: bool = False
