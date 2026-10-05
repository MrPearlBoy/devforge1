"""Project endpoints: CRUD, dashboard, tasks."""
from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import desc, func, select

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep
from app.core.errors import NotFoundError
from app.models.agent import Task
from app.models.approval import Approval
from app.models.enums import ApprovalStatus, FindingStatus, TestStatus
from app.models.project import Project
from app.models.repository import Repository
from app.models.security import SecurityFinding
from app.models.testing import TestRun
from app.models.workflow import WorkflowRun
from app.schemas.agent import TaskCreate, TaskRead, TaskUpdate
from app.schemas.common import Message
from app.schemas.project import (
    ProjectCreate,
    ProjectDashboard,
    ProjectRead,
    ProjectSummary,
    ProjectUpdate,
)
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def _summary(db, project: Project, user) -> ProjectSummary:  # noqa: ANN001
    owner = db.get(type(user), project.owner_id)
    pending = db.scalar(
        select(func.count(Approval.id)).where(
            Approval.project_id == project.id, Approval.status == ApprovalStatus.PENDING.value
        )
    ) or 0
    findings = db.scalar(
        select(func.count(SecurityFinding.id)).where(
            SecurityFinding.project_id == project.id,
            SecurityFinding.status == FindingStatus.OPEN.value,
        )
    ) or 0
    test_run = db.scalars(
        select(TestRun).where(TestRun.project_id == project.id).order_by(desc(TestRun.created_at))
    ).first()
    run = db.scalars(
        select(WorkflowRun).where(WorkflowRun.project_id == project.id)
        .order_by(desc(WorkflowRun.created_at))
    ).first()
    repository = db.scalar(select(Repository).where(Repository.project_id == project.id))
    payload = ProjectRead.model_validate(project).model_dump()
    return ProjectSummary(
        **payload,
        owner_name=(owner.full_name or owner.email) if owner else "",
        active_run_id=run.id if run and run.status in {"RUNNING", "AWAITING_APPROVAL"} else None,
        pending_approvals=pending,
        open_findings=findings,
        last_test_status=test_run.status if test_run else None,
        github_connected=repository is not None,
    )


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED,
             summary="Create a project")
def create_project(payload: ProjectCreate, db: DbSession, user: CurrentUser) -> ProjectRead:
    project = ProjectService(db).create(
        name=payload.name,
        description=payload.description,
        requirement_input=payload.requirement_input,
        tech_stack=payload.tech_stack,
        tags=payload.tags,
        owner=user,
    )
    return ProjectRead.model_validate(project)


@router.get("", response_model=list[ProjectSummary], summary="List accessible projects")
def list_projects(db: DbSession, user: CurrentUser, include_archived: bool = False) -> list[ProjectSummary]:
    projects = ProjectService(db).list_for_user(user, include_archived=include_archived)
    return [_summary(db, project, user) for project in projects]


@router.get("/{project_id}", response_model=ProjectRead, summary="Project details")
def get_project(project: ProjectDep) -> ProjectRead:
    return ProjectRead.model_validate(project)


@router.put("/{project_id}", response_model=ProjectRead, summary="Update a project")
def update_project(project: EditableProjectDep, payload: ProjectUpdate, db: DbSession,
                   user: CurrentUser) -> ProjectRead:
    updated = ProjectService(db).update(project, user=user, **payload.model_dump(exclude_unset=True))
    return ProjectRead.model_validate(updated)


@router.delete("/{project_id}", response_model=Message, summary="Delete a project")
def delete_project(project: EditableProjectDep, db: DbSession, user: CurrentUser,
                   remove_workspace: bool = False) -> Message:
    if project.owner_id != user.id and user.role != "ADMIN":
        from app.core.errors import PermissionDeniedError

        raise PermissionDeniedError("Only the project owner can delete this project.")
    ProjectService(db).delete(project, user=user, remove_workspace=remove_workspace)
    return Message(detail="Project deleted.")


@router.get("/{project_id}/dashboard", response_model=ProjectDashboard,
            summary="Everything the project dashboard needs")
def dashboard(project: ProjectDep, db: DbSession) -> ProjectDashboard:
    data = ProjectService(db).build_dashboard(project)
    return ProjectDashboard(**data)


# --------------------------------------------------------------------------- #
# tasks
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/tasks", response_model=list[TaskRead], summary="Project task board")
def list_tasks(project: ProjectDep, db: DbSession, task_status: str | None = None) -> list[TaskRead]:
    stmt = select(Task).where(Task.project_id == project.id)
    if task_status:
        stmt = stmt.where(Task.status == task_status)
    stmt = stmt.order_by(desc(Task.created_at)).limit(200)
    return [TaskRead.model_validate(item) for item in db.scalars(stmt)]


@router.post("/{project_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED,
             summary="Create a task")
def create_task(project: EditableProjectDep, payload: TaskCreate, db: DbSession,
                user: CurrentUser) -> TaskRead:
    task = Task(
        project_id=project.id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        stage=payload.stage,
        assigned_agent_key=payload.assigned_agent_key,
        source="HUMAN",
        created_by_user_id=user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)


@router.patch("/{project_id}/tasks/{task_id}", response_model=TaskRead, summary="Update a task")
def update_task(project: EditableProjectDep, task_id: str, payload: TaskUpdate, db: DbSession,
                user: CurrentUser) -> TaskRead:
    task = db.get(Task, task_id)
    if task is None or task.project_id != project.id:
        raise NotFoundError("Task not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return TaskRead.model_validate(task)
