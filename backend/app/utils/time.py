"""Time helpers.

SQLite (and some drivers) return naive datetimes even for timezone-aware columns,
so timestamps coming back from the database are normalised to UTC-aware before any
arithmetic. All DevForge timestamps are UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(value: datetime | None) -> datetime | None:
    """Return ``value`` as a UTC-aware datetime (assumes UTC when naive)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def duration_ms(start: datetime | None, end: datetime | None) -> int:
    """Milliseconds between two timestamps, tolerant of naive/aware mixtures."""
    start, end = ensure_aware(start), ensure_aware(end)
    if start is None or end is None:
        return 0
    return max(0, int((end - start).total_seconds() * 1000))


def iso(value: datetime | None) -> str:
    aware = ensure_aware(value)
    return aware.isoformat() if aware else ""
