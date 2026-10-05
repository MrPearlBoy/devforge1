"""Project memory: chunking, embedding and retrieval of project knowledge.

Anything an agent might need later is indexed here: requirements, architecture,
source files, tests, security findings, documentation and conversation turns.
Before an agent runs, :class:`ProjectContextService` retrieves the most relevant
chunks so answers stay grounded in the actual project.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import KnowledgeSource
from app.services.vector_store import KnowledgeHit, vector_store

logger = get_logger("devforge.knowledge")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def chunk_text(text: str, *, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    paragraphs = [p.strip() for p in text.split("\n\n")]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= size:
            current = f"{current}\n\n{paragraph}".strip()
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= size:
            current = paragraph
        else:  # very long paragraph: hard split with overlap
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start:start + size])
                start += size - overlap
            current = ""
    if current:
        chunks.append(current)
    # apply overlap stitching between consecutive hard chunks
    return [c for c in chunks if c.strip()]


class KnowledgeService:
    """Indexes and searches project knowledge through the vector store."""

    def __init__(self, gateway=None) -> None:  # noqa: ANN001 - LLMGateway (lazy import)
        self._gateway = gateway

    # ---------------------------------------------------------------- indexing
    def _embeddings(self, texts: Sequence[str]) -> tuple[list[list[float]] | None, str]:
        if not texts:
            return None, ""
        gateway = self._gateway
        if gateway is None:
            try:
                from app.tools.llm.factory import get_llm_gateway

                gateway = get_llm_gateway()
                self._gateway = gateway
            except Exception as exc:  # pragma: no cover - provider unavailable
                logger.debug("Embeddings unavailable: %s", exc)
                return None, ""
        try:
            vectors = gateway.embed(list(texts))
            model = getattr(gateway, "embedding_model", "") or ""
            return [list(v) for v in vectors], model
        except Exception as exc:
            logger.warning("Embedding generation failed, falling back to lexical search: %s", exc)
            return None, ""

    def index_text(
        self,
        db: Session,
        *,
        project_id: str,
        source_type: KnowledgeSource | str,
        source_ref: str,
        text: str,
        meta: dict | None = None,
    ) -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0
        embeddings, model = self._embeddings(chunks)
        count = vector_store.upsert(
            db,
            project_id=project_id,
            source_type=str(source_type),
            source_ref=source_ref,
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=model,
            meta=meta,
        )
        logger.debug("Indexed %s chunks from %s (%s)", count, source_ref, source_type)
        return count

    def index_files(self, db: Session, *, project_id: str, files: dict[str, str],
                    source_type: KnowledgeSource = KnowledgeSource.SOURCE_CODE) -> int:
        total = 0
        for path, content in files.items():
            if not content.strip():
                continue
            total += self.index_text(
                db,
                project_id=project_id,
                source_type=source_type,
                source_ref=path,
                text=f"# File: {path}\n\n{content}",
                meta={"path": path},
            )
        return total

    # ---------------------------------------------------------------- retrieval
    def search(self, db: Session, *, project_id: str, query: str, limit: int = 8,
               source_types: Sequence[str] | None = None) -> list[KnowledgeHit]:
        embeddings, _ = self._embeddings([query]) if query else (None, "")
        vector = embeddings[0] if embeddings else None
        return vector_store.search(
            db,
            project_id=project_id,
            query_embedding=vector,
            query_text=query,
            limit=limit,
            source_types=source_types,
        )

    def clear(self, db: Session, *, project_id: str, source_ref: str) -> int:
        return vector_store.clear_source(db, project_id=project_id, source_ref=source_ref)
