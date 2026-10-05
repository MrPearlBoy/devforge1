"""Test execution, security findings and the sandboxed command runner.

Every command below runs inside the restricted sandbox (``app/tools/executor``) with a
working directory inside the project workspace — AI-generated code is never executed on
the host directly, and each invocation is recorded with an audit entry.
"""
from __future__ import annotations

import shlex

from fastapi import APIRouter
from sqlalchemy import desc, func, select

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep, Workspace
from app.core.errors import ExecutionError as ExecError, NotFoundError, ValidationFailure
from app.core.logging import get_logger
from app.models.enums import (
    ArtifactType,
    ExecutionTrigger,
    FindingStatus,
    Severity,
    Stage,
    TestStatus,
)
from app.models.security import SecurityFinding
from app.models.testing import TestResult, TestRun
from app.schemas.execution import (
    ExecutionRequest,
    ExecutionResultRead,
    FindingUpdateRequest,
    RunTestsRequest,
    SecurityFindingRead,
    SecurityScanRequest,
    SecuritySummary,
    TestResultRead,
    TestRunDetail,
    TestRunRead,
)
from app.services.agent_runtime import AgentRunRequest, AgentRuntime
from app.services.artifact_service import ArtifactService
from app.services.audit import AuditService
from app.core.config import settings
from app.tools.executor import executor_status, get_executor
from app.tools.test_runner import TestRunner

logger = get_logger("devforge.api.execution")

router = APIRouter(tags=["execution"])


# --------------------------------------------------------------------------- #
# tests
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/tests", response_model=list[TestRunRead],
            summary="Test run history")
def list_test_runs(project: ProjectDep, db: DbSession, limit: int = 20) -> list[TestRunRead]:
    rows = db.scalars(
        select(TestRun).where(TestRun.project_id == project.id)
        .order_by(desc(TestRun.created_at)).limit(min(limit, 100))
    )
    return [TestRunRead.model_validate(row) for row in rows]


@router.get("/projects/{project_id}/tests/latest", response_model=TestRunDetail | None,
            summary="Latest test run with per-test results")
def latest_test_run(project: ProjectDep, db: DbSession) -> TestRunDetail | None:
    run = db.scalars(
        select(TestRun).where(TestRun.project_id == project.id).order_by(desc(TestRun.created_at))
    ).first()
    if run is None:
        return None
    results = db.scalars(
        select(TestResult).where(TestResult.test_run_id == run.id).order_by(TestResult.name)
    ).all()
    payload = TestRunRead.model_validate(run).model_dump()
    return TestRunDetail(
        **payload,
        results=[TestResultRead.model_validate(row) for row in results],
        raw_output=str((run.report or {}).get("raw_output", ""))[:20000],
    )


@router.get("/tests/{test_run_id}", response_model=TestRunDetail, summary="One test run")
def test_run_detail(test_run_id: str, db: DbSession, user: CurrentUser) -> TestRunDetail:
    run = db.get(TestRun, test_run_id)
    if run is None:
        raise NotFoundError("Test run not found.")
    results = db.scalars(
        select(TestResult).where(TestResult.test_run_id == run.id).order_by(TestResult.name)
    ).all()
    payload = TestRunRead.model_validate(run).model_dump()
    return TestRunDetail(
        **payload,
        results=[TestResultRead.model_validate(row) for row in results],
        raw_output=str((run.report or {}).get("raw_output", ""))[:20000],
    )


@router.post("/projects/{project_id}/tests/run", response_model=TestRunDetail,
             summary="Run the project test suite in the sandbox")
def run_tests(project: EditableProjectDep, payload: RunTestsRequest, db: DbSession,
              user: CurrentUser, workspace: Workspace) -> TestRunDetail:
    if not payload.confirm_execution:
        raise ValidationFailure("Test execution requires explicit confirmation.")
    project_dir = workspace.project_dir(project.id)
    runner = TestRunner()
    parsed = runner.run(project_dir, target=payload.target)

    run = TestRun(
        project_id=project.id,
        status=parsed.status,
        total=parsed.total, passed=parsed.passed, failed=parsed.failed,
        skipped=parsed.skipped, errors=parsed.errors,
        command=parsed.command, provider=parsed.provider, duration_ms=parsed.duration_ms,
        triggered_by="MANUAL", confirmed_by_user=True,
        report={
            "parser": parsed.parser, "layout": parsed.layout, "notes": parsed.notes,
            "raw_output": parsed.raw_output[:20000],
            "sandbox": {"provider": parsed.provider, "project_dir": str(project_dir)},
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Manual runs inherit the requirement references the agents attached to the same
    # test names, so traceability survives a re-run from the UI.
    inherited: dict[str, list[str]] = {}
    for row in db.scalars(
        select(TestResult).join(TestRun, TestResult.test_run_id == TestRun.id)
        .where(TestRun.project_id == project.id).order_by(desc(TestResult.created_at)).limit(500)
    ):
        if row.requirement_refs and row.name not in inherited:
            inherited[row.name] = list(row.requirement_refs)

    for item in parsed.results:
        db.add(TestResult(
            test_run_id=run.id, name=item.name, file_path=item.file_path,
            status=item.status, duration_ms=item.duration_ms, message=item.message[:2000],
            requirement_refs=inherited.get(item.name, []),
        ))
    db.commit()

    AuditService(db).record(
        action="tests.executed",
        project_id=project.id,
        user=user,
        entity_type="test_run",
        entity_id=run.id,
        stage=Stage.TESTING.value,
        summary=f"{user.full_name or user.email} ran the suite: "
                f"{parsed.passed}/{parsed.total} passed ({parsed.status})",
        detail={"command": parsed.command, "duration_ms": parsed.duration_ms,
                "target": payload.target},
        publish=True,
    )
    from app.core.events import bus

    bus.emit("test_completed", project.id, run_id=run.id, status=parsed.status,
             passed=parsed.passed, total=parsed.total, duration_ms=parsed.duration_ms,
             triggered_by="MANUAL",
             message=f"{parsed.passed}/{parsed.total} tests passed")

    results = db.scalars(
        select(TestResult).where(TestResult.test_run_id == run.id).order_by(TestResult.name)
    ).all()
    detail = TestRunRead.model_validate(run).model_dump()
    return TestRunDetail(
        **detail,
        results=[TestResultRead.model_validate(row) for row in results],
        raw_output=parsed.raw_output[:20000],
    )


@router.post("/projects/{project_id}/tests/agent", response_model=TestRunDetail,
             summary="Ask the Testing Agent to plan and run the suite")
def run_testing_agent(project: EditableProjectDep, payload: RunTestsRequest, db: DbSession,
                      user: CurrentUser) -> TestRunDetail:
    runtime = AgentRuntime(db)
    runtime.execute(AgentRunRequest(
        project_id=project.id,
        agent_key="testing",
        task=payload.target or "Design and execute the test suite for the current project.",
        trigger=ExecutionTrigger.MANUAL,
        user=user,
        query="test plan suite coverage",
        meta={"source": "manual_test_run"},
    ))
    run = db.scalars(
        select(TestRun).where(TestRun.project_id == project.id).order_by(desc(TestRun.created_at))
    ).first()
    if run is None:
        raise NotFoundError("The Testing Agent did not produce a test run.")
    results = db.scalars(select(TestResult).where(TestResult.test_run_id == run.id)).all()
    detail = TestRunRead.model_validate(run).model_dump()
    return TestRunDetail(
        **detail,
        results=[TestResultRead.model_validate(row) for row in results],
        raw_output=str((run.report or {}).get("raw_output", ""))[:20000],
    )


# --------------------------------------------------------------------------- #
# security
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/security/findings", response_model=list[SecurityFindingRead],
            summary="Security findings")
def list_findings(project: ProjectDep, db: DbSession, finding_status: str | None = None,
                  severity: str | None = None) -> list[SecurityFindingRead]:
    stmt = select(SecurityFinding).where(SecurityFinding.project_id == project.id)
    if finding_status:
        stmt = stmt.where(SecurityFinding.status == finding_status)
    if severity:
        stmt = stmt.where(SecurityFinding.severity == severity)
    stmt = stmt.order_by(SecurityFinding.severity, desc(SecurityFinding.created_at)).limit(300)
    return [SecurityFindingRead.model_validate(row) for row in db.scalars(stmt)]


@router.get("/projects/{project_id}/security/summary", response_model=SecuritySummary,
            summary="Security posture summary")
def security_summary(project: ProjectDep, db: DbSession) -> SecuritySummary:
    rows = db.scalars(
        select(SecurityFinding).where(SecurityFinding.project_id == project.id)
    ).all()
    open_rows = [row for row in rows if row.status == FindingStatus.OPEN.value]
    counts: dict[str, int] = {}
    for row in open_rows:
        counts[row.severity] = counts.get(row.severity, 0) + 1
    artifact = ArtifactService(db).latest(project.id, ArtifactType.SECURITY_REPORT)
    data = (artifact.data or {}) if artifact else {}
    scan = data.get("scan", {}) if isinstance(data, dict) else {}
    return SecuritySummary(
        scan_id=str(scan.get("scan_id", "")),
        artifact_id=artifact.id if artifact else None,
        critical=counts.get(Severity.CRITICAL.value, 0),
        high=counts.get(Severity.HIGH.value, 0),
        medium=counts.get(Severity.MEDIUM.value, 0),
        low=counts.get(Severity.LOW.value, 0),
        info=counts.get(Severity.INFO.value, 0),
        open_total=len(open_rows),
        files_scanned=int(scan.get("files_scanned", 0) or 0),
        created_at=artifact.created_at if artifact else None,
        disclaimer=(
            "Automated static analysis plus model review. It complements — and does not "
            "replace — a professional security audit."
        ),
    )


@router.post("/projects/{project_id}/security/scan", response_model=SecuritySummary,
             summary="Ask the Security Agent to scan and review the project")
def run_security_scan(project: EditableProjectDep, payload: SecurityScanRequest, db: DbSession,
                      user: CurrentUser) -> SecuritySummary:
    runtime = AgentRuntime(db)
    runtime.execute(AgentRunRequest(
        project_id=project.id,
        agent_key="security",
        task="Scan the generated project for security weaknesses and review the design.",
        trigger=ExecutionTrigger.MANUAL,
        user=user,
        query="security scan secrets injection dependencies",
        meta={"source": "manual_security_scan",
              "include_ai_review": payload.include_ai_review},
    ))
    return security_summary(project, db)


@router.patch("/security/findings/{finding_id}", response_model=SecurityFindingRead,
              summary="Triage a finding (OPEN / ACKNOWLEDGED / FIXED / FALSE_POSITIVE)")
def update_finding(finding_id: str, payload: FindingUpdateRequest, db: DbSession,
                   user: CurrentUser) -> SecurityFindingRead:
    finding = db.get(SecurityFinding, finding_id)
    if finding is None:
        raise NotFoundError("Finding not found.")
    allowed = {item.value for item in FindingStatus}
    if payload.status not in allowed:
        raise ValidationFailure(f"Status must be one of: {', '.join(sorted(allowed))}.")
    finding.status = payload.status
    if payload.status == FindingStatus.FIXED.value:
        from app.utils.time import utcnow

        finding.resolved_at = utcnow()
    db.commit()
    db.refresh(finding)
    AuditService(db).record(
        action="security.finding_triaged",
        project_id=finding.project_id,
        user=user,
        entity_type="security_finding",
        entity_id=finding.id,
        stage=Stage.SECURITY.value,
        summary=f"{user.full_name or user.email} marked {finding.rule_id} as {payload.status}",
        detail={"comment": payload.comment},
    )
    return SecurityFindingRead.model_validate(finding)


@router.post("/projects/{project_id}/security/findings/{finding_id}/remediate",
             summary="Open a remediation approval for one finding")
def remediate(finding_id: str, project: EditableProjectDep, db: DbSession,
              user: CurrentUser) -> dict:
    finding = db.get(SecurityFinding, finding_id)
    if finding is None or finding.project_id != project.id:
        raise NotFoundError("Finding not found.")
    runtime = AgentRuntime(db)
    outcome, execution = runtime.execute(AgentRunRequest(
        project_id=project.id,
        agent_key="developer",
        task=(f"Remediate finding {finding.rule_id} ({finding.title}) in {finding.file_path}. "
              f"Recommendation: {finding.recommendation}"),
        trigger=ExecutionTrigger.MANUAL,
        user=user,
        query=f"{finding.rule_id} {finding.title} remediation",
        meta={"source": "finding_remediation", "finding_id": finding.id,
              "rule_id": finding.rule_id},
    ))

    from app.services.approval_service import ApprovalService

    change_set = ArtifactService(db).latest(project.id, ArtifactType.CHANGE_SET, Stage.DEVELOPMENT)
    approval_id = ""
    if change_set is not None and outcome.file_changes:
        approval = ApprovalService(db).request(
            project_id=project.id,
            stage=Stage.DEVELOPMENT.value,
            gate="code_review",
            artifact=change_set,
            agent_key="developer",
            summary=f"Remediation proposal for {finding.rule_id}",
            meta={"finding_id": finding.id, "rule_id": finding.rule_id, "origin": "security"},
        )
        approval_id = approval.id
    return {
        "execution_id": execution.id,
        "finding_id": finding.id,
        "approval_id": approval_id,
        "summary": outcome.summary,
        "proposed_files": [item.get("path", "") for item in outcome.file_changes],
    }


# --------------------------------------------------------------------------- #
# sandbox
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/sandbox", summary="Sandbox configuration and limits")
def sandbox_info(project: ProjectDep, workspace: Workspace) -> dict:
    status = executor_status()
    return {
        "provider": status.get("provider", ""),
        "available": bool(status.get("available", False)),
        "isolation": status.get("isolation", ""),
        "limits": {
            "timeout_seconds": settings.execution_timeout_seconds,
            "memory_mb": settings.execution_memory_mb,
            "cpu_seconds": settings.execution_cpu_seconds,
        },
        "allowed_commands": sorted(settings.allowed_commands),
        "working_directory": str(workspace.project_dir(project.id)),
        "note": (
            "AI-generated code is executed through this sandbox only: an allow-listed "
            "executable, no shell, CPU/memory/time limits and a process-group kill on "
            "timeout. Set EXECUTION_PROVIDER=docker for stronger isolation."
        ),
        "status_note": status.get("note", ""),
    }


@router.post("/projects/{project_id}/sandbox/run", response_model=ExecutionResultRead,
             summary="Run an allow-listed command inside the sandbox")
def sandbox_run(project: EditableProjectDep, payload: ExecutionRequest, db: DbSession,
                user: CurrentUser, workspace: Workspace) -> ExecutionResultRead:
    if not payload.confirm_execution:
        raise ValidationFailure("Running a command in the sandbox requires explicit confirmation.")

    command = payload.command.strip()
    if not command:
        raise ValidationFailure("Provide a command to run, for example 'pytest'.")

    project_dir = workspace.project_dir(project.id)
    try:
        result = get_executor().run([command, *payload.args], cwd=project_dir,
                                    timeout=payload.timeout_seconds or 120)
    except ExecError as exc:
        raise ValidationFailure(exc.message, detail=exc.detail or {}) from exc

    AuditService(db).record(
        action="sandbox.command_executed",
        project_id=project.id,
        user=user,
        actor_label=user.email,
        entity_type="sandbox",
        entity_id="",
        summary=f"{user.full_name or user.email} ran: {shlex.join([command, *payload.args])}",
        detail={"exit_code": result.exit_code, "duration_ms": result.duration_ms,
                "timed_out": result.timed_out},
    )
    return ExecutionResultRead(
        exit_code=result.exit_code,
        stdout=result.stdout[-20000:],
        stderr=result.stderr[-20000:],
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
        provider=result.provider,
        command=result.command or shlex.join([command, *payload.args]),
        sandboxed=result.sandboxed,
        truncated=result.truncated or len(result.stdout) > 20000,
    )
