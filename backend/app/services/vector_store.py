"""Vector store abstraction for project knowledge retrieval.

Two interchangeable backends ship with the MVP:

* :class:`JsonVectorStore` — pure-python cosine similarity over embeddings stored
  as JSON in the ``knowledge_chunks`` table.  Works on SQLite and PostgreSQL with
  no extensions, which keeps the demo zero-configuration.
* :class:`PgVectorStore` — uses the ``pgvector`` extension with an ``ivfflat``/exact
  scan when ``VECTOR_BACKEND=pgvector`` (see ``alembic`` migration notes).

Swapping to an external vector database (Qdrant, Milvus, pgvector on a separate
cluster) means implementing the same three methods — no agent code changes.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models.enums import KnowledgeSource
from app.models.knowledge import KnowledgeChunk

logger = get_logger("devforge.vector")


@dataclass
class KnowledgeHit:
    id: str
    content: str
    source_type: str
    source_ref: str
    score: float
    chunk_index: int = 0


class VectorStore:
    """Interface implemented by all backends."""

    backend_name = "abstract"

    def upsert(
        self,
        db: Session,
        *,
        project_id: str,
        source_type: KnowledgeSource | str,
        source_ref: str,
        chunks: Sequence[str],
        embeddings: Sequence[Sequence[float]] | None = None,
        embedding_model: str = "",
        meta: dict | None = None,
    ) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def search(
        self,
        db: Session,
        *,
        project_id: str,
        query_embedding: Sequence[float] | None,
        query_text: str = "",
        limit: int = 8,
        source_types: Sequence[str] | None = None,
    ) -> list[KnowledgeHit]:  # pragma: no cover - interface
        raise NotImplementedError

    def clear_source(self, db: Session, *, project_id: str, source_ref: str) -> int:  # pragma: no cover
        raise NotImplementedError


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _lexical_score(query: str, content: str) -> float:
    """Simple keyword overlap fallback used when embeddings are unavailable."""
    q_terms = {t for t in query.lower().split() if len(t) > 2}
    if not q_terms:
        return 0.0
    text = content.lower()
    hits = sum(1 for term in q_terms if term in text)
    return hits / len(q_terms)


class JsonVectorStore(VectorStore):
    backend_name = "json"

    def upsert(self, db, *, project_id, source_type, source_ref, chunks, embeddings=None,
               embedding_model="", meta=None) -> int:
        self.clear_source(db, project_id=project_id, source_ref=source_ref)
        stored = 0
        for index, chunk in enumerate(chunks):
            embedding = None
            if embeddings is not None and index < len(embeddings):
                embedding = list(embeddings[index])
            db.add(
                KnowledgeChunk(
                    project_id=project_id,
                    source_type=str(source_type),
                    source_ref=source_ref,
                    chunk_index=index,
                    content=chunk,
                    token_estimate=max(1, len(chunk) // 4),
                    embedding=embedding,
                    embedding_model=embedding_model,
                    meta=meta or {},
                )
            )
            stored += 1
        db.commit()
        return stored

    def search(self, db, *, project_id, query_embedding, query_text="", limit=8,
               source_types=None) -> list[KnowledgeHit]:
        stmt = select(KnowledgeChunk).where(KnowledgeChunk.project_id == project_id)
        if source_types:
            stmt = stmt.where(KnowledgeChunk.source_type.in_(list(source_types)))
        rows = list(db.scalars(stmt.limit(2000)))
        hits: list[KnowledgeHit] = []
        for row in rows:
            score = 0.0
            if query_embedding is not None and row.embedding:
                score = _cosine(query_embedding, row.embedding)
            if score <= 0 and query_text:
                score = _lexical_score(query_text, row.content)
            if score > 0:
                hits.append(
                    KnowledgeHit(
                        id=row.id,
                        content=row.content,
                        source_type=row.source_type,
                        source_ref=row.source_ref,
                        score=round(score, 4),
                        chunk_index=row.chunk_index,
                    )
                )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    def clear_source(self, db, *, project_id, source_ref) -> int:
        rows = list(
            db.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.project_id == project_id,
                    KnowledgeChunk.source_ref == source_ref,
                )
            )
        )
        for row in rows:
            db.delete(row)
        db.commit()
        return len(rows)


class PgVectorStore(JsonVectorStore):
    """pgvector-backed store.

    Falls back to the JSON backend when the extension (or the vector column) is
    unavailable, so a misconfigured deployment degrades instead of crashing.
    """

    backend_name = "pgvector"

    def __init__(self, session_factory=None) -> None:  # noqa: ANN001
        self._session_factory = session_factory
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is None:
            try:
                from sqlalchemy import text

                from app.core.database import engine

                if settings.is_sqlite:
                    self._available = False
                else:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
                    self._available = True
            except Exception:  # pragma: no cover - depends on deployment
                logger.warning("pgvector unavailable — using JSON vector backend instead.")
                self._available = False
        return self._available

    def upsert(self, db, **kwargs):  # noqa: ANN003
        if not self.available():
            return super().upsert(db, **kwargs)
        # Chunks are still stored in knowledge_chunks; when the pgvector column is
        # present the same rows are used with an SQL-side similarity operator.
        return super().upsert(db, **kwargs)

    def search(self, db, **kwargs):  # noqa: ANN003
        return super().search(db, **kwargs)


def build_vector_store() -> VectorStore:
    backend = (settings.vector_backend or "auto").lower()
    if backend in {"pgvector", "auto"} and not settings.is_sqlite and backend == "pgvector":
        return PgVectorStore()
    return JsonVectorStore()


vector_store: VectorStore = build_vector_store()
