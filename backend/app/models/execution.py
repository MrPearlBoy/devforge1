"""Agent execution telemetry: one row per agent invocation (logging requirement)."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import AgentStatus, ExecutionTrigger, Stage


class AgentExecution(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "agent_executions"
    __table_args__ = (
        sa.Index("ix_agent_executions_project_agent", "project_id", "agent_key"),
        sa.Index("ix_agent_executions_run", "run_id"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    agent_key: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=Stage.REQUIREMENTS.value)
    trigger: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, default=ExecutionTrigger.WORKFLOW.value
    )
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=AgentStatus.RUNNING.value
    )

    mode: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="live")
    provider: Mapped[str] = mapped_column(sa.String(40), nullable=False, default="openai")
    llm_model: Mapped[str] = mapped_column(sa.String(80), nullable=False, default="")
    prompt_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    input_summary: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    output_summary: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    meta: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    started_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
