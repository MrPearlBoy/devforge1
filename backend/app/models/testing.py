"""Test execution records produced by the Testing Agent / sandbox runner."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import TestStatus


class TestRun(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "test_runs"
    __table_args__ = (sa.Index("ix_test_runs_project", "project_id", "created_at"),)

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=TestStatus.ERROR.value)
    total: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    command: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    provider: Mapped[str] = mapped_column(sa.String(40), nullable=False, default="subprocess")
    duration_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    triggered_by: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="AGENT")
    raw_output: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    report: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    confirmed_by_user: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    results: Mapped[list["TestResult"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )


class TestResult(Base, UUIDPrimaryKey, Timestamped):
    """Individual test case outcome."""

    __tablename__ = "test_results"
    __table_args__ = (sa.Index("ix_test_results_run", "test_run_id"),)

    test_run_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    file_path: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=TestStatus.ERROR.value)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    requirement_refs: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)

    test_run: Mapped[TestRun] = relationship(back_populates="results")
