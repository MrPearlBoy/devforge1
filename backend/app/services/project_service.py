"""Project service: creation, access control, progress and dashboard assembly."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.events import bus
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.logging import get_logger
from app.models.agent import Task
from app.models.approval import Approval
from app.models.artifact import Artifact
from app.models.execution import AgentExecution
from app.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    FindingStatus,
    ProjectRole,
    Role,
    Stage,
    StageStatus,
    STAGE_ORDER,
    WorkflowStatus,
)
from app.models.project import Project
from app.models.repository import Repository
from app.models.security import SecurityFinding
from app.models.testing import TestRun
from app.models.user import ProjectMember, User
from app.models.workflow import WorkflowRun
from app.services.audit import AuditService
from app.services.workspace import WorkspaceService
from app.workflows.state import STAGE_LABELS

logger = get_logger("devforge.projects")

PROGRESS_BY_STAGE = {
    Stage.REQUIREMENTS.value: 10,
    Stage.ARCHITECTURE.value: 25,
    Stage.DEVELOPMENT.value: 45,
    Stage.TESTING.value: 60,
    Stage.SECURITY.value: 75,
    Stage.DOCUMENTATION.value: 90,
    Stage.DELIVERY.value: 100,
}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return slug[:180] or "project"


class ProjectService:
    def __init__(self, db: Session, *, workspace: WorkspaceService | None = None) -> None:
        self.db = db
        self.workspace = workspace or WorkspaceService()
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ create
    def create(
        self,
        *,
        name: str,
        description: str = "",
        requirement_input: str = "",
        tech_stack: str = "",
        tags: list[str] | None = None,
        owner: User,
    ) -> Project:
        base_slug = slugify(name)
        slug = base_slug
        suffix = 2
        while self.db.scalar(select(Project.id).where(Project.slug == slug)):
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        project = Project(
            name=name.strip(),
            description=description.strip(),
            slug=slug,
            requirement_input=requirement_input.strip(),
            tech_stack=tech_stack.strip(),
            tags=tags or [],
            owner_id=owner.id,
            current_stage=Stage.REQUIREMENTS.value,
            workflow_status=WorkflowStatus.NOT_STARTED.value,
            stage_status=StageStatus.PENDING.value,
            progress_percent=0,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        self.db.add(ProjectMember(project_id=project.id, user_id=owner.id,
                                  project_role=ProjectRole.OWNER.value))
        self.db.commit()

        self.workspace.ensure_project(project.id)
        project.workspace_path = str(self.workspace.project_dir(project.id))
        self.db.commit()
        self.db.refresh(project)

        self.workspace.write_project_metadata(project.id, {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "owner": owner.email,
            "created_at": project.created_at.isoformat(),
            "requirement_input": project.requirement_input,
        })
        self.audit.record(
            action="project.created",
            project_id=project.id,
            user=owner,
            entity_type="project",
            entity_id=project.id,
            summary=f"{owner.full_name or owner.email} created project '{project.name}'",
        )
        logger.info("Created project %s (%s)", project.id, project.slug)
        return project

    # -------------------------------------------------------------------- read
    def get(self, project_id: str) -> Project:
        project = self.db.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found.")
        return project

    def ensure_access(self, project: Project, user: User, *, write: bool = False) -> None:
        """Membership/role check used by every project scoped endpoint."""
        if user.role == Role.ADMIN.value:
            return
        membership = self.db.scalar(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id, ProjectMember.user_id == user.id
            )
        )
        if membership is None:
            raise PermissionDeniedError("You do not have access to this project.")
        if write and membership.project_role == ProjectRole.VIEWER.value:
            raise PermissionDeniedError("Your project role is read-only.")

    def list_for_user(self, user: User, *, include_archived: bool = False,
                      limit: int = 100) -> list[Project]:
        stmt = (
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .order_by(desc(Project.updated_at))
            .limit(limit)
        )
        projects = list(self.db.scalars(stmt))
        if not include_archived:
            projects = [project for project in projects if not project.is_archived]
        if user.role == Role.ADMIN.value:
            extra = list(self.db.scalars(
                select(Project).order_by(desc(Project.updated_at)).limit(limit)
            ))
            seen = {project.id for project in projects}
            projects += [project for project in extra if project.id not in seen]
        return projects

    # ------------------------------------------------------------------ update
    def update(self, project: Project, *, user: User, **fields) -> Project:
        allowed = {"name", "description", "requirement_input", "tech_stack", "tags", "is_archived"}
        for key, value in fields.items():
            if key in allowed and value is not None:
                setattr(project, key, value)
        self.db.commit()
        self.db.refresh(project)
        self.workspace.write_project_metadata(project.id, {
            "id": project.id,
            "name": project.name,
            "slug": project.slug,
            "description": project.description,
            "updated_at": project.updated_at.isoformat(),
        })
        self.audit.record(
            action="project.updated",
            project_id=project.id,
            user=user,
            entity_type="project",
            entity_id=project.id,
            summary=f"{user.full_name or user.email} updated project details",
            detail={key: str(value)[:200] for key, value in fields.items() if value is not None},
        )
        return project

    def delete(self, project: Project, *, user: User, remove_workspace: bool = False) -> None:
        self.audit.record(
            action="project.deleted",
            project_id=None,
            user=user,
            entity_type="project",
            entity_id=project.id,
            summary=f"{user.full_name or user.email} deleted project '{project.name}'",
            publish=False,
        )
        if remove_workspace:
            self.workspace.delete_project(project.id)
        self.db.delete(project)
        self.db.commit()

    # -------------------------------------------------------------- workflow glue
    def mark_stage(
        self,
        project_id: str,
        *,
        stage: str,
        status: str,
        progress: int | None = None,
        run_id: str | None = None,
    ) -> Project:
        project = self.get(project_id)
        project.current_stage = stage
        project.stage_status = status
        project.workflow_status = (
            WorkflowStatus.AWAITING_APPROVAL.value
            if status == StageStatus.AWAITING_APPROVAL.value
            else WorkflowStatus.RUNNING.value
        )
        if progress is not None:
            project.progress_percent = min(100, max(project.progress_percent, progress))
        elif status == StageStatus.COMPLETED.value:
            project.progress_percent = min(100, PROGRESS_BY_STAGE.get(stage, 0))
        self.db.commit()
        self.db.refresh(project)
        bus.emit(
            "workflow_updated",
            project.id,
            run_id=run_id,
            stage=stage,
            status=status,
            progress=project.progress_percent,
            message=f"{STAGE_LABELS.get(stage, stage)}: {status.replace('_', ' ').lower()}",
        )
        return project

    def mark_awaiting_approval(self, project_id: str, *, stage: str, approval_id: str) -> Project:
        project = self.get(project_id)
        run = self.db.scalars(
            select(WorkflowRun).where(WorkflowRun.project_id == project_id)
            .order_by(desc(WorkflowRun.created_at))
        ).first()
        if run is not None:
            run.awaiting_approval = True
            run.pending_approval_id = approval_id
            run.current_stage = stage
            run.status = WorkflowStatus.AWAITING_APPROVAL.value
            self.db.commit()
        return self.mark_stage(project_id, stage=stage,
                               status=StageStatus.AWAITING_APPROVAL.value,
                               run_id=run.id if run else None)

    def recompute_progress(self, project_id: str) -> int:
        completed = self.db.scalar(
            select(func.count(Artifact.id)).where(
                Artifact.project_id == project_id,
                Artifact.status == ArtifactStatus.APPROVED.value,
            )
        ) or 0
        project = self.get(project_id)
        computed = min(100, int(completed * 12))
        project.progress_percent = max(project.progress_percent, computed)
        self.db.commit()
        return project.progress_percent

    # ----------------------------------------------------------------- dashboard
    @staticmethod
    def _audit_payload(row) -> dict:  # noqa: ANN001 - AuditLog
        """Serialise an audit row for the dashboard payload."""
        from app.api.routes.activity import ACTION_LABELS

        return {
            "id": row.id,
            "action": row.action,
            "label": ACTION_LABELS.get(row.action, row.action.replace(".", " ")),
            "actor_type": row.actor_type,
            "actor_label": row.actor_label,
            "stage": row.stage,
            "summary": row.summary,
            "detail": row.detail or {},
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "created_at": row.created_at,
        }

    def build_dashboard(self, project: Project) -> dict:
        from app.services.approval_service import ApprovalService
        from app.services.github_service import GitHubService
        from app.services.project_context import ProjectContextService

        context_service = ProjectContextService(self.db, workspace=self.workspace)
        approvals = ApprovalService(self.db)

        artifacts = list(self.db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project.id)
            .order_by(desc(Artifact.updated_at))
            .limit(60)
        ))
        latest_by_stage: dict[str, Artifact] = {}
        for artifact in artifacts:
            latest_by_stage.setdefault(artifact.stage, artifact)

        pending = approvals.pending(project.id)
        pending_payload = self._approval_payload(pending[0]) if pending else None

        run = self.db.scalars(
            select(WorkflowRun).where(WorkflowRun.project_id == project.id)
            .order_by(desc(WorkflowRun.created_at))
        ).first()

        test_run = self.db.scalars(
            select(TestRun).where(TestRun.project_id == project.id)
            .order_by(desc(TestRun.created_at))
        ).first()

        security = context_service.get_security_summary(project.id)

        # The workflow run is the authority on stage progression (it knows about rework
        # rounds), so its records win; the artifact status is the fallback for projects
        # that have artifacts but no run (e.g. a single manual agent execution).
        run_records = ((run.state_snapshot or {}).get("stage_records") or {}) if run else {}
        artifact_stage_status = {
            ArtifactStatus.DRAFT.value: StageStatus.RUNNING.value,
            ArtifactStatus.IN_REVIEW.value: StageStatus.AWAITING_APPROVAL.value,
            ArtifactStatus.APPROVED.value: StageStatus.COMPLETED.value,
            ArtifactStatus.REJECTED.value: StageStatus.FAILED.value,
            ArtifactStatus.SUPERSEDED.value: StageStatus.COMPLETED.value,
        }

        stages = []
        stage_status_map = {stage: StageStatus.PENDING.value for stage in STAGE_LABELS}
        for stage in STAGE_ORDER:
            artifact = latest_by_stage.get(stage.value)
            approval = next((item for item in pending if item.stage == stage.value), None)
            run_status = (run_records.get(stage.value) or {}).get("status", "")
            status = (
                run_status
                or (artifact_stage_status.get(artifact.status, "") if artifact else "")
                or StageStatus.PENDING.value
            )
            if approval is not None:
                status = StageStatus.AWAITING_APPROVAL.value
            if (project.current_stage == stage.value
                    and project.stage_status == StageStatus.RUNNING.value
                    and not run_status):
                status = StageStatus.RUNNING.value
            stage_status_map[stage.value] = status
            stages.append({
                "stage": stage.value,
                "label": STAGE_LABELS[stage.value],
                "status": status,
                "order": STAGE_ORDER.index(stage) + 1,
                "artifact_id": artifact.id if artifact else None,
                "artifact_title": artifact.title if artifact else "",
                "approval_id": approval.id if approval else None,
                "approval_status": approval.status if approval else None,
            })

        executions = list(self.db.scalars(
            select(AgentExecution)
            .where(AgentExecution.project_id == project.id)
            .order_by(desc(AgentExecution.created_at))
            .limit(40)
        ))

        from app.services.agent_registry import AGENT_SPECS

        activity = []
        for spec in sorted(AGENT_SPECS, key=lambda item: item.order_index):
            latest = next((item for item in executions if item.agent_key == spec.key), None)
            activity.append({
                "agent_key": spec.key,
                "name": spec.name,
                "stage": spec.stage,
                "status": latest.status if latest else "IDLE",
                "execution_id": latest.id if latest else None,
                "started_at": latest.started_at if latest else None,
                "finished_at": latest.finished_at if latest else None,
                "duration_ms": latest.duration_ms if latest else 0,
                "result": latest.output_summary if latest else "",
                "error": latest.error if latest else "",
                "mode": latest.mode if latest else "",
                "model": latest.llm_model if latest else "",
                "total_tokens": latest.total_tokens if latest else 0,
            })

        try:
            repository = GitHubService(self.db).status(project.id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Repository status unavailable: %s", exc)
            repository = {"connected": False}

        from app.core.config import settings

        return {
            "project": project,
            "stages": stages,
            "active_run": self._run_payload(run) if run else None,
            "pending_approval": pending_payload,
            "approvals": [self._approval_payload(item) for item in approvals.list_for_project(project.id, limit=10)],
            "agent_activity": activity,
            "recent_activity": [
                self._audit_payload(row)
                for row in self.audit.list_for_project(project.id, limit=25)
            ],
            "artifacts": [
                {
                    "id": artifact.id,
                    "type": artifact.type,
                    "stage": artifact.stage,
                    "title": artifact.title,
                    "summary": artifact.summary,
                    "path": artifact.path,
                    "status": artifact.status,
                    "version": artifact.version,
                    "updated_at": artifact.updated_at,
                }
                for artifact in artifacts[:25]
            ],
            "latest_test_run": self._test_payload(test_run) if test_run else None,
            "security_summary": security,
            "repository": repository,
            "ai_config": {
                "mode": settings.resolved_ai_mode,
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "execution_provider": settings.execution_provider,
                "execution_enabled": settings.execution_enabled,
                "github_configured": bool(settings.github_token),
                "vector_backend": settings.vector_backend,
                "max_stage_iterations": settings.max_stage_iterations,
            },
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status,
                    "priority": task.priority,
                    "stage": task.stage,
                    "assigned_agent_key": task.assigned_agent_key,
                }
                for task in self.db.scalars(
                    select(Task).where(Task.project_id == project.id).order_by(desc(Task.created_at)).limit(20)
                )
            ],
            "open_findings": security.get("open_total", 0),
        }

    # ------------------------------------------------------------------ helpers
    def _approval_payload(self, approval: Approval) -> dict:
        artifact = self.db.get(Artifact, approval.artifact_id) if approval.artifact_id else None
        decider = self.db.get(User, approval.decided_by_user_id) if approval.decided_by_user_id else None
        return {
            "id": approval.id,
            "project_id": approval.project_id,
            "run_id": approval.run_id,
            "artifact_id": approval.artifact_id,
            "stage": approval.stage,
            "stage_label": STAGE_LABELS.get(approval.stage, approval.stage),
            "gate": approval.gate,
            "status": approval.status,
            "requested_by_agent_key": approval.requested_by_agent_key,
            "requested_at": approval.requested_at,
            "decided_at": approval.decided_at,
            "decided_by_user_id": approval.decided_by_user_id,
            "decided_by_name": (decider.full_name or decider.email) if decider else "",
            "comments": approval.comments,
            "decision_meta": approval.decision_meta or {},
            "artifact_title": artifact.title if artifact else "",
            "artifact_type": artifact.type if artifact else "",
            "artifact_preview": (artifact.content or "")[:4000] if artifact else "",
            "artifact_path": artifact.path if artifact else "",
            "created_at": approval.created_at,
        }

    @staticmethod
    def _run_payload(run: WorkflowRun) -> dict:
        return {
            "id": run.id,
            "project_id": run.project_id,
            "run_number": run.run_number,
            "status": run.status,
            "engine": run.engine,
            "thread_id": run.thread_id,
            "current_stage": run.current_stage,
            "current_node": run.current_node,
            "awaiting_approval": run.awaiting_approval,
            "pending_approval_id": run.pending_approval_id,
            "stage_iterations": run.stage_iterations or {},
            "total_steps": run.total_steps,
            "max_stage_iterations": run.max_stage_iterations,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "last_error": run.last_error,
            "created_at": run.created_at,
        }

    @staticmethod
    def _test_payload(test_run: TestRun) -> dict:
        return {
            "id": test_run.id,
            "status": test_run.status,
            "total": test_run.total,
            "passed": test_run.passed,
            "failed": test_run.failed,
            "skipped": test_run.skipped,
            "errors": test_run.errors,
            "duration_ms": test_run.duration_ms,
            "command": test_run.command,
            "provider": test_run.provider,
            "created_at": test_run.created_at,
            "report": test_run.report or {},
        }


def project_service(db: Session) -> ProjectService:
    return ProjectService(db)
