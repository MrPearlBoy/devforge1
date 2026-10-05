"""Shared model building blocks: UUID primary keys and UTC timestamps."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class UUIDPrimaryKey:
    """UUID primary key, generated application side (portable, test friendly)."""

    id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), primary_key=True, default=new_uuid
    )


class Timestamped:
    """Creation/update bookkeeping present on every mutable entity."""

    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
