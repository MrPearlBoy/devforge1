"""SQLAlchemy engine / session management.

DevForge targets PostgreSQL in deployment, but every layer is written against
SQLAlchemy 2.0 so that SQLite works as a zero-configuration development, demo and
test database (``DATABASE_URL=sqlite:///./devforge.db``).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all DevForge models."""


def _engine_kwargs() -> dict:
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update({"pool_size": 10, "max_overflow": 20})
    return kwargs


engine: Engine = create_engine(settings.database_url, **_engine_kwargs())

if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
        """Enable FK enforcement + WAL so SQLite behaves like the real thing."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for background work (agents, tools, workers)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables for SQLite/dev convenience (Alembic owns production schema)."""
    from app import models  # noqa: F401  (ensure all models are imported)

    Base.metadata.create_all(bind=engine)


def check_database() -> dict:
    """Lightweight connectivity probe used by ``/api/health``."""
    from sqlalchemy import text

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"connected": True, "dialect": engine.dialect.name}
    except Exception as exc:  # pragma: no cover - depends on the environment
        return {"connected": False, "dialect": engine.dialect.name, "error": str(exc)[:200]}
