"""Aggregate API router — every module is mounted under ``/api``."""
from fastapi import APIRouter

from app.api.routes import (
    activity,
    agents,
    approvals,
    artifacts,
    auth,
    execution,
    health,
    projects,
    repositories,
    trace,
    workflow,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(workflow.router)
api_router.include_router(agents.router)
api_router.include_router(approvals.router)
api_router.include_router(artifacts.router)
api_router.include_router(execution.router)
api_router.include_router(repositories.router)
api_router.include_router(trace.router)
api_router.include_router(activity.router)

__all__ = ["api_router"]
