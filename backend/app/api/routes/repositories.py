"""GitHub integration endpoints.

Read operations (status, commits, plan) are free. Everything that writes to the remote
(commit, push, pull request) requires ``confirm=true`` in the request body — the UI only
sets it after the human clicks through an explicit confirmation dialog — and is recorded
in ``git_operations`` plus the audit log.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep
from app.core.errors import ValidationFailure
from app.schemas.common import Message
from app.schemas.repository import (
    GitCommitRequest,
    GitOperationRead,
    GitPushRequest,
    GitStatusRead,
    GitSyncPlan,
    RepositoryConnectRequest,
    RepositoryRead,
)
from app.services.github_service import GitHubService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects/{project_id}/repository", tags=["github"])


@router.get("", response_model=GitStatusRead, summary="Repository status and working tree")
def repository_status(project: ProjectDep, db: DbSession) -> GitStatusRead:
    return GitStatusRead(**GitHubService(db).status(project.id))


@router.post("", response_model=RepositoryRead, summary="Connect a GitHub repository")
def connect_repository(project: EditableProjectDep, payload: RepositoryConnectRequest, db: DbSession,
                       user: CurrentUser) -> RepositoryRead:
    repository = GitHubService(db).connect(
        project=project,
        user=user,
        url=payload.url,
        token=payload.token,
        default_branch=payload.default_branch,
        clone=payload.clone,
    )
    return RepositoryRead.model_validate(repository)


@router.delete("", response_model=Message, summary="Disconnect the repository")
def disconnect_repository(project: EditableProjectDep, db: DbSession, user: CurrentUser) -> Message:
    GitHubService(db).disconnect(project=project, user=user)
    return Message(detail="Repository disconnected. The generated workspace was kept.")


@router.post("/init", summary="Initialise a local git repository (no remote writes)")
def init_repository(project: EditableProjectDep, db: DbSession, user: CurrentUser) -> dict:
    return GitHubService(db).init_local(project=project, user=user)


@router.post("/clone", summary="Clone the connected repository into the workspace")
def clone_repository(project: EditableProjectDep, db: DbSession, user: CurrentUser) -> dict:
    return GitHubService(db).clone(project=project, user=user)


@router.post("/pull", summary="Pull the default branch (fast-forward, never destructive)")
def pull_repository(project: EditableProjectDep, db: DbSession, user: CurrentUser,
                    branch: str = "") -> dict:
    return GitHubService(db).pull(project=project, user=user, branch=branch)


@router.get("/commits", summary="Recent commits")
def list_commits(project: ProjectDep, db: DbSession, limit: int = 20) -> list[dict]:
    return GitHubService(db).commits(project.id, limit=min(limit, 100))


@router.get("/operations", response_model=list[GitOperationRead],
            summary="Git operation log (every remote write is a human-confirmed row)")
def list_operations(project: ProjectDep, db: DbSession, limit: int = 50) -> list[GitOperationRead]:
    rows = GitHubService(db).operations(project.id, limit=min(limit, 200))
    return [GitOperationRead.model_validate(row) for row in rows]


@router.get("/plan", response_model=GitSyncPlan, summary="What would be committed (nothing runs)")
def sync_plan(project: ProjectDep, db: DbSession, message: str = "") -> GitSyncPlan:
    plan = GitHubService(db).plan_sync(project.id, message=message)
    payload = plan.to_dict()
    return GitSyncPlan(
        branch=payload["branch"],
        base_branch=payload["base_branch"],
        commit_message=payload["commit_message"],
        files=payload["files"],
        summary=payload["summary"],
        requires_confirmation=True,
    )


@router.post("/commit", summary="Commit the workspace (requires confirmation)")
def commit(project: EditableProjectDep, payload: GitCommitRequest, db: DbSession,
           user: CurrentUser) -> dict:
    if not payload.confirm:
        raise ValidationFailure("Set confirm=true to commit the workspace.")
    result = GitHubService(db).commit(
        project=project, user=user, message=payload.message, paths=payload.paths, confirm=True
    )
    ArtifactRefresh = None  # noqa: F841 - placeholder kept out of the response path
    return {"ok": True, **result}


@router.post("/push", summary="Push to GitHub (requires confirmation)")
def push(project: EditableProjectDep, payload: GitPushRequest, db: DbSession,
         user: CurrentUser) -> dict:
    if not payload.confirm:
        raise ValidationFailure("Set confirm=true to push to the remote repository.")
    return GitHubService(db).push(
        project=project,
        user=user,
        branch=payload.branch,
        confirm=True,
        set_upstream=payload.set_upstream,
        create_pull_request=payload.create_pull_request,
        pr_title=payload.pr_title,
        pr_body=payload.pr_body,
        base_branch=payload.base_branch,
    )


@router.get("/delivery", summary="Delivery readiness: what is still missing before pushing")
def delivery_readiness(project: ProjectDep, db: DbSession) -> dict:
    """A human-friendly checklist shown on the Delivery tab."""
    dashboard = ProjectService(db).build_dashboard(project)
    service = GitHubService(db)
    status = service.status(project.id)
    stages = {stage["stage"]: stage["status"] for stage in dashboard["stages"]}
    approved = [stage for stage, value in stages.items() if value == "COMPLETED"]
    pending = dashboard.get("pending_approval") or {}
    test_run = dashboard.get("latest_test_run") or {}
    security = dashboard.get("security_summary") or {}

    checklist = [
        {
            "item": "Requirement and architecture approved",
            "done": stages.get("REQUIREMENTS") == "COMPLETED" and stages.get("ARCHITECTURE") == "COMPLETED",
        },
        {"item": "Implementation and tests generated",
         "done": stages.get("DEVELOPMENT") == "COMPLETED"},
        {"item": "Test suite green",
         "done": str(test_run.get("status", "")).upper() == "PASSED",
         "detail": f"{test_run.get('passed', 0)}/{test_run.get('total', 0)} passed"
                   if test_run else "no test run recorded"},
        {"item": "Security review completed",
         "done": bool(security) and int(security.get("open_total", 0) or 0) >= 0
                 and stages.get("SECURITY") == "COMPLETED",
         "detail": f"{security.get('open_total', 0)} open finding(s)" if security else "not scanned"},
        {"item": "Documentation generated", "done": stages.get("DOCUMENTATION") == "COMPLETED"},
        {"item": "Repository connected", "done": bool(status.get("connected"))},
        {"item": "No approval waiting on a human", "done": not pending},
    ]
    ready = all(item["done"] for item in checklist)
    return {
        "ready": ready,
        "checklist": checklist,
        "completed_stages": approved,
        "repository": status.get("repository"),
        "branch": status.get("branch", ""),
        "changed_files": len(status.get("changes", []) or []),
        "pending_approval": pending or None,
        "requires_confirmation": True,
        "message": (
            "Everything is approved — you can commit and push from the Delivery tab."
            if ready else
            "Some items still need attention before delivery."
        ),
    }
