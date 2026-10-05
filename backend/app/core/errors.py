"""Domain specific exceptions and API error translation.

Internal details (stack traces, provider payloads) are logged on the server and
never returned to clients: only a stable machine readable ``code`` and a human
readable ``message`` are exposed.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("devforge.errors")


class DevForgeError(Exception):
    """Base class for all expected application errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "devforge_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(DevForgeError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(DevForgeError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class AuthenticationError(DevForgeError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class PermissionDeniedError(DevForgeError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class ValidationFailure(DevForgeError):
    status_code = 422  # 422 Unprocessable Content (constant renamed in recent Starlette)
    code = "validation_error"


class WorkflowError(DevForgeError):
    code = "workflow_error"


class AgentExecutionError(DevForgeError):
    code = "agent_error"


class LLMError(DevForgeError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "llm_error"


class ExecutionError(DevForgeError):
    code = "execution_error"


class GitIntegrationError(DevForgeError):
    code = "git_error"


class ConfigurationError(DevForgeError):
    code = "configuration_error"


def _payload(code: str, message: str, detail: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach consistent JSON error handling to the FastAPI application."""

    @app.exception_handler(DevForgeError)
    async def _devforge_error(_: Request, exc: DevForgeError) -> JSONResponse:  # noqa: ANN202
        logger.warning("Handled application error: %s (%s)", exc.message, exc.code)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.detail),
            headers={"WWW-Authenticate": "Bearer"} if exc.code == "unauthorized" else None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: ANN202
        return JSONResponse(
            status_code=422,
            content=_payload("validation_error", "Request payload failed validation.",
                             {"fields": exc.errors()[:10]}),
        )

    @app.exception_handler(SQLAlchemyError)
    async def _db_error(_: Request, exc: SQLAlchemyError) -> JSONResponse:  # noqa: ANN202
        logger.exception("Database error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_payload("database_error", "A database error occurred. Please retry."),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:  # noqa: ANN202
        logger.exception("Unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_payload("internal_error", "An unexpected internal error occurred."),
        )
