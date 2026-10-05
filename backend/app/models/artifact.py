"""Artifacts: every AI (or human) produced deliverable, versioned and traceable."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import ArtifactStatus, Stage


class Artifact(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "artifacts"
    __table_args__ = (
        sa.Index("ix_artifacts_project_stage", "project_id", "stage"),
        sa.Index("ix_artifacts_project_type", "project_id", "type"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )

    type: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    stage: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=Stage.REQUIREMENTS.value)
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False, default="")
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")

    #: Markdown/text body, kept for display and diffing.
    content: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    #: Structured representation (agent schema output, file list, metrics...).
    data: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    #: Workspace relative path of the materialised file, when applicable.
    path: Mapped[str] = mapped_column(sa.String(600), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(sa.String(80), nullable=False, default="")

    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=ArtifactStatus.DRAFT.value
    )
    produced_by_agent_key: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Lightweight traceability anchors, e.g. ``["REQ-001", "ARCH-002"]``.
    trace_refs: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)

    versions: Mapped[list["ArtifactVersion"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan", order_by="ArtifactVersion.version"
    )


class ArtifactVersion(Base, UUIDPrimaryKey, Timestamped):
    """Immutable historical revision of an artifact (append-only)."""

    __tablename__ = "artifact_versions"
    __table_args__ = (sa.Index("ix_artifact_versions_artifact", "artifact_id", "version"),)

    artifact_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    data: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(sa.String(80), nullable=False, default="")
    change_reason: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    author_type: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="AGENT")
    author_label: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="")

    artifact: Mapped[Artifact] = relationship(back_populates="versions")
