"""GitHub/Git repository linkage and the audit trail of every remote operation."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import GitOperationStatus


class Repository(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "repositories"
    __table_args__ = (sa.UniqueConstraint("project_id", name="uq_repository_project"),)

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="github")
    url: Mapped[str] = mapped_column(sa.String(500), nullable=False, default="")
    owner: Mapped[str] = mapped_column(sa.String(200), nullable=False, default="")
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False, default="")
    default_branch: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="main")
    working_branch: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="")
    local_path: Mapped[str] = mapped_column(sa.String(600), nullable=False, default="")

    #: Fernet-encrypted token. Raw tokens are never persisted or returned by the API.
    token_encrypted: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    auth_configured: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    status: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="CONNECTED")
    last_synced_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_commit_sha: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    meta: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)

    operations: Mapped[list["GitOperation"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )


class GitOperation(Base, UUIDPrimaryKey, Timestamped):
    """Audit record for every git action (human actions and agent proposals)."""

    __tablename__ = "git_operations"
    __table_args__ = (sa.Index("ix_git_operations_project", "project_id", "created_at"),)

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    repository_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("repositories.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    operation: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=GitOperationStatus.PENDING_CONFIRMATION.value
    )
    branch: Mapped[str] = mapped_column(sa.String(120), nullable=False, default="")
    commit_sha: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    message: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    #: Remote/destructive actions require an explicit human confirmation flag.
    confirmed_by_user: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    detail: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")

    repository: Mapped[Repository | None] = relationship(back_populates="operations")
