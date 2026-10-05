"""Health, configuration and real-time event endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text

from app.api.deps import DbSession, StreamUser
from app.core.config import settings
from app.core.database import engine
from app.core.events import bus
from app.models.artifact import Artifact
from app.models.project import Project
from app.models.user import User
from app.schemas.auth import AIConfigRead
from app.schemas.common import Message
from app.tools.executor.factory import executor_status
from app.tools.llm.factory import get_llm_gateway

router = APIRouter(tags=["platform"])


@router.get("/health", summary="Liveness and readiness probe")
def health(db: DbSession) -> dict:
    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover - degraded database
        database_ok = False
    gateway = get_llm_gateway()
    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "database": {"connected": database_ok, "dialect": engine.dialect.name},
        "ai": {
            "mode": settings.resolved_ai_mode,
            "provider": gateway.provider_name,
            "model": gateway.model,
        },
        "execution": executor_status(),
    }


@router.get("/config", response_model=AIConfigRead, summary="Platform configuration for the UI")
def config() -> AIConfigRead:
    execution = executor_status()
    gateway = get_llm_gateway()
    return AIConfigRead(
        mode=gateway.mode,
        provider=gateway.provider_name,
        # the effective model: in mock mode a placeholder provider model is misleading
        model=gateway.model,
        mock_mode=not settings.is_live_ai,
        execution_provider=str(execution.get("provider", settings.execution_provider)),
        execution_enabled=bool(execution.get("available", settings.execution_enabled)),
        github_configured=bool(settings.github_token),
        vector_backend=settings.vector_backend,
        max_stage_iterations=settings.max_stage_iterations,
    )


@router.get("/stats", summary="Workspace level counters for the dashboard")
def stats(db: DbSession, user: StreamUser) -> dict:
    projects = db.scalar(
        select(func.count(Project.id)).where(Project.owner_id == user.id)
    ) or 0
    artifacts = db.scalar(select(func.count(Artifact.id))) or 0
    users = db.scalar(select(func.count(User.id))) or 0
    return {
        "projects": projects,
        "artifacts": artifacts,
        "users": users,
        "ai_mode": settings.resolved_ai_mode,
    }


@router.get("/projects/{project_id}/events", summary="Server-Sent Events for agent activity")
def project_events(project_id: str, user: StreamUser) -> StreamingResponse:
    """Live agent/workflow events for one project (SSE)."""
    return StreamingResponse(
        bus.stream(project_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/projects/{project_id}/events/recent", summary="Recent events (SSE catch-up)")
def recent_events(project_id: str, user: StreamUser) -> list[dict]:
    return [
        {"type": event.type, "timestamp": event.timestamp, "payload": event.payload}
        for event in bus.recent(project_id, limit=50)
    ]


@router.post("/events/test", response_model=Message, summary="Publish a test event (debug)")
def publish_test_event(project_id: str, user: StreamUser, response: Response) -> Message:
    bus.emit("ping", project_id, message="test event", by=user.email)
    return Message(detail="Event published.")
