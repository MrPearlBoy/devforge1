"""GitHub / Git integration.

Safety rules enforced here (spec §27, Rule 11):

* tokens are encrypted at rest (Fernet key derived from ``SECRET_KEY``) and are
  never returned by the API, logged, or written into ``.git/config``;
* commit, push and pull-request operations require ``confirm=True`` from the caller,
  which the API only sets from an explicit human confirmation request;
* force-push and history-rewriting operations do not exist in this service;
* everything is written to ``git_operations`` and the audit log.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.errors import GitIntegrationError, NotFoundError, ValidationFailure
from app.core.logging import get_logger
from app.models.enums import ActorType, GitOperationStatus, GitOperationType
from app.models.project import Project
from app.models.repository import GitOperation, Repository
from app.models.user import User
from app.services.audit import AuditService
from app.services.workspace import WorkspaceService
from app.tools.git_tool import GitTool

logger = get_logger("devforge.github")

GITHUB_URL_RE = r"^(https://|git@)github\.com[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(\.git)?/?$"


@dataclass
class SyncPlan:
    branch: str
    base_branch: str
    commit_message: str
    files: list[dict]
    summary: str

    def to_dict(self) -> dict:
        return {
            "branch": self.branch,
            "base_branch": self.base_branch,
            "commit_message": self.commit_message,
            "files": self.files,
            "summary": self.summary,
            "requires_confirmation": True,
        }


class GitHubService:
    """Connect, inspect and publish project workspaces to GitHub."""

    def __init__(self, db: Session, *, workspace: WorkspaceService | None = None) -> None:
        self.db = db
        self.workspace = workspace or WorkspaceService()
        self.audit = AuditService(db)

    # ---------------------------------------------------------------- repository
    def get_repository(self, project_id: str) -> Repository | None:
        return self.db.scalar(select(Repository).where(Repository.project_id == project_id))

    def _require_repository(self, project_id: str) -> Repository:
        repository = self.get_repository(project_id)
        if repository is None:
            raise NotFoundError("No repository is connected to this project yet.")
        return repository

    @staticmethod
    def parse_github_url(url: str) -> tuple[str, str]:
        import re

        match = re.match(GITHUB_URL_RE, (url or "").strip(), re.IGNORECASE)
        if not match:
            raise ValidationFailure(
                "Enter a GitHub repository URL such as https://github.com/owner/repository.git",
            )
        return match.group("owner"), match.group("name")

    def connect(
        self,
        *,
        project: Project,
        user: User,
        url: str,
        token: str = "",
        default_branch: str = "main",
        clone: bool = True,
    ) -> Repository:
        owner, name = self.parse_github_url(url)
        existing = self.get_repository(project.id)
        encrypted = existing.token_encrypted if existing else ""
        if token.strip():
            encrypted = encrypt_secret(token.strip())

        repository = existing or Repository(project_id=project.id)
        repository.url = url.strip()
        repository.owner = owner
        repository.name = name
        repository.default_branch = default_branch or "main"
        repository.local_path = str(self.workspace.ensure_project(project.id))
        repository.token_encrypted = encrypted
        repository.auth_configured = bool(encrypted)
        repository.status = "CONNECTED"
        if not repository.working_branch:
            repository.working_branch = f"devforge/{project.slug[:60] or 'work'}"
        self.db.add(repository)
        self.db.commit()
        self.db.refresh(repository)

        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.INIT, status=GitOperationStatus.SUCCEEDED,
            branch=repository.default_branch, confirmed=True,
            message=f"Connected {owner}/{name}",
            detail={"owner": owner, "name": name, "token_provided": bool(token)},
        )

        if clone:
            try:
                self.clone(project=project, user=user)
            except GitIntegrationError as exc:
                logger.warning("Clone failed, repository stays connected: %s", exc)
                repository.status = "CONNECTED_NOT_CLONED"
                self.db.commit()

        self.audit.record(
            action="github.connected",
            project_id=project.id,
            user=user,
            entity_type="repository",
            entity_id=repository.id,
            summary=f"{user.full_name or user.email} connected repository {owner}/{name}",
            detail={"url": repository.url, "auth": bool(encrypted)},
        )
        return repository

    def _token_for(self, repository: Repository) -> str:
        if repository.token_encrypted:
            try:
                return decrypt_secret(repository.token_encrypted)
            except Exception as exc:  # pragma: no cover - decryption failure
                logger.warning("Stored token could not be decrypted: %s", exc)
        return settings.github_token or ""

    def token_hint(self, repository: Repository | None) -> str:
        if repository is None:
            return ""
        token = self._token_for(repository)
        return mask_secret(token) if token else ""

    # -------------------------------------------------------------- local repo
    def _git(self, project_id: str) -> GitTool:
        path = self.workspace.project_dir(project_id)
        return GitTool(path)

    def clone(self, *, project: Project, user: User) -> dict:
        repository = self._require_repository(project.id)
        tool = self._git(project.id)
        if tool.is_repo():
            raise GitIntegrationError(
                "This project workspace is already a git repository.",
                detail={"branch": tool.current_branch()},
            )
        branch = tool.clone(repository.url, branch=repository.default_branch,
                            token=self._token_for(repository))
        repository.status = "CLONED"
        repository.last_synced_at = datetime.now(timezone.utc)
        self.db.commit()
        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.CLONE, status=GitOperationStatus.SUCCEEDED,
            branch=branch, confirmed=True, message="Repository cloned",
            detail={"branch": branch},
        )
        return {"branch": branch}

    def init_local(self, *, project: Project, user: User) -> dict:
        """Initialise a local repository for projects that are not cloned yet."""
        repository = self._require_repository(project.id)
        tool = self._git(project.id)
        branch = tool.init(repository.default_branch) if not tool.is_repo() else tool.current_branch()
        if repository.url:
            try:
                tool.set_remote(repository.url)
            except Exception as exc:  # remote may not be reachable yet
                logger.warning("Could not set remote: %s", exc)
        repository.status = "INITIALISED"
        repository.working_branch = tool.current_branch() or branch
        self.db.commit()
        return {"branch": repository.working_branch}

    def pull(self, *, project: Project, user: User, branch: str = "") -> dict:
        repository = self._require_repository(project.id)
        tool = self._git(project.id)
        if not tool.is_repo():
            raise GitIntegrationError("The project workspace is not a git repository yet.")
        try:
            summary = tool.pull(branch=branch or repository.default_branch,
                                token=self._token_for(repository))
        except GitIntegrationError as exc:
            self._record_operation(
                project_id=project.id, user=user, repository=repository,
                operation=GitOperationType.PULL, status=GitOperationStatus.FAILED,
                branch=branch or repository.default_branch, confirmed=True,
                message="Pull failed", detail={"error": exc.message},
            )
            raise
        repository.last_synced_at = datetime.now(timezone.utc)
        self.db.commit()
        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.PULL, status=GitOperationStatus.SUCCEEDED,
            branch=branch or repository.default_branch, confirmed=True,
            message="Pulled from remote", detail={"summary": summary[:500]},
        )
        return {"summary": summary}

    # ------------------------------------------------------------------- status
    def status(self, project_id: str) -> dict:
        repository = self.get_repository(project_id)
        if repository is None:
            return {
                "connected": False,
                "repository": None,
                "branch": "",
                "changes": [],
                "message": "No repository connected. Add a GitHub URL to enable delivery.",
                "requires_confirmation": True,
            }
        tool = self._git(project_id)
        last_operation = self.db.scalars(
            select(GitOperation)
            .where(GitOperation.project_id == project_id)
            .order_by(desc(GitOperation.created_at))
        ).first()

        if not tool.is_repo():
            return {
                "connected": True,
                "repository": self._repository_payload(repository),
                "branch": repository.default_branch,
                "is_clean": False,
                "changes": [],
                "staged_count": 0,
                "untracked_count": 0,
                "ahead": 0,
                "behind": 0,
                "remote_url": repository.url,
                "last_operation": self._operation_payload(last_operation),
                "requires_confirmation": True,
                "message": "Repository connected but the workspace has not been initialised or "
                           "cloned yet.",
            }

        state = tool.state()
        return {
            "connected": True,
            "repository": self._repository_payload(repository),
            "branch": state.branch,
            "is_clean": state.is_clean,
            "changes": [
                {"path": change.path, "status": change.status, "staged": change.staged}
                for change in state.changes[:200]
            ],
            "staged_count": state.staged_count,
            "untracked_count": state.untracked_count,
            "ahead": state.ahead,
            "behind": state.behind,
            "remote_url": state.remote_url or repository.url,
            "last_commit": state.last_commit,
            "last_operation": self._operation_payload(last_operation),
            "requires_confirmation": True,
            "message": "",
        }

    def commits(self, project_id: str, *, limit: int = 20) -> list[dict]:
        repository = self.get_repository(project_id)
        if repository is None:
            return []
        tool = self._git(project_id)
        if not tool.is_repo():
            return []
        return tool.log(limit=limit)

    # ------------------------------------------------------- proposal & publish
    def plan_sync(self, project_id: str, *, message: str = "") -> SyncPlan:
        """What DevForge would commit — shown to the human before anything happens."""
        repository = self._require_repository(project_id)
        tool = self._git(project_id)
        if not tool.is_repo():
            self.init_local_from_repository(repository, project_id)
            tool = self._git(project_id)
        state = tool.state()
        files = [{"path": change.path, "status": change.status, "staged": change.staged}
                 for change in state.changes[:200]]
        branch = state.branch or repository.working_branch or repository.default_branch
        combined = "\n".join(sorted({change.path for change in state.changes}))
        default_message = message or self._suggest_message(combined)
        return SyncPlan(
            branch=branch,
            base_branch=repository.default_branch,
            commit_message=default_message,
            files=files,
            summary=(
                f"{len(files)} changed file(s) on branch '{branch}': "
                f"{state.staged_count} staged, {state.untracked_count} untracked."
            ),
        )

    def init_local_from_repository(self, repository: Repository, project_id: str) -> None:
        tool = self._git(project_id)
        if not tool.is_repo():
            tool.init(repository.default_branch)
        if repository.url:
            try:
                tool.set_remote(repository.url)
            except Exception as exc:  # pragma: no cover
                logger.warning("Remote setup failed: %s", exc)

    @staticmethod
    def _suggest_message(changed_paths: str) -> str:
        areas = []
        for prefix, label in (
            ("backend/", "backend"), ("frontend/", "frontend"),
            ("tests/", "tests"), ("documentation/", "documentation"),
            ("security/", "security report"), ("requirements/", "requirements"),
            ("architecture/", "architecture"),
        ):
            if prefix in changed_paths:
                areas.append(label)
        scope = ", ".join(areas) if areas else "project files"
        return f"chore(devforge): sync approved {scope}"

    def commit(
        self,
        *,
        project: Project,
        user: User,
        message: str,
        paths: list[str] | None = None,
        confirm: bool = False,
    ) -> dict:
        if not confirm:
            raise GitIntegrationError(
                "Committing requires explicit human confirmation.",
            )
        repository = self._require_repository(project.id)
        tool = self._git(project.id)
        if not tool.is_repo():
            self.init_local_from_repository(repository, project.id)
            tool = self._git(project.id)

        # create a working branch on first commit so the default branch is never
        # written to without an explicit review
        state = tool.state()
        if state.branch in {repository.default_branch, "master", "main"} and repository.working_branch:
            if repository.working_branch not in tool.branches():
                tool.create_branch(repository.working_branch)
            else:
                tool.checkout(repository.working_branch)
            state = tool.state()

        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.BRANCH, status=GitOperationStatus.SUCCEEDED,
            branch=state.branch, confirmed=True, message=f"On branch {state.branch}",
            detail={},
        )
        staged_count = tool.stage(paths or [])
        sha = tool.commit(message)
        repository.last_commit_sha = sha
        self.db.commit()
        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.COMMIT, status=GitOperationStatus.SUCCEEDED,
            branch=state.branch, commit_sha=sha, confirmed=True, message=message[:400],
            detail={"files": staged_count},
        )
        self.audit.record(
            action="github.committed",
            project_id=project.id,
            user=user,
            entity_type="repository",
            entity_id=repository.id,
            summary=f"{user.full_name or user.email} committed {staged_count} file(s) on "
                    f"{state.branch}",
            detail={"sha": sha[:12], "message": message[:200]},
        )
        return {"sha": sha, "branch": state.branch, "files": staged_count}

    def push(
        self,
        *,
        project: Project,
        user: User,
        branch: str = "",
        confirm: bool = False,
        set_upstream: bool = True,
        create_pull_request: bool = False,
        pr_title: str = "",
        pr_body: str = "",
        base_branch: str = "",
    ) -> dict:
        if not confirm:
            raise GitIntegrationError(
                "Pushing to a remote repository requires explicit human confirmation.",
            )
        repository = self._require_repository(project.id)
        tool = self._git(project.id)
        if not tool.is_repo():
            raise GitIntegrationError("There is no local repository to push from yet.")

        target = branch or tool.current_branch() or repository.working_branch
        try:
            summary = tool.push(branch=target, token=self._token_for(repository),
                                set_upstream=set_upstream)
        except GitIntegrationError as exc:
            self._record_operation(
                project_id=project.id, user=user, repository=repository,
                operation=GitOperationType.PUSH, status=GitOperationStatus.FAILED,
                branch=target, confirmed=True, message="Push failed",
                detail={"error": exc.message[:400]},
            )
            raise
        repository.status = "PUSHED"
        repository.last_synced_at = datetime.now(timezone.utc)
        self.db.commit()
        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.PUSH, status=GitOperationStatus.SUCCEEDED,
            branch=target, commit_sha=repository.last_commit_sha, confirmed=True,
            message=f"Pushed {target}", detail={"summary": summary[:400]},
        )
        result = {"branch": target, "summary": summary}

        if create_pull_request:
            result["pull_request"] = self.create_pull_request(
                project=project, user=user, head=target,
                base=base_branch or repository.default_branch,
                title=pr_title or f"DevForge: {project.name}",
                body=pr_body or self._default_pr_body(project),
            )
        self.audit.record(
            action="github.pushed",
            project_id=project.id,
            user=user,
            entity_type="repository",
            entity_id=repository.id,
            summary=f"{user.full_name or user.email} pushed branch {target}",
            detail={"summary": summary[:300]},
        )
        return result

    def create_pull_request(self, *, project: Project, user: User, head: str, base: str,
                            title: str, body: str) -> dict:
        repository = self._require_repository(project.id)
        token = self._token_for(repository)
        if not token:
            raise GitIntegrationError(
                "Creating a pull request needs a GitHub token with repository access.",
            )
        payload = {"title": title[:200], "head": head, "base": base, "body": body[:6000]}
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    f"{settings.github_api_url}/repos/{repository.owner}/{repository.name}/pulls",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json=payload,
                )
        except httpx.RequestError as exc:
            raise GitIntegrationError("Could not reach the GitHub API.") from exc

        if response.status_code >= 400:
            detail = "GitHub rejected the pull request."
            try:
                detail = response.json().get("message", detail)
            except ValueError:
                pass
            self._record_operation(
                project_id=project.id, user=user, repository=repository,
                operation=GitOperationType.PULL_REQUEST, status=GitOperationStatus.FAILED,
                branch=head, confirmed=True, message=detail[:300],
                detail={"status": response.status_code},
            )
            raise GitIntegrationError(detail, detail={"status": response.status_code})

        data = response.json()
        self._record_operation(
            project_id=project.id, user=user, repository=repository,
            operation=GitOperationType.PULL_REQUEST, status=GitOperationStatus.SUCCEEDED,
            branch=head, confirmed=True, message=f"Opened PR #{data.get('number')}",
            detail={"url": data.get("html_url", ""), "base": base},
        )
        return {
            "number": data.get("number"),
            "url": data.get("html_url", ""),
            "state": data.get("state", "open"),
        }

    def disconnect(self, *, project: Project, user: User) -> None:
        repository = self.get_repository(project.id)
        if repository is None:
            return
        self.audit.record(
            action="github.disconnected",
            project_id=project.id,
            user=user,
            entity_type="repository",
            entity_id=repository.id,
            summary=f"{user.full_name or user.email} disconnected repository {repository.owner}/"
                    f"{repository.name}",
        )
        self.db.delete(repository)
        self.db.commit()

    def operations(self, project_id: str, *, limit: int = 50) -> list[GitOperation]:
        return list(self.db.scalars(
            select(GitOperation)
            .where(GitOperation.project_id == project_id)
            .order_by(desc(GitOperation.created_at))
            .limit(limit)
        ))

    # ------------------------------------------------------------------ helpers
    def _record_operation(self, *, project_id: str, user: User | None, repository: Repository | None,
                          operation: GitOperationType, status: GitOperationStatus,
                          branch: str = "", commit_sha: str = "", message: str = "",
                          confirmed: bool = False, detail: dict | None = None) -> GitOperation:
        record = GitOperation(
            project_id=project_id,
            repository_id=repository.id if repository else None,
            user_id=user.id if user else None,
            operation=operation.value,
            status=status.value,
            branch=branch[:120],
            commit_sha=commit_sha[:64],
            message=message[:400],
            confirmed_by_user=confirmed,
            detail=detail or {},
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def _repository_payload(self, repository: Repository) -> dict:
        return {
            "id": repository.id,
            "project_id": repository.project_id,
            "provider": repository.provider,
            "url": repository.url,
            "owner": repository.owner,
            "name": repository.name,
            "default_branch": repository.default_branch,
            "working_branch": repository.working_branch,
            "local_path": repository.local_path,
            "auth_configured": repository.auth_configured,
            "token_hint": self.token_hint(repository),
            "status": repository.status,
            "last_synced_at": repository.last_synced_at,
            "last_commit_sha": repository.last_commit_sha,
            "meta": repository.meta or {},
            "created_at": repository.created_at,
        }

    @staticmethod
    def _operation_payload(operation: GitOperation | None) -> dict | None:
        if operation is None:
            return None
        return {
            "id": operation.id,
            "operation": operation.operation,
            "status": operation.status,
            "branch": operation.branch,
            "commit_sha": operation.commit_sha,
            "message": operation.message,
            "confirmed_by_user": operation.confirmed_by_user,
            "detail": operation.detail,
            "error": operation.error,
            "created_at": operation.created_at,
        }

    @staticmethod
    def _default_pr_body(project: Project) -> str:
        return (
            f"## DevForge delivery for {project.name}\n\n"
            "This pull request contains work produced through the DevForge multi-agent workflow "
            "and approved by a human at every gate:\n\n"
            "- requirements specification\n- architecture specification\n- generated implementation\n"
            "- test plan and test results\n- security analysis\n- documentation\n\n"
            "Review the linked artifacts in the DevForge workspace before merging."
        )
