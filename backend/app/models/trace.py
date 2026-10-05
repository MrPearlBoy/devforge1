"""Traceability links: REQ -> ARCH -> CODE -> TEST -> SEC -> DOC."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey


class TraceLink(Base, UUIDPrimaryKey, Timestamped):
    """A directed relationship between two identified engineering elements.

    Refs are stable, human readable identifiers such as ``REQ-001``,
    ``ARCH-003``, ``CODE app/main.py``, ``TEST test_auth.py::test_login``,
    ``SEC-AUTH-001`` and ``DOC README.md`` — so traceability survives code
    movement and can be rendered without joining every table.
    """

    __tablename__ = "trace_links"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "source_ref", "target_ref", "relation", name="uq_trace_link"),
        sa.Index("ix_trace_links_source", "project_id", "source_ref"),
        sa.Index("ix_trace_links_target", "project_id", "target_ref"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    source_ref: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    source_label: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")

    target_type: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    target_ref: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    target_label: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")

    relation: Mapped[str] = mapped_column(sa.String(32), nullable=False, default="implements")
    artifact_id: Mapped[str | None] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(sa.Float, nullable=False, default=1.0)
    note: Mapped[str] = mapped_column(sa.String(400), nullable=False, default="")
