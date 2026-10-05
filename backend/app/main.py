"""FastAPI application factory for DevForge.

``create_app()`` is the only place where the platform is assembled: configuration,
logging, CORS, exception handling, the API router and startup tasks (schema
bootstrap in development, agent catalogue seeding).  Keeping it factory-based makes
the app importable in tests with an isolated database.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.database import check_database, init_db
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.services.agent_registry import seed_agent_catalog
from app.tools.llm.factory import get_llm_gateway

logger = get_logger("devforge.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    gateway = get_llm_gateway()
    logger.info(
        "DevForge starting — env=%s, ai_mode=%s, provider=%s, model=%s, database=%s",
        settings.environment, gateway.mode, gateway.provider_name, gateway.model,
        check_database().get("dialect", "unknown"),
    )
    if settings.auto_create_schema:
        init_db()
        logger.info("Database schema ensured (AUTO_CREATE_SCHEMA=true)")
    try:
        from app.core.database import session_scope

        with session_scope() as db:
            created = seed_agent_catalog(db)
            if created:
                logger.info("Seeded %s agent definitions", created)
    except Exception as exc:  # pragma: no cover - startup must not crash the API
        logger.warning("Agent catalogue seeding skipped: %s", exc)
    yield
    logger.info("DevForge shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description=(
            "AI-assisted software engineering platform: six specialist agents orchestrated "
            "by a human-approved LangGraph workflow, with traceability from requirement to "
            "documentation and a sandboxed execution environment."
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-process-time-ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
        if settings.debug:
            logger.debug("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "api": "/api",
            "docs": "/docs" if not settings.is_production else None,
            "health": "/api/health",
        }

    @app.get("/health", include_in_schema=False)
    def root_health() -> JSONResponse:
        status = check_database()
        return JSONResponse({"status": "ok" if status.get("connected") else "degraded",
                             **status})

    return app


app = create_app()
