"""Shared FastAPI dependencies: database session, current user, project access."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AuthenticationError
from app.core.security import decode_access_token, get_current_user
from app.models.project import Project
from app.models.user import User
from app.services.project_service import ProjectService
from app.services.workspace import WorkspaceService

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_workspace() -> WorkspaceService:
    return WorkspaceService()


Workspace = Annotated[WorkspaceService, Depends(get_workspace)]


def get_project(project_id: str, db: DbSession, user: CurrentUser) -> Project:
    """Load a project and enforce that the caller can access it."""
    service = ProjectService(db)
    project = service.get(project_id)
    service.ensure_access(project, user)
    return project


ProjectDep = Annotated[Project, Depends(get_project)]


def get_editable_project(project_id: str, db: DbSession, user: CurrentUser) -> Project:
    """Same as :func:`get_project` but requires write permission."""
    service = ProjectService(db)
    project = service.get(project_id)
    service.ensure_access(project, user, write=True)
    return project


EditableProjectDep = Annotated[Project, Depends(get_editable_project)]


def event_stream_user(
    db: DbSession,
    token: Annotated[str | None, Query(description="JWT for SSE clients")] = None,
) -> User:
    """Authenticate an SSE subscriber.

    ``EventSource`` cannot set headers, so the token may be passed as a query
    parameter — it is validated with exactly the same rules as the header path.
    """
    if not token:
        raise AuthenticationError("A token query parameter is required for the event stream.")
    payload = decode_access_token(token)
    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise AuthenticationError("Account not found or disabled.")
    return user


StreamUser = Annotated[User, Depends(event_stream_user)]
