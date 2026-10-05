"""Audit log and activity feed."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import desc, func, select

from app.api.deps import CurrentUser, DbSession, ProjectDep
from app.models.audit import AuditLog
from app.schemas.agent import AuditLogRead

router = APIRouter(tags=["activity"])

#: Human-readable verbs for the activity feed (the raw action stays in ``action``).
ACTION_LABELS = {
    "workflow.started": "started the workflow",
    "workflow.awaiting_approval": "is waiting for approval",
    "workflow.resumed": "resumed the workflow",
    "workflow.completed": "completed the workflow",
    "workflow.failed": "hit an error",
    "workflow.delivery_confirmed": "confirmed delivery",
    "approval.requested": "requested approval",
    "approval.approved": "approved",
    "approval.rejected": "rejected",
    "approval.changes_requested": "requested changes",
    "agent.failed": "failed",
    "code.changes_applied": "applied code changes",
    "code.change_set_proposed": "proposed code changes",
    "tests.executed": "ran the test suite",
    "security.scan_completed": "completed a security scan",
    "security.finding_triaged": "triaged a finding",
    "github.connected": "connected a repository",
    "github.committed": "committed",
    "github.pushed": "pushed",
    "sandbox.command_executed": "ran a sandboxed command",
    "project.created": "created the project",
    "chat.message": "sent a message",
}


@router.get("/projects/{project_id}/activity", response_model=list[AuditLogRead],
            summary="Project activity / audit log")
def project_activity(project: ProjectDep, db: DbSession, limit: int = 100,
                     action: str = "", stage: str = "") -> list[AuditLogRead]:
    stmt = select(AuditLog).where(AuditLog.project_id == project.id)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if stage:
        stmt = stmt.where(AuditLog.stage == stage)
    stmt = stmt.order_by(desc(AuditLog.created_at)).limit(min(limit, 500))
    return [AuditLogRead.model_validate(row) for row in db.scalars(stmt)]


@router.get("/activity", response_model=list[AuditLogRead], summary="Global activity feed")
def global_activity(db: DbSession, user: CurrentUser, limit: int = 100) -> list[AuditLogRead]:
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(min(limit, 500))
    return [AuditLogRead.model_validate(row) for row in db.scalars(stmt)]


@router.get("/projects/{project_id}/activity/summary", summary="Activity counters by action")
def activity_summary(project: ProjectDep, db: DbSession) -> dict:
    rows = db.execute(
        select(AuditLog.action, func.count(AuditLog.id))
        .where(AuditLog.project_id == project.id)
        .group_by(AuditLog.action)
    ).all()
    counts = {action: total for action, total in rows}
    return {
        "total": sum(counts.values()),
        "by_action": counts,
        "labels": {action: ACTION_LABELS.get(action, action) for action in counts},
    }


@router.get("/activity/labels", summary="Human-readable verbs for the activity feed")
def action_labels() -> dict:
    return ACTION_LABELS
