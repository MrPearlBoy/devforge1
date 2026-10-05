"""Audit log: every human action, agent execution and workflow transition."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import ActorType


class AuditLog(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "audit_logs"
    __table_args__ = (
        sa.Index("ix_audit_logs_project_time", "project_id", "created_at"),
        sa.Index("ix_audit_logs_action", "action"),
    )

    project_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=ActorType.USER.value)
    actor_label: Mapped[str] = mapped_column(sa.String(160), nullable=False, default="")

    action: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.String(48), nullable=False, default="")
    entity_id: Mapped[str] = mapped_column(sa.String(80), nullable=False, default="")
    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="")
    summary: Mapped[str] = mapped_column(sa.String(500), nullable=False, default="")
    detail: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
