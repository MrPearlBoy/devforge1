"""Approval endpoints — the human control plane.

``approve`` / ``reject`` / ``changes`` record the decision *and* resume the LangGraph
run that is suspended on that gate, so the database and the orchestration state never
diverge.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import ApprovalDecision, ApprovalStatus, ArtifactType
from app.models.workflow import WorkflowRun
from app.schemas.approval import ApprovalDecisionRequest, ApprovalDetail, ApprovalRead
from app.services.approval_service import ApprovalService
from app.services.artifact_service import ArtifactService
from app.services.change_set import ChangeSetService
from app.services.project_service import ProjectService
from app.workflows.engine import WorkflowEngine

router = APIRouter(tags=["approvals"])


@router.get("/projects/{project_id}/approvals", response_model=list[ApprovalDetail],
            summary="Approval history for a project")
def list_approvals(project: ProjectDep, db: DbSession, approval_status: str | None = None) -> list[ApprovalDetail]:
    service = ApprovalService(db)
    project_service = ProjectService(db)
    rows = service.list_for_project(project.id, status=approval_status, limit=200)
    return [ApprovalDetail(**project_service._approval_payload(row)) for row in rows]


@router.get("/projects/{project_id}/approvals/pending", response_model=list[ApprovalDetail],
            summary="Open approval gates")
def pending_approvals(project: ProjectDep, db: DbSession) -> list[ApprovalDetail]:
    service = ApprovalService(db)
    project_service = ProjectService(db)
    return [
        ApprovalDetail(**project_service._approval_payload(row))
        for row in service.pending(project.id)
    ]


@router.get("/approvals/{approval_id}", response_model=ApprovalDetail, summary="Approval detail")
def get_approval(approval_id: str, db: DbSession, user: CurrentUser) -> ApprovalDetail:
    service = ApprovalService(db)
    approval = service.get(approval_id)
    project = ProjectService(db).get(approval.project_id)
    ProjectService(db).ensure_access(project, user)
    return ApprovalDetail(**ProjectService(db)._approval_payload(approval))


def _decide(
    *,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    db,  # noqa: ANN001 - Session
    user,  # noqa: ANN001 - User
) -> ApprovalDetail:
    """Record a decision and continue the workflow that is waiting on it."""
    service = ApprovalService(db)
    approval = service.get(approval_id)
    project = ProjectService(db).get(approval.project_id)
    ProjectService(db).ensure_access(project, user, write=True)
    if approval.status != ApprovalStatus.PENDING.value:
        raise ConflictError(
            f"This approval was already {approval.status.lower().replace('_', ' ')}.",
            detail={"status": approval.status},
        )

    run = db.get(WorkflowRun, approval.run_id) if approval.run_id else None
    suspended_run = (
        run is not None
        and run.status in {"AWAITING_APPROVAL", "PAUSED"}
        and run.pending_approval_id == approval.id
    )

    if suspended_run:
        # The orchestration engine records the decision and resumes the graph.
        WorkflowEngine().resume(
            run.id,
            user=user,
            decision=payload.decision,
            comments=payload.comments,
            instructions=payload.instructions,
            approval_id=approval.id,
            edited_content=payload.edited_content,
            background=True,
        )
    else:
        service.decide(
            approval.id,
            user=user,
            decision=payload.decision,
            comments=payload.comments,
            instructions=payload.instructions,
            edited_content=payload.edited_content,
        )
        # Chat-initiated approvals: applying an approved change set is the effect.
        if payload.decision == ApprovalDecision.APPROVE and approval.artifact_id:
            artifact = ArtifactService(db).get(approval.artifact_id)
            if artifact is not None and artifact.type == ArtifactType.CHANGE_SET.value:
                ChangeSetService(db).ensure_applied(artifact, user=user)

    db.expire_all()
    refreshed = service.get(approval_id)
    return ApprovalDetail(**ProjectService(db)._approval_payload(refreshed))


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalDetail,
             summary="Approve a stage")
def approve(approval_id: str, payload: ApprovalDecisionRequest, db: DbSession,
            user: CurrentUser) -> ApprovalDetail:
    payload.decision = ApprovalDecision.APPROVE
    return _decide(approval_id=approval_id, payload=payload, db=db, user=user)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalDetail,
             summary="Reject a stage")
def reject(approval_id: str, payload: ApprovalDecisionRequest, db: DbSession,
           user: CurrentUser) -> ApprovalDetail:
    payload.decision = ApprovalDecision.REJECT
    return _decide(approval_id=approval_id, payload=payload, db=db, user=user)


@router.post("/approvals/{approval_id}/changes", response_model=ApprovalDetail,
             summary="Request changes from the responsible agent")
def request_changes(approval_id: str, payload: ApprovalDecisionRequest, db: DbSession,
                    user: CurrentUser) -> ApprovalDetail:
    if not (payload.comments.strip() or payload.instructions.strip()):
        raise ConflictError(
            "Describe what should change so the agent can act on it.",
        )
    payload.decision = ApprovalDecision.REQUEST_CHANGES
    return _decide(approval_id=approval_id, payload=payload, db=db, user=user)


@router.get("/approvals/{approval_id}/artifact", response_model=ApprovalRead,
            summary="Artifact under review (use /api/artifacts/{id} for the full body)")
def approval_artifact(approval_id: str, db: DbSession, user: CurrentUser) -> ApprovalRead:
    approval = ApprovalService(db).get(approval_id)
    project = ProjectService(db).get(approval.project_id)
    ProjectService(db).ensure_access(project, user)
    return ApprovalRead.model_validate(approval)
