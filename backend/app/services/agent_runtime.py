"""AgentRuntime — the single place that executes an agent and records everything.

Responsibilities (spec §39 logging, §22 real-time events, Rule 8/10):

1. open an ``agent_executions`` row (input, mode, model, tokens, timing, status)
2. emit ``agent_started`` / ``agent_thinking`` / ``agent_completed`` / ``agent_failed``
3. build the project context (memory) and run the agent through the LLM gateway
4. persist artifacts, trace links and suggested tasks
5. write an audit entry
"""
from __future__ import annotations

from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import bus
from app.core.errors import AgentExecutionError
from app.core.logging import get_logger
from app.models.agent import Task
from app.models.enums import ActorType, ExecutionTrigger, FindingStatus, Stage
from app.models.execution import AgentExecution
from app.models.security import SecurityFinding
from app.models.testing import TestResult, TestRun
from app.models.user import User
from app.services.agent_registry import get_agent_spec
from app.services.artifact_service import ArtifactService
from app.services.audit import AuditService
from app.services.project_context import ProjectContextService
from app.services.trace import TraceService
from app.services.workspace import WorkspaceService
from app.tools.llm.factory import get_llm_gateway
from app.utils.time import duration_ms as elapsed_ms
from app.utils.time import utcnow

logger = get_logger("devforge.runtime")


@dataclass
class AgentRunRequest:
    project_id: str
    agent_key: str
    task: str = ""
    instructions: str = ""
    trigger: ExecutionTrigger = ExecutionTrigger.WORKFLOW
    run_id: str | None = None
    thread_agent_key: str | None = None
    user: User | None = None
    query: str = ""
    include_source: bool = True
    meta: dict = field(default_factory=dict)


class AgentRuntime:
    """Executes agents with full telemetry, persistence and eventing."""

    def __init__(self, db: Session, *, workspace: WorkspaceService | None = None) -> None:
        self.db = db
        self.workspace = workspace or WorkspaceService()
        self.artifacts = ArtifactService(db, workspace=self.workspace)
        self.trace = TraceService(db)
        self.audit = AuditService(db)
        self.context_service = ProjectContextService(db, workspace=self.workspace)

    # ------------------------------------------------------------------ lookup
    def agent_for(self, agent_key: str):  # noqa: ANN201 - BaseAgent
        from app.agents.registry import build_agent

        return build_agent(agent_key, get_llm_gateway())

    # --------------------------------------------------------------- execution
    def execute(self, request: AgentRunRequest):
        spec = get_agent_spec(request.agent_key)
        gateway = get_llm_gateway()
        agent = self.agent_for(request.agent_key)

        execution = AgentExecution(
            project_id=request.project_id,
            run_id=request.run_id,
            agent_key=spec.key,
            stage=spec.stage,
            trigger=request.trigger.value,
            mode=gateway.mode,
            provider=gateway.provider_name,
            llm_model=gateway.model,
            input_summary=(request.task or request.instructions or "workflow stage execution")[:2000],
            started_at=utcnow(),
            meta={"prompt_version": agent.prompt_version, **request.meta},
        )
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)

        bus.emit(
            "agent_started", request.project_id,
            agent_key=spec.key, agent_name=spec.name, stage=spec.stage,
            execution_id=execution.id, mode=gateway.mode, model=gateway.model,
            trigger=request.trigger.value,
        )
        bus.emit(
            "agent_thinking", request.project_id,
            agent_key=spec.key, execution_id=execution.id,
            message=f"{spec.name} is reviewing project context…",
        )

        try:
            context = self.context_service.build_agent_context(
                request.project_id,
                agent_key=spec.key,
                stage=spec.stage,
                query=request.query or request.task or request.instructions,
                instructions=request.instructions,
                thread_agent_key=request.thread_agent_key,
                include_source=request.include_source,
            )
            execution.meta = {**execution.meta, "context": context.fingerprint()}
            self.db.commit()

            outcome = agent.run(context, request.task)
            artifacts = self.persist_outcome(request, outcome)

            execution.status = "SUCCEEDED"
            execution.output_summary = (
                outcome.summary or outcome.content[:500] or "completed"
            )[:2000]
            usage = outcome.meta.get("usage") or {}
            execution.prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            execution.completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            execution.total_tokens = int(usage.get("total_tokens", 0) or 0)
            execution.meta = {**execution.meta, "artifact_ids": [a.id for a in artifacts],
                              "warnings": outcome.warnings[:5]}
        except Exception as exc:
            logger.exception("Agent %s failed", spec.key)
            execution.status = "FAILED"
            execution.error = str(exc)[:2000]
            execution.finished_at = utcnow()
            execution.duration_ms = elapsed_ms(execution.started_at, execution.finished_at)
            self.db.commit()
            bus.emit(
                "agent_failed", request.project_id,
                agent_key=spec.key, agent_name=spec.name, execution_id=execution.id,
                error=str(exc)[:400],
            )
            self.audit.record(
                action="agent.failed",
                project_id=request.project_id,
                user=request.user,
                actor_type=ActorType.AGENT,
                actor_label=spec.key,
                entity_type="agent_execution",
                entity_id=execution.id,
                stage=spec.stage,
                summary=f"{spec.name} failed: {str(exc)[:200]}",
                detail={"error": str(exc)[:1000]},
            )
            if isinstance(exc, AgentExecutionError):
                raise
            raise AgentExecutionError(
                f"{spec.name} failed to complete its task.",
                detail={"agent": spec.key, "reason": str(exc)[:300]},
            ) from exc

        execution.finished_at = utcnow()
        execution.duration_ms = elapsed_ms(execution.started_at, execution.finished_at)
        self.db.commit()
        self.db.refresh(execution)

        bus.emit(
            "agent_completed", request.project_id,
            agent_key=spec.key, agent_name=spec.name, stage=spec.stage,
            execution_id=execution.id, summary=execution.output_summary,
            duration_ms=execution.duration_ms, artifact_count=len(artifacts),
            mode=gateway.mode,
        )
        return outcome, execution

    # --------------------------------------------------------------- persistence
    def persist_outcome(self, request: AgentRunRequest, outcome) -> list:  # noqa: ANN001
        """Store artifacts, traceability links and suggested tasks."""
        spec = get_agent_spec(request.agent_key)

        # 1. auxiliary files the agent owns (e.g. test sources) — never overwritten
        for item in outcome.auto_apply_files:
            path = (item.get("path") or "").strip()
            if not path or self.workspace.exists(request.project_id, path):
                continue
            try:
                self.workspace.write_text(request.project_id, path, item.get("content") or "")
            except Exception as exc:  # pragma: no cover - workspace permissions
                logger.warning("Could not write auxiliary file %s: %s", path, exc)

        # 2. artifacts (change sets are NOT applied here — they need human approval)
        saved = []
        for draft in outcome.artifacts:
            artifact = self.artifacts.save(
                project_id=request.project_id,
                artifact_type=draft.artifact_type,
                stage=draft.stage or spec.stage,
                title=draft.title,
                content=draft.content,
                summary=draft.summary,
                data=draft.data,
                path=draft.path,
                agent_key=spec.key,
                user=request.user,
                run_id=request.run_id,
                trace_refs=draft.trace_refs,
                change_reason=f"{spec.name} generated a new revision",
            )
            saved.append(artifact)

        # Index whatever the agent produced so downstream agents can retrieve it
        # from project memory without re-reading whole artifacts.
        for artifact in saved:
            if not artifact.content.strip():
                continue
            try:
                self.context_service.knowledge.index_text(
                    self.db,
                    project_id=request.project_id,
                    source_type=ProjectContextService.source_type_for_artifact(artifact),
                    source_ref=f"artifact:{artifact.id}",
                    text=f"# {artifact.title} ({artifact.stage})\n\n{artifact.content}",
                    meta={"artifact_id": artifact.id, "type": artifact.type},
                )
            except Exception as exc:  # indexing is best-effort, never fatal
                logger.warning("Artifact indexing skipped for %s: %s", artifact.id, exc)

        # 3. structured execution outputs
        test_run = outcome.meta.get("test_run")
        if test_run:
            self._persist_test_run(request, test_run, saved)
        security_scan = outcome.meta.get("security_scan")
        if security_scan:
            self._persist_security_findings(request, security_scan, saved)

        for pair in outcome.trace_pairs:
            self.trace.link(project_id=request.project_id, **pair)

        for suggestion in outcome.suggested_tasks[:10]:
            self.db.add(
                Task(
                    project_id=request.project_id,
                    title=suggestion.get("title", "Untitled task")[:300],
                    description=suggestion.get("description", "")[:4000],
                    stage=suggestion.get("stage", spec.stage),
                    status=suggestion.get("status", "TODO"),
                    priority=suggestion.get("priority", "MEDIUM"),
                    assigned_agent_key=suggestion.get("agent_key", spec.key),
                    requirement_refs=suggestion.get("requirement_refs", []),
                    source="AGENT",
                )
            )
        self.db.commit()

        self.audit.record(
            action="agent.executed",
            project_id=request.project_id,
            user=request.user,
            actor_type=ActorType.AGENT,
            actor_label=spec.key,
            entity_type="agent",
            entity_id=spec.key,
            stage=spec.stage,
            summary=(outcome.summary or f"{spec.name} completed")[:400],
            detail={"artifacts": [a.id for a in saved], "warnings": outcome.warnings[:3]},
        )
        return saved

    # ------------------------------------------------------------------ run logs
    def _persist_test_run(self, request: AgentRunRequest, payload: dict, saved: list) -> None:
        """Store a TestRun + its per-test TestResult rows."""
        artifact_id = next(
            (artifact.id for artifact in saved if artifact.type == "TEST_RESULTS"), None
        )
        test_run = TestRun(
            project_id=request.project_id,
            run_id=request.run_id,
            artifact_id=artifact_id,
            status=payload.get("status", "ERROR"),
            total=int(payload.get("total", 0) or 0),
            passed=int(payload.get("passed", 0) or 0),
            failed=int(payload.get("failed", 0) or 0),
            skipped=int(payload.get("skipped", 0) or 0),
            errors=int(payload.get("errors", 0) or 0),
            command=(payload.get("command") or "")[:400],
            provider=payload.get("provider", ""),
            duration_ms=int(payload.get("duration_ms", 0) or 0),
            triggered_by="AGENT",
            raw_output=(payload.get("raw_output") or "")[:60_000],
            report={
                "parser": payload.get("parser", ""),
                "notes": payload.get("notes", []),
                "layout": payload.get("layout", {}),
            },
        )
        self.db.add(test_run)
        self.db.commit()
        self.db.refresh(test_run)

        for item in payload.get("results", [])[:500]:
            self.db.add(
                TestResult(
                    test_run_id=test_run.id,
                    name=(item.get("name") or "")[:400],
                    file_path=(item.get("file_path") or "")[:400],
                    status=item.get("status", "ERROR"),
                    duration_ms=int(item.get("duration_ms", 0) or 0),
                    message=(item.get("message") or "")[:4000],
                )
            )
        self.db.commit()
        self.audit.record(
            action="tests.executed",
            project_id=request.project_id,
            user=request.user,
            actor_type=ActorType.AGENT,
            actor_label=request.agent_key,
            entity_type="test_run",
            entity_id=test_run.id,
            stage=Stage.TESTING.value,
            summary=(
                f"Testing Agent executed the suite in the sandbox: "
                f"{test_run.passed}/{test_run.total} passed ({test_run.status})"
            ),
            detail={"command": test_run.command, "provider": test_run.provider,
                    "duration_ms": test_run.duration_ms},
        )
        bus.emit(
            "test_completed",
            request.project_id,
            test_run_id=test_run.id,
            status=test_run.status,
            total=test_run.total,
            passed=test_run.passed,
            failed=test_run.failed,
            errors=test_run.errors,
            duration_ms=test_run.duration_ms,
        )

    def _persist_security_findings(self, request: AgentRunRequest, payload: dict,
                                   saved: list) -> None:
        """Store SecurityFinding rows for a scan (replacing open findings of the same ref)."""
        artifact_id = next(
            (artifact.id for artifact in saved if artifact.type == "SECURITY_REPORT"), None
        )
        scan_id = f"scan-{int(utcnow().timestamp())}"
        existing = {
            f"{finding.rule_id}|{finding.file_path}|{finding.line}": finding
            for finding in self.db.scalars(
                select(SecurityFinding).where(
                    SecurityFinding.project_id == request.project_id,
                    SecurityFinding.status == FindingStatus.OPEN.value,
                )
            )
        }
        created = 0
        for item in payload.get("findings", []):
            rule_id = item.get("rule_id", "")
            previous = existing.get(f"{rule_id}|{item.get('file_path')}|{item.get('line')}")
            if previous is not None:
                continue  # same open finding: keep it, do not duplicate
            self.db.add(
                SecurityFinding(
                    project_id=request.project_id,
                    run_id=request.run_id,
                    artifact_id=artifact_id,
                    scan_id=scan_id,
                    rule_id=rule_id[:40],
                    severity=item.get("severity", "MEDIUM"),
                    category=item.get("category", "")[:64],
                    title=item.get("title", "")[:300],
                    description=item.get("description", ""),
                    file_path=item.get("file_path", "")[:600],
                    line=item.get("line"),
                    evidence=(item.get("evidence") or "")[:4000],
                    recommendation=item.get("recommendation", ""),
                    status=FindingStatus.OPEN.value,
                    detected_by=item.get("detected_by", "security_agent"),
                    trace_refs=[item.get("ref", "")],
                )
            )
            created += 1
        # close previously open findings that no longer appear in this scan
        current_keys = {
            f"{item.get('rule_id')}|{item.get('file_path')}|{item.get('line')}"
            for item in payload.get("findings", [])
        }
        for key, finding in existing.items():
            if key not in current_keys:
                finding.status = FindingStatus.FIXED.value
                finding.resolved_at = utcnow()
        self.db.commit()
        self.audit.record(
            action="security.scan_completed",
            project_id=request.project_id,
            user=request.user,
            actor_type=ActorType.AGENT,
            actor_label=request.agent_key,
            entity_type="security_scan",
            entity_id=scan_id,
            stage=Stage.SECURITY.value,
            summary=(
                f"Security Agent scanned {payload.get('files_scanned', 0)} file(s); "
                f"{len(payload.get('findings', []))} finding(s)"
            ),
            detail={"counts": payload.get("counts", {})},
        )
        bus.emit(
            "security_completed",
            request.project_id,
            scan_id=scan_id,
            files_scanned=payload.get("files_scanned", 0),
            counts=payload.get("counts", {}),
            findings=len(payload.get("findings", [])),
            created=created,
        )
