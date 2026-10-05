"""Agent catalog and human/agent work items (tasks)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import TaskPriority, TaskStatus


class Agent(Base, UUIDPrimaryKey, Timestamped):
    """Registry row describing a specialised agent available in the platform."""

    __tablename__ = "agents"

    key: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="")
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    order_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    icon: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="robot")
    capabilities: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    output_artifact_types: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)


class Task(Base, UUIDPrimaryKey, Timestamped):
    """A unit of work visible on the project board (agent-generated or manual)."""

    __tablename__ = "tasks"
    __table_args__ = (sa.Index("ix_tasks_project_status", "project_id", "status"),)

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=TaskStatus.TODO.value)
    priority: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=TaskPriority.MEDIUM.value)
    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="")
    assigned_agent_key: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    requirement_refs: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="AGENT")
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
