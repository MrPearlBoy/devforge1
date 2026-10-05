"""Persisted human <-> agent conversations."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import MessageRole


class AgentMessage(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "agent_messages"
    __table_args__ = (
        sa.Index("ix_agent_messages_project_agent", "project_id", "agent_key", "created_at"),
        sa.Index("ix_agent_messages_thread", "thread_id", "created_at"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: ``None`` for a shared/human-only thread.
    agent_key: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    thread_id: Mapped[str] = mapped_column(sa.String(80), nullable=False, default="default")

    role: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=MessageRole.USER.value)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    execution_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("agent_executions.id", ondelete="SET NULL"), nullable=True
    )
    #: Structured extras: proposed file changes, references, token usage...
    meta: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
