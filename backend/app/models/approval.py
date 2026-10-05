"""Human-in-the-loop approval records.

Every workflow gate must be represented here before the graph is allowed to
advance: the orchestration engine blocks on a LangGraph ``interrupt`` and is
resumed only by an approval decision recorded in this table.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import ApprovalStatus, Stage


class Approval(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "approvals"
    __table_args__ = (
        sa.Index("ix_approvals_project_status", "project_id", "status"),
        sa.Index("ix_approvals_artifact", "artifact_id"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )

    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=Stage.REQUIREMENTS.value)
    #: Fine grained gate name inside the stage (e.g. ``code_review``).
    gate: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=ApprovalStatus.PENDING.value
    )
    requested_by_agent_key: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    requested_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    decided_by_user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    comments: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    decision_meta: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    artifact: Mapped["Artifact"] = relationship()  # noqa: F821
