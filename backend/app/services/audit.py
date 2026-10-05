"""Audit logging service — the single place where activity history is written."""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.events import bus
from app.models.audit import AuditLog
from app.models.enums import ActorType
from app.models.user import User


class AuditService:
    """Writes audit rows and (optionally) publishes them to the live event bus."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ write
    def record(
        self,
        *,
        action: str,
        project_id: str | None = None,
        user: User | None = None,
        actor_type: ActorType = ActorType.USER,
        actor_label: str = "",
        entity_type: str = "",
        entity_id: str = "",
        stage: str = "",
        summary: str = "",
        detail: dict | None = None,
        publish: bool = True,
    ) -> AuditLog:
        label = actor_label or (user.full_name or user.email if user else actor_type.value)
        entry = AuditLog(
            project_id=project_id,
            user_id=user.id if user else None,
            actor_type=actor_type.value,
            actor_label=label,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id or ""),
            stage=stage,
            summary=summary,
            detail=detail or {},
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        if publish and project_id:
            bus.emit(
                "activity_logged",
                project_id,
                id=entry.id,
                action=entry.action,
                summary=entry.summary,
                actor_type=entry.actor_type,
                actor_label=entry.actor_label,
                stage=entry.stage,
                created_at=entry.created_at.isoformat(),
            )
        return entry

    # ------------------------------------------------------------------- read
    def list_for_project(
        self, project_id: str, *, limit: int = 100, offset: int = 0, action: str | None = None
    ) -> list[AuditLog]:
        stmt = select(AuditLog).where(AuditLog.project_id == project_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        stmt = stmt.order_by(desc(AuditLog.created_at)).limit(limit).offset(offset)
        return list(self.db.scalars(stmt))

    def list_for_user(self, user_id: str, *, limit: int = 50) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
