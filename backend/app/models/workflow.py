"""Workflow run + per-step state snapshots (auditability of orchestration)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import Stage, StageStatus, WorkflowStatus


class WorkflowRun(Base, UUIDPrimaryKey, Timestamped):
    """One execution of the DevForge SDLC graph for a project."""

    __tablename__ = "workflow_runs"
    __table_args__ = (sa.Index("ix_workflow_runs_project_status", "project_id", "status"),)

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=WorkflowStatus.RUNNING.value
    )
    engine: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="langgraph")
    thread_id: Mapped[str] = mapped_column(sa.String(80), nullable=False, index=True)

    current_stage: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=Stage.REQUIREMENTS.value
    )
    current_node: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    awaiting_approval: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    pending_approval_id: Mapped[str | None] = mapped_column(sa.Uuid(as_uuid=False), nullable=True)

    stage_iterations: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    total_steps: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    max_stage_iterations: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=3)

    started_by_user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    state_snapshot: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    project: Mapped["Project"] = relationship(back_populates="workflow_runs")  # noqa: F821
    steps: Mapped[list["WorkflowState"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="WorkflowState.step_index"
    )


class WorkflowState(Base, UUIDPrimaryKey, Timestamped):
    """Immutable-ish snapshot captured after each graph node execution."""

    __tablename__ = "workflow_states"
    __table_args__ = (sa.Index("ix_workflow_states_run_step", "run_id", "step_index"),)

    run_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    step_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    node: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=Stage.REQUIREMENTS.value)
    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=StageStatus.RUNNING.value)
    summary: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    state: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    run: Mapped[WorkflowRun] = relationship(back_populates="steps")
