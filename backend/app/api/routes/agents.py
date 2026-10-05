"""Agent endpoints: catalogue, status, chat, executions."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import desc, select

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep
from app.core.config import settings
from app.core.errors import ValidationFailure
from app.models.agent import Agent, Task
from app.models.execution import AgentExecution
from app.schemas.agent import (
    AgentRead,
    AgentStatusRead,
    ChatRequest,
    ChatResponse,
    ExecutionRead,
    MessageRead,
    TaskRead,
)
from app.services.agent_registry import get_agent_spec, list_agent_specs, seed_agent_catalog
from app.services.chat_service import ChatService

router = APIRouter(tags=["agents"])


@router.get("/agents", response_model=list[AgentRead], summary="Agent catalogue")
def list_agents(db: DbSession, user: CurrentUser) -> list[AgentRead]:
    rows = db.scalars(select(Agent).order_by(Agent.order_index)).all()
    if not rows:  # first call on a fresh database
        seed_agent_catalog(db)
        rows = db.scalars(select(Agent).order_by(Agent.order_index)).all()
    return [AgentRead.model_validate(row) for row in rows]


@router.get("/agents/specs", summary="Agent specs with stage labels (UI directory)")
def agent_specs() -> list[dict]:
    return [
        {
            "key": spec.key,
            "name": spec.name,
            "role": spec.role,
            "stage": spec.stage,
            "description": spec.description,
            "icon": spec.icon,
            "order_index": spec.order_index,
            "capabilities": list(spec.capabilities),
            "output_artifact_types": [str(item) for item in spec.output_artifact_types],
        }
        for spec in list_agent_specs()
    ]


@router.get("/projects/{project_id}/agents/status", response_model=list[AgentStatusRead],
            summary="Latest execution status per agent for a project")
def agent_status(project: ProjectDep, db: DbSession) -> list[AgentStatusRead]:
    rows = db.scalars(
        select(AgentExecution)
        .where(AgentExecution.project_id == project.id)
        .order_by(desc(AgentExecution.created_at))
        .limit(200)
    ).all()
    latest: dict[str, AgentExecution] = {}
    for row in rows:
        latest.setdefault(row.agent_key, row)

    statuses: list[AgentStatusRead] = []
    for spec in list_agent_specs():
        execution = latest.get(spec.key)
        statuses.append(AgentStatusRead(
            agent_key=spec.key,
            name=spec.name,
            stage=spec.stage,
            status=execution.status if execution else "IDLE",
            execution_id=execution.id if execution else None,
            started_at=execution.started_at if execution else None,
            finished_at=execution.finished_at if execution else None,
            duration_ms=execution.duration_ms if execution else 0,
            result=execution.output_summary if execution else "",
            error=execution.error if execution else "",
            mode=execution.mode if execution else settings.resolved_ai_mode,
            model=execution.llm_model if execution else settings.llm_model,
            total_tokens=execution.total_tokens if execution else 0,
        ))
    return statuses


@router.get("/projects/{project_id}/executions", response_model=list[ExecutionRead],
            summary="Agent execution log for a project")
def executions(project: ProjectDep, db: DbSession, agent_key: str | None = None,
               limit: int = 50) -> list[ExecutionRead]:
    stmt = select(AgentExecution).where(AgentExecution.project_id == project.id)
    if agent_key:
        stmt = stmt.where(AgentExecution.agent_key == agent_key)
    stmt = stmt.order_by(desc(AgentExecution.created_at)).limit(min(limit, 200))
    return [ExecutionRead.model_validate(row) for row in db.scalars(stmt)]


@router.get("/executions/{execution_id}", response_model=ExecutionRead,
            summary="One agent execution")
def execution_detail(execution_id: str, db: DbSession, user: CurrentUser) -> ExecutionRead:
    execution = db.get(AgentExecution, execution_id)
    if execution is None:
        from app.core.errors import NotFoundError

        raise NotFoundError("Execution not found.")
    return ExecutionRead.model_validate(execution)


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
@router.post("/projects/{project_id}/chat", response_model=ChatResponse,
             summary="Talk to an agent (proposals open an approval gate)")
def chat(project: EditableProjectDep, payload: ChatRequest, db: DbSession,
         user: CurrentUser) -> ChatResponse:
    return ChatService(db).send(
        project,
        user=user,
        message=payload.message,
        agent_key=payload.agent_key,
        thread_id=payload.thread_id,
        allow_code_proposals=payload.allow_code_proposals,
    )


@router.get("/projects/{project_id}/chat", response_model=list[MessageRead],
            summary="Chat history")
def chat_history(project: ProjectDep, db: DbSession, thread_id: str = "",
                 agent_key: str = "", limit: int = 100) -> list[MessageRead]:
    rows = ChatService(db).history(project.id, thread_id=thread_id, agent_key=agent_key,
                                   limit=min(limit, 300))
    return [MessageRead.model_validate(row) for row in rows]


@router.get("/projects/{project_id}/chat/threads", summary="Conversation threads")
def chat_threads(project: ProjectDep, db: DbSession) -> list[dict]:
    return ChatService(db).threads(project.id)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead],
            summary="Agent-suggested work items")
def list_project_tasks(project: ProjectDep, db: DbSession) -> list[TaskRead]:
    rows = db.scalars(
        select(Task).where(Task.project_id == project.id).order_by(desc(Task.created_at)).limit(200)
    )
    return [TaskRead.model_validate(row) for row in rows]
