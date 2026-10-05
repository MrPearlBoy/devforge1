"""Project memory: embedded knowledge chunks retrievable before agent calls."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Timestamped, UUIDPrimaryKey


class KnowledgeChunk(Base, UUIDPrimaryKey, Timestamped):
    """A retrievable slice of project context.

    ``embedding`` is stored as JSON so the default deployment works without the
    pgvector extension; when ``VECTOR_BACKEND=pgvector`` the migration switches
    the column to a native ``vector`` type and the same service code is used
    through the :class:`VectorStore` abstraction.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        sa.Index("ix_knowledge_chunks_project", "project_id", "source_type"),
        sa.Index("ix_knowledge_chunks_source", "project_id", "source_ref"),
    )

    project_id: Mapped[str] = mapped_column(
        sa.Uuid(as_uuid=False), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(sa.String(200), nullable=False, default="")
    chunk_index: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    token_estimate: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    embedding: Mapped[list | None] = mapped_column(sa.JSON, nullable=True)
    embedding_model: Mapped[str] = mapped_column(sa.String(80), nullable=False, default="")
    meta: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
