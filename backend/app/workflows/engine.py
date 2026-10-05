"""WorkflowEngine — starts, suspends, resumes and reports orchestration runs.

The engine owns everything around the graph:

* creating the ``workflow_runs`` row and the initial state;
* driving the compiled graph on a worker thread so API requests never block;
* translating LangGraph ``interrupt`` payloads into project/approval state;
* recording each step in ``workflow_states`` and every lifecycle change in the audit
  log, and mirroring the state into ``.devforge/workflow.json`` inside the workspace.
"""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone
from typing import Any

from langgraph.types import Command
from sqlalchemy import desc, select

from app.core.config import settings
from app.core.database import session_scope
from app.core.errors import ConflictError, NotFoundError, WorkflowError
from app.core.events import bus
from app.core.logging import get_logger
from app.models.enums import (
    ActorType,
    ApprovalDecision,
    ApprovalStatus,
    ApprovalStatus as ApprovalState,
    Stage,
    StageStatus,
    WorkflowStatus,
)
from app.models.user import User
from app.models.workflow import WorkflowRun, WorkflowState
from app.services.approval_service import ApprovalService
from app.services.audit import AuditService
from app.services.project_service import ProjectService
from app.services.workspace import WorkspaceService
from app.utils.time import duration_ms, utcnow
from app.workflows.graph import STAGE_FOR_NODE, build_workflow_graph
from app.workflows.state import DevForgeState, STAGE_LABELS, initial_state

logger = get_logger("devforge.workflow.engine")

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="devforge-workflow")
_GRAPH_LOCK = threading.Lock()
_GRAPH: Any = None


def get_graph():
    """Compiled graph singleton (shares one checkpointer)."""
    global _GRAPH
    with _GRAPH_LOCK:
        if _GRAPH is None:
            _GRAPH = build_workflow_graph()
    return _GRAPH


def reset_graph() -> None:
    global _GRAPH
    with _GRAPH_LOCK:
        _GRAPH = None


class WorkflowEngine:
    """Public API used by the REST layer, the CLI and the tests."""

    # ------------------------------------------------------------------ lifecycle
    def start(
        self,
        project_id: str,
        *,
        user: User,
        instructions: str = "",
        restart: bool = False,
        background: bool = True,
    ) -> WorkflowRun:
        with session_scope() as db:
            project = ProjectService(db).get(project_id)
            previous = db.scalars(
                select(WorkflowRun).where(WorkflowRun.project_id == project_id)
                .order_by(desc(WorkflowRun.created_at))
            ).first()
            if previous is not None and previous.status in {
                WorkflowStatus.RUNNING.value, WorkflowStatus.AWAITING_APPROVAL.value
            } and not restart:
                raise ConflictError(
                    "A workflow is already running for this project. "
                    "Resolve the pending approval or restart the workflow.",
                    detail={"run_id": previous.id, "status": previous.status},
                )

            run = WorkflowRun(
                project_id=project_id,
                run_number=(previous.run_number + 1) if previous else 1,
                status=WorkflowStatus.RUNNING.value,
                engine="langgraph",
                thread_id=f"devforge-{project_id}-{utcnow().strftime('%Y%m%d%H%M%S')}",
                current_stage=Stage.REQUIREMENTS.value,
                max_stage_iterations=settings.max_stage_iterations,
                started_by_user_id=user.id,
                started_at=utcnow(),
                stage_iterations={},
            )
            db.add(run)
            db.commit()
            db.refresh(run)

            ProjectService(db).mark_stage(project_id, stage=Stage.REQUIREMENTS.value,
                                          status=StageStatus.RUNNING.value, run_id=run.id)
            AuditService(db).record(
                action="workflow.started",
                project_id=project_id,
                user=user,
                entity_type="workflow_run",
                entity_id=run.id,
                stage=Stage.REQUIREMENTS.value,
                summary=f"{user.full_name or user.email} started the SDLC workflow "
                        f"(run #{run.run_number})",
                detail={"instructions": instructions[:500]},
            )
            state = initial_state(
                project_id=project_id,
                run_id=run.id,
                user_id=user.id,
                thread_id=run.thread_id,
                instructions=instructions,
                max_stage_iterations=settings.max_stage_iterations,
            )
            workspace = WorkspaceService()
            workspace.write_workflow_metadata(project_id, {"run_id": run.id, "status": "RUNNING",
                                                           "state": state})
            run_id = run.id

        bus.emit("workflow_started", project_id, run_id=run_id,
                 message="DevForge workflow started — Requirement Agent is analysing your input")
        if background:
            _EXECUTOR.submit(self._drive, run_id, state, None)
        else:
            self._drive(run_id, state, None)
        return self.get_run(run_id)

    def resume(
        self,
        run_id: str,
        *,
        user: User,
        decision: ApprovalDecision,
        comments: str = "",
        instructions: str = "",
        approval_id: str | None = None,
        edited_content: str | None = None,
        background: bool = True,
    ) -> WorkflowRun:
        run = self.get_run(run_id)
        if run.status not in {WorkflowStatus.AWAITING_APPROVAL.value, WorkflowStatus.PAUSED.value}:
            raise ConflictError(
                f"This workflow is {run.status.lower().replace('_', ' ')} and cannot be resumed.",
                detail={"status": run.status},
            )

        with session_scope() as db:
            service = ApprovalService(db)
            approval = None
            if approval_id:
                approval = service.get(approval_id)
            else:
                pending = service.latest_pending(run.project_id)
                approval = pending
            if approval is None:
                raise NotFoundError("There is no pending approval to decide for this project.")
            if approval.status != ApprovalStatus.PENDING.value:
                raise ConflictError("This approval has already been decided.")

            service.decide(
                approval.id,
                user=user,
                decision=decision,
                comments=comments,
                instructions=instructions,
                edited_content=edited_content,
            )
            resolved_approval_id = approval.id
            project_id = run.project_id

            run.status = WorkflowStatus.RUNNING.value
            run.awaiting_approval = False
            self_db = db
            self_db.commit()

        payload = {
            "decision": decision.value,
            "comments": comments,
            "instructions": instructions,
            "approval_id": resolved_approval_id,
            "decided_by": user.full_name or user.email,
        }
        bus.emit(
            "workflow_resumed", project_id, run_id=run_id,
            decision=decision.value, stage=run.current_stage,
            message=f"Human decision received ({decision.value.replace('_', ' ').lower()}); "
                    "workflow resuming",
        )
        if background:
            _EXECUTOR.submit(self._drive, run_id, None, payload)
        else:
            self._drive(run_id, None, payload)
        return self.get_run(run_id)

    # ------------------------------------------------------------------- driving
    def _drive(self, run_id: str, state: DevForgeState | None, resume_payload: dict | None) -> None:
        """Run (or continue) the graph until it suspends, completes or fails."""
        graph = get_graph()
        run = self.get_run(run_id)
        config = {"configurable": {"thread_id": run.thread_id}, "recursion_limit": 60}

        try:
            if resume_payload is None:
                result = graph.invoke(state, config)
            else:
                result = graph.invoke(Command(resume=resume_payload), config)
        except Exception as exc:  # noqa: BLE001 - the run must be marked failed, not crash a thread
            logger.exception("Workflow run %s failed", run_id)
            self._mark_failed(run_id, str(exc))
            return

        interrupt_payload = self._extract_interrupt(result, config, graph)
        if interrupt_payload is not None:
            self._mark_awaiting_approval(run_id, interrupt_payload, result)
            return
        self._mark_finished(run_id, result)

    @staticmethod
    def _extract_interrupt(result: dict | None, config: dict, graph: Any) -> dict | None:
        if isinstance(result, dict) and result.get("__interrupt__"):
            interrupts = result["__interrupt__"]
            value = getattr(interrupts[0], "value", None)
            if isinstance(value, dict):
                return value
        # Fallback: ask the checkpointer where the graph stopped.
        try:
            snapshot = graph.get_state(config)
            if snapshot.next:
                for task in snapshot.tasks:
                    for item in getattr(task, "interrupts", []) or []:
                        if isinstance(getattr(item, "value", None), dict):
                            return item.value
        except Exception:  # pragma: no cover - defensive
            return None
        return None

    # ------------------------------------------------------------------ reporting
    def _mark_awaiting_approval(self, run_id: str, payload: dict, state: dict) -> None:
        stage = payload.get("stage", "")
        with session_scope() as db:
            run = db.get(WorkflowRun, run_id)
            if run is None:  # pragma: no cover
                return
            run.status = WorkflowStatus.AWAITING_APPROVAL.value
            run.awaiting_approval = True
            run.pending_approval_id = payload.get("approval_id")
            run.current_stage = stage
            run.current_node = payload.get("gate", "")
            run.stage_iterations = state.get("iterations", {}) if isinstance(state, dict) else {}
            run.total_steps = state.get("total_steps", run.total_steps) if isinstance(state, dict) else run.total_steps
            run.state_snapshot = self._snapshot(state)
            db.commit()
            self._record_step(db, run, node=payload.get("gate", ""), stage=stage,
                              status=StageStatus.AWAITING_APPROVAL.value,
                              summary=f"Awaiting human decision: {payload.get('question', '')}")
            ProjectService(db).mark_awaiting_approval(
                run.project_id, stage=stage, approval_id=payload.get("approval_id", "")
            )
            workspace = WorkspaceService()
            workspace.write_workflow_metadata(run.project_id, {
                "run_id": run_id, "status": run.status, "stage": stage,
                "awaiting_approval": True,
                "approval_id": payload.get("approval_id"),
                "state": self._snapshot(state),
            })
            AuditService(db).record(
                action="workflow.awaiting_approval",
                project_id=run.project_id,
                actor_type=ActorType.SYSTEM,
                actor_label="workflow",
                entity_type="workflow_run",
                entity_id=run_id,
                stage=stage,
                summary=f"{STAGE_LABELS.get(stage, stage)} stage is waiting for human approval",
            )
        bus.emit(
            "workflow_updated", self._project_of(run_id), run_id=run_id, stage=stage,
            status=StageStatus.AWAITING_APPROVAL.value,
            message=f"{STAGE_LABELS.get(stage, stage)} is waiting for your approval",
        )

    def _mark_finished(self, run_id: str, state: dict) -> None:
        with session_scope() as db:
            run = db.get(WorkflowRun, run_id)
            if run is None:  # pragma: no cover
                return
            status = (state or {}).get("status", WorkflowStatus.COMPLETED.value)
            run.status = status
            run.awaiting_approval = False
            run.finished_at = utcnow()
            run.total_steps = (state or {}).get("total_steps", run.total_steps)
            run.stage_iterations = (state or {}).get("iterations", run.stage_iterations)
            run.state_snapshot = self._snapshot(state)
            db.commit()
            self._record_step(db, run, node="finalize", stage=run.current_stage,
                              status=StageStatus.COMPLETED.value,
                              summary=f"Workflow {status.lower()}")
            project = ProjectService(db).get(run.project_id)
            project.workflow_status = status
            project.stage_status = (
                StageStatus.COMPLETED.value if status == WorkflowStatus.COMPLETED.value
                else project.stage_status
            )
            if status == WorkflowStatus.COMPLETED.value:
                project.progress_percent = 100
            db.commit()
            WorkspaceService().write_workflow_metadata(run.project_id, {
                "run_id": run_id, "status": status,
                "finished_at": run.finished_at.isoformat() if run.finished_at else "",
                "state": self._snapshot(state),
            })
            AuditService(db).record(
                action="workflow.finished",
                project_id=run.project_id,
                actor_type=ActorType.SYSTEM,
                actor_label="workflow",
                entity_type="workflow_run",
                entity_id=run_id,
                stage=run.current_stage,
                summary=f"Workflow {status.lower()} after {run.total_steps} step(s)",
            )
        bus.emit("workflow_completed", self._project_of(run_id), run_id=run_id, status=status,
                 message=f"Workflow {status.lower()}")

    def _mark_failed(self, run_id: str, error: str) -> None:
        with session_scope() as db:
            run = db.get(WorkflowRun, run_id)
            if run is None:  # pragma: no cover
                return
            run.status = WorkflowStatus.FAILED.value
            run.awaiting_approval = False
            run.finished_at = utcnow()
            run.last_error = error[:2000]
            db.commit()
            self._record_step(db, run, node=run.current_node, stage=run.current_stage,
                              status=StageStatus.FAILED.value, summary=error[:400])
            project = ProjectService(db).get(run.project_id)
            project.workflow_status = WorkflowStatus.FAILED.value
            project.stage_status = StageStatus.FAILED.value
            db.commit()
            AuditService(db).record(
                action="workflow.failed",
                project_id=run.project_id,
                actor_type=ActorType.SYSTEM,
                actor_label="workflow",
                entity_type="workflow_run",
                entity_id=run_id,
                stage=run.current_stage,
                summary=f"Workflow failed: {error[:200]}",
                detail={"error": error[:1000]},
            )
        bus.emit("workflow_failed", self._project_of(run_id), run_id=run_id, error=error[:400])

    def _record_step(self, db, run: WorkflowRun, *, node: str, stage: str,  # noqa: ANN001
                     status: str, summary: str = "") -> None:
        step_index = (db.scalar(
            select(WorkflowState.step_index)
            .where(WorkflowState.run_id == run.id)
            .order_by(desc(WorkflowState.step_index))
        ) or 0) + 1
        db.add(WorkflowState(
            run_id=run.id,
            project_id=run.project_id,
            step_index=step_index,
            node=node,
            stage=stage,
            status=status,
            summary=summary[:400],
            state={"stage_iterations": run.stage_iterations, "total_steps": run.total_steps},
        ))
        db.commit()

    # -------------------------------------------------------------------- reads
    def get_run(self, run_id: str) -> WorkflowRun:
        with session_scope() as db:
            run = db.get(WorkflowRun, run_id)
            if run is None:
                raise NotFoundError("Workflow run not found.")
            db.expunge(run)
            return run

    def latest_run(self, project_id: str) -> WorkflowRun | None:
        with session_scope() as db:
            run = db.scalars(
                select(WorkflowRun).where(WorkflowRun.project_id == project_id)
                .order_by(desc(WorkflowRun.created_at))
            ).first()
            if run is not None:
                db.expunge(run)
            return run

    def steps(self, run_id: str) -> list[WorkflowState]:
        with session_scope() as db:
            return list(db.scalars(
                select(WorkflowState).where(WorkflowState.run_id == run_id)
                .order_by(WorkflowState.step_index)
            ))

    def overview(self, project_id: str) -> dict:
        with session_scope() as db:
            run = db.scalars(
                select(WorkflowRun).where(WorkflowRun.project_id == project_id)
                .order_by(desc(WorkflowRun.created_at))
            ).first()
            service = ApprovalService(db)
            pending = service.latest_pending(project_id)
            project_service = ProjectService(db)
            run_payload = project_service._run_payload(run) if run else None
            pending_payload = project_service._approval_payload(pending) if pending else None
            dashboard = project_service.build_dashboard(project_service.get(project_id))
            return {
                "run": run_payload,
                "project_status": dashboard["project"].workflow_status,
                "current_stage": dashboard["project"].current_stage,
                "stages": dashboard["stages"],
                "pending_approval": pending_payload,
                "can_resume": bool(pending and run and run.status
                                   in {WorkflowStatus.AWAITING_APPROVAL.value,
                                       WorkflowStatus.PAUSED.value}),
                "iteration_budget": {
                    "max_stage_iterations": run.max_stage_iterations if run else settings.max_stage_iterations,
                    "used": (run.stage_iterations if run else {}) or {},
                },
            }

    def resume_after_delivery_confirmation(self, run_id: str, *, user: User,
                                           message: str = "") -> WorkflowRun:
        """Continue the run once the human has confirmed the git operations."""
        run = self.get_run(run_id)
        with session_scope() as db:
            run_db = db.get(WorkflowRun, run_id)
            if run_db is None:  # pragma: no cover
                raise NotFoundError("Workflow run not found.")
            run_db.status = WorkflowStatus.RUNNING.value
            db.commit()
            AuditService(db).record(
                action="workflow.delivery_confirmed",
                project_id=run_db.project_id,
                user=user,
                entity_type="workflow_run",
                entity_id=run_id,
                stage=Stage.DELIVERY.value,
                summary=f"{user.full_name or user.email} confirmed delivery: {message[:200]}",
            )
        _EXECUTOR.submit(self._drive, run_id, None, {
            "decision": ApprovalDecision.APPROVE.value,
            "comments": message,
            "instructions": "",
            "approval_id": "",
            "decided_by": user.full_name or user.email,
        })
        return self.get_run(run_id)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _snapshot(state: dict | None) -> dict:
        """JSON-safe subset of the workflow state for the database and workspace."""
        if not isinstance(state, dict):
            return {}
        safe_keys = {
            "current_stage", "current_node", "status", "iterations", "total_steps",
            "stage_records", "approval", "approval_status", "errors", "warnings",
            "test_results", "security_results", "delivery", "source_changes",
        }
        snapshot: dict[str, Any] = {}
        for key in safe_keys:
            value = state.get(key)
            if value is None:
                continue
            try:
                json.dumps(value, default=str)
                snapshot[key] = value
            except (TypeError, ValueError):
                snapshot[key] = str(value)[:2000]
        if "messages" in state and isinstance(state["messages"], list):
            snapshot["messages"] = state["messages"][-25:]
        return snapshot

    @staticmethod
    def _project_of(run_id: str) -> str:
        with session_scope() as db:
            run = db.get(WorkflowRun, run_id)
            return run.project_id if run else ""


def workflow_engine() -> WorkflowEngine:
    return WorkflowEngine()
