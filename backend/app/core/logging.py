"""Structured-ish logging setup used by the API, agents and tools."""
from __future__ import annotations

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


class DevForgeFormatter(logging.Formatter):
    """Compact, greppable single line log format."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        base = (
            f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')} "
            f"{record.levelname:<7} {record.name:<28} {record.getMessage()}"
        )
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(DevForgeFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # Trim noisy third party loggers unless we are debugging.
    if not settings.debug:
        for noisy in ("httpx", "httpcore", "uvicorn.access"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
