"""Users and project membership."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import ProjectRole, Role


class User(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(sa.String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(sa.String(160), nullable=False, default="")
    hashed_password: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[str] = mapped_column(sa.String(32), nullable=False, default=Role.DEVELOPER.value)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    last_login_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["ProjectMember"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )


class ProjectMember(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "project_members"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        sa.Index("ix_project_members_project", "project_id"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_role: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, default=ProjectRole.EDITOR.value
    )

    user: Mapped[User] = relationship(back_populates="memberships")
    project: Mapped["Project"] = relationship(back_populates="members")  # noqa: F821
