"""ORM models: projects, workflow events (audit trail), approvals,
test results and security findings."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """A DevForge project = one generated software application."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    task: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(32), default="created", index=True)
    status: Mapped[str] = mapped_column(String(24), default="idle", index=True)
    awaiting_gate: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default=None)
    llm_provider: Mapped[str] = mapped_column(String(40), default="mock")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    #: Full serialized WorkflowState (artifacts + iterations) for resume.
    artifacts: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class WorkflowEvent(Base):
    """Append-only audit/log trail: every agent action, state transition,
    gate decision, test run and scan result is recorded here."""

    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(32))
    stage: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Approval(Base):
    """A human-in-the-loop gate decision."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    gate: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(24))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TestResult(Base):
    """Outcome of one pytest run in the sandbox."""

    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    run_number: Mapped[int] = mapped_column(Integer, default=1)
    passed: Mapped[bool] = mapped_column(default=False)
    total: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    exit_code: Mapped[int] = mapped_column(Integer, default=-1)
    duration_s: Mapped[float] = mapped_column(default=0.0)
    summary: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SecurityFinding(Base):
    """A single vulnerability/fsm finding from the security scan."""

    __tablename__ = "security_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    file: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
