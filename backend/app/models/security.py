"""Security findings detected by the Security Agent's static analysis pass."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey
from app.models.enums import FindingStatus, Severity


class SecurityFinding(Base, UUIDPrimaryKey, Timestamped):
    __tablename__ = "security_findings"
    __table_args__ = (
        sa.Index("ix_security_findings_project", "project_id", "severity"),
        sa.Index("ix_security_findings_scan", "scan_id"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )

    scan_id: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    rule_id: Mapped[str] = mapped_column(sa.String(40), nullable=False, default="")
    severity: Mapped[str] = mapped_column(sa.String(16), nullable=False, default=Severity.MEDIUM.value)
    category: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False, default="")
    description: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    file_path: Mapped[str] = mapped_column(sa.String(600), nullable=False, default="")
    line: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    evidence: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    recommendation: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(sa.String(24), nullable=False, default=FindingStatus.OPEN.value)
    detected_by: Mapped[str] = mapped_column(sa.String(64), nullable=False, default="security_agent")
    trace_refs: Mapped[list] = mapped_column(sa.JSON, nullable=False, default=list)
    resolved_at: Mapped[sa.DateTime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
