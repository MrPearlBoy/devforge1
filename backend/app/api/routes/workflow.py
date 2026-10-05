"""Workflow endpoints: start / inspect / resume the SDLC orchestration."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep
from app.core.errors import ConflictError
from app.models.workflow import WorkflowRun
from app.schemas.common import Message
from app.schemas.workflow import (
    ResumeWorkflowRequest,
    StartWorkflowRequest,
    WorkflowOverview,
    WorkflowRunRead,
    WorkflowStateRead,
)
from app.services.project_service import ProjectService
from app.workflows.engine import WorkflowEngine

router = APIRouter(prefix="/projects/{project_id}/workflow", tags=["workflow"])


@router.post("/start", response_model=WorkflowRunRead, summary="Start the AI-assisted SDLC")
def start_workflow(project: EditableProjectDep, payload: StartWorkflowRequest, db: DbSession,
                   user: CurrentUser) -> WorkflowRunRead:
    if not project.requirement_input.strip() and not payload.instructions.strip():
        raise ConflictError(
            "Describe what should be built before starting the workflow "
            "(project requirement or start instructions)."
        )
    run = WorkflowEngine().start(
        project.id,
        user=user,
        instructions=payload.instructions,
        restart=payload.restart,
        background=True,
    )
    return WorkflowRunRead.model_validate(run)


@router.get("", response_model=WorkflowOverview, summary="Workflow overview with stage statuses")
def workflow_overview(project: ProjectDep, db: DbSession) -> WorkflowOverview:
    return WorkflowOverview(**WorkflowEngine().overview(project.id))


@router.post("/resume", response_model=WorkflowRunRead, summary="Resume after a pause")
def resume_workflow(project: EditableProjectDep, payload: ResumeWorkflowRequest, db: DbSession,
                    user: CurrentUser) -> WorkflowRunRead:
    """Continue a run that was paused for human intervention (approval or escalation).

    Approvals normally flow through ``/api/approvals/{id}/approve``; this endpoint
    exists for the "continue anyway" action after an escalation, and it records the
    human's note in the audit trail.
    """
    run = WorkflowEngine().latest_run(project.id)
    if run is None:
        raise ConflictError("This project has no workflow run yet.")
    if run.status not in {"AWAITING_APPROVAL", "PAUSED"}:
        raise ConflictError(f"This workflow is {run.status.lower().replace('_', ' ')}.")

    engine = WorkflowEngine()
    from app.models.enums import ApprovalDecision

    pending = None
    from app.services.approval_service import ApprovalService

    pending = ApprovalService(db).latest_pending(project.id)
    if pending is not None:
        resumed = engine.resume(
            run.id, user=user, decision=ApprovalDecision.APPROVE,
            comments=payload.comments or "Continued by human after review.",
            approval_id=pending.id, background=True,
        )
    else:  # escalation with no open approval: acknowledge and continue the graph
        resumed = engine.resume_after_delivery_confirmation(run.id, user=user,
                                                            message=payload.comments)
    return WorkflowRunRead.model_validate(resumed)


@router.get("/runs", response_model=list[WorkflowRunRead], summary="History of workflow runs")
def list_runs(project: ProjectDep, db: DbSession) -> list[WorkflowRunRead]:
    from sqlalchemy import desc, select

    runs = db.scalars(
        select(WorkflowRun).where(WorkflowRun.project_id == project.id)
        .order_by(desc(WorkflowRun.created_at)).limit(50)
    )
    return [WorkflowRunRead.model_validate(run) for run in runs]


@router.get("/runs/{run_id}/steps", response_model=list[WorkflowStateRead],
            summary="Step-by-step state history of a run")
def run_steps(project: ProjectDep, run_id: str) -> list[WorkflowStateRead]:
    steps = WorkflowEngine().steps(run_id)
    return [WorkflowStateRead.model_validate(step) for step in steps]


@router.get("/run", response_model=WorkflowRunRead | None, summary="Latest run for this project")
def latest_run(project: ProjectDep) -> WorkflowRunRead | None:
    run = WorkflowEngine().latest_run(project.id)
    return WorkflowRunRead.model_validate(run) if run else None
