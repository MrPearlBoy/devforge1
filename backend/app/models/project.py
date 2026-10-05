"""Projects: the central aggregate of the platform."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import Stage, StageStatus, WorkflowStatus


class Project(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    slug: Mapped[str] = mapped_column(sa.String(220), nullable=False, unique=True, index=True)
    #: Raw natural-language idea supplied by the human.
    requirement_input: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")

    owner_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    current_stage: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=Stage.REQUIREMENTS.value
    )
    workflow_status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=WorkflowStatus.NOT_STARTED.value, index=True
    )
    stage_status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=StageStatus.PENDING.value
    )
    progress_percent: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    tech_stack: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    tags: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    settings: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    workspace_path: Mapped[str] = mapped_column(sa.String(600), nullable=False, default="")
    is_archived: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)

    owner: Mapped["User"] = relationship()  # noqa: F821
    members: Mapped[list["ProjectMember"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan"
    )
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan", order_by="desc(WorkflowRun.created_at)"
    )
