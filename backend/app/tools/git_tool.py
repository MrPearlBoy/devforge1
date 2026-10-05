"""Git operations wrapper (GitPython).

Safety contract:
* never force-push, never ``reset --hard``, never ``clean -fdx`` — those verbs are
  simply not implemented here;
* credentials are injected only for the duration of a remote call and never logged;
* callers (the GitHub service) require an explicit human confirmation flag before
  commit/push/PR; this tool only performs what it is told, on a validated path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.errors import GitIntegrationError
from app.core.logging import get_logger

logger = get_logger("devforge.git")


@dataclass
class GitChange:
    path: str
    status: str  # added | modified | deleted | renamed | untracked
    staged: bool = False


@dataclass
class GitState:
    is_repo: bool = False
    branch: str = ""
    changes: list[GitChange] = field(default_factory=list)
    staged_count: int = 0
    untracked_count: int = 0
    ahead: int = 0
    behind: int = 0
    remote_url: str = ""
    last_commit: dict = field(default_factory=dict)
    is_clean: bool = True


class GitTool:
    """Thin, defensive wrapper around a local repository."""

    def __init__(self, repo_path: Path | str) -> None:
        self.repo_path = Path(repo_path)

    # ------------------------------------------------------------------ setup
    def _repo(self):  # noqa: ANN202 - git.Repo
        try:
            from git import Repo
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise GitIntegrationError("GitPython is not installed on the backend.") from exc
        if not (self.repo_path / ".git").exists():
            raise GitIntegrationError(
                "No git repository has been initialised for this project yet.",
                detail={"path": str(self.repo_path)},
            )
        return Repo(self.repo_path)

    def is_repo(self) -> bool:
        return (self.repo_path / ".git").exists()

    def _configure_identity(self, repo) -> None:  # noqa: ANN001
        with repo.config_writer() as config:
            config.set_value("user", "name", settings.git_author_name)
            config.set_value("user", "email", settings.git_author_email)

    # ----------------------------------------------------------------- actions
    def init(self, default_branch: str = "main") -> str:
        from git import Repo

        self.repo_path.mkdir(parents=True, exist_ok=True)
        if self.is_repo():
            return self.current_branch()
        repo = Repo.init(self.repo_path, initial=default_branch)
        self._configure_identity(repo)
        logger.info("Initialised git repository at %s (%s)", self.repo_path, default_branch)
        return default_branch

    def current_branch(self) -> str:
        try:
            return self._repo().active_branch.name
        except Exception:
            return ""

    def set_remote(self, url: str) -> None:
        repo = self._repo()
        if "origin" in [remote.name for remote in repo.remotes]:
            repo.remotes.origin.set_url(url)
        else:
            repo.create_remote("origin", url)
        logger.info("Remote origin set (url redacted)")

    def remote_url(self) -> str:
        try:
            repo = self._repo()
            return repo.remotes.origin.url if repo.remotes else ""
        except Exception:
            return ""

    def state(self) -> GitState:
        if not self.is_repo():
            return GitState(is_repo=False)
        repo = self._repo()
        state = GitState(is_repo=True)
        try:
            state.branch = repo.active_branch.name
        except Exception:  # detached HEAD
            state.branch = "(detached)"
        state.remote_url = self.remote_url()
        tracked_changes = repo.index.diff(None)
        staged = repo.index.diff("HEAD") if self._has_commits(repo) else repo.index.diff(None)
        for diff in tracked_changes:
            state.changes.append(GitChange(path=diff.a_path or "", status="modified", staged=False))
        for diff in staged:
            state.changes.append(GitChange(path=diff.a_path or "", status="modified", staged=True))
            state.staged_count += 1
        for path in repo.untracked_files:
            state.changes.append(GitChange(path=path, status="untracked", staged=False))
            state.untracked_count += 1
        state.is_clean = not state.changes
        if self._has_commits(repo) and repo.remotes:
            try:
                branch = repo.active_branch.name
                tracking = repo.active_branch.tracking_branch()
                if tracking is not None:
                    counts = repo.git.rev_list("--left-right", "--count", f"{tracking}...{branch}")
                    behind, ahead = (int(x) for x in counts.split())
                    state.ahead, state.behind = ahead, behind
            except Exception:  # pragma: no cover - remote not fetched yet
                pass
        if self._has_commits(repo):
            commit = repo.head.commit
            state.last_commit = {
                "sha": commit.hexsha[:12],
                "message": commit.message.strip().splitlines()[0][:200],
                "author": commit.author.name,
                "date": commit.committed_datetime.isoformat(),
            }
        return state

    @staticmethod
    def _has_commits(repo) -> bool:  # noqa: ANN001
        try:
            return repo.head.is_valid()
        except Exception:
            return False

    def stage(self, paths: list[str]) -> int:
        repo = self._repo()
        targets = paths or ["-A"]
        repo.git.add(*targets)
        staged = repo.git.diff("--cached", "--name-only")
        return len([line for line in staged.splitlines() if line.strip()])

    def commit(self, message: str) -> str:
        """Create a commit.

        ``IndexFile.commit`` cannot create the *first* commit of a repository
        (HEAD is unborn), so that case is delegated to ``git commit``, which is
        equally safe (no history rewriting is ever performed).
        """
        repo = self._repo()
        if self._has_commits(repo):
            repo.index.commit(message)
        else:
            repo.git.commit("-m", message or "DevForge initial commit")
        return repo.head.commit.hexsha

    def create_branch(self, name: str, *, checkout: bool = True) -> str:
        """Create (and optionally check out) a branch.

        In a repository without commits GitPython cannot resolve the branch
        reference, so the unborn case goes through ``git checkout -b``.
        """
        repo = self._repo()
        if not self._has_commits(repo):
            if checkout:
                repo.git.checkout("-b", name)
            else:
                repo.git.symbolic_ref("HEAD", f"refs/heads/{name}")
            return name
        branch = repo.create_head(name)
        if checkout:
            branch.checkout()
        return name

    def checkout(self, name: str) -> str:
        repo = self._repo()
        repo.git.checkout(name)
        return name

    def branches(self) -> list[str]:
        try:
            return [head.name for head in self._repo().heads]
        except Exception:
            return []

    def log(self, limit: int = 20) -> list[dict]:
        if not self.is_repo():
            return []
        repo = self._repo()
        if not self._has_commits(repo):
            return []
        return [
            {
                "sha": commit.hexsha[:12],
                "message": commit.message.strip().splitlines()[0][:200],
                "author": commit.author.name,
                "date": commit.committed_datetime.isoformat(),
            }
            for commit in repo.iter_commits(max_count=limit)
        ]

    def diff_text(self, *, staged: bool = False) -> str:
        repo = self._repo()
        try:
            return repo.git.diff("--cached" if staged else None, "--stat")
        except Exception as exc:  # pragma: no cover
            logger.debug("diff failed: %s", exc)
            return ""

    # ------------------------------------------------------------------ remote
    def pull(self, *, branch: str = "", token: str = "") -> str:
        repo = self._repo()
        url = self.remote_url()
        effective = self._authenticated_url(url, token)
        try:
            if effective != url:
                repo.remotes.origin.set_url(effective)
            result = repo.remotes.origin.pull(branch or repo.active_branch.name)
            return "; ".join(str(item) for item in result)
        except Exception as exc:
            raise GitIntegrationError(
                "Pulling from the remote repository failed.",
                detail={"reason": self._redact(str(exc))},
            ) from exc
        finally:
            if effective != url:
                repo.remotes.origin.set_url(url)

    def push(self, *, branch: str = "", token: str = "", set_upstream: bool = True) -> str:
        repo = self._repo()
        target_branch = branch or repo.active_branch.name
        url = self.remote_url()
        effective = self._authenticated_url(url, token)
        try:
            if effective != url:
                repo.remotes.origin.set_url(effective)
            info = repo.remotes.origin.push(
                refspec=f"{target_branch}:{target_branch}",
                set_upstream=set_upstream,
            )
            summaries = []
            for item in info:
                if item.flags & item.ERROR:
                    raise GitIntegrationError(
                        "The remote rejected the push.",
                        detail={"summary": self._redact(str(item.summary))[:300]},
                    )
                summaries.append(item.summary.strip())
            logger.info("Pushed branch %s", target_branch)
            return "; ".join(summaries) or "push completed"
        except GitIntegrationError:
            raise
        except Exception as exc:
            raise GitIntegrationError(
                "Pushing to the remote repository failed.",
                detail={"reason": self._redact(str(exc))[:300]},
            ) from exc
        finally:
            if effective != url:
                repo.remotes.origin.set_url(url)

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _authenticated_url(url: str, token: str) -> str:
        if not token or not url.startswith("https://"):
            return url
        if "@" in url.split("//", 1)[-1]:
            return url
        return url.replace("https://", f"https://x-access-token:{token}@", 1)

    def _redact(self, text: str) -> str:
        """Strip credentials from any message before it is stored or shown."""
        import re

        text = re.sub(r"https://[^@\s]+@", "https://***@", text)
        if settings.github_token:
            text = text.replace(settings.github_token, "***")
        return text

    def clone(self, url: str, *, branch: str = "", token: str = "") -> str:
        from git import Repo

        effective = self._authenticated_url(url, token)
        if self.repo_path.exists() and any(self.repo_path.iterdir()):
            raise GitIntegrationError("The project workspace is not empty; clone aborted.")
        self.repo_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            repo = Repo.clone_from(effective, self.repo_path, branch=branch or None)
        except Exception as exc:
            raise GitIntegrationError(
                "Cloning the repository failed.",
                detail={"reason": self._redact(str(exc))[:300]},
            ) from exc
        self._configure_identity(repo)
        if "origin" in [remote.name for remote in repo.remotes]:
            repo.remotes.origin.set_url(url)  # never persist the token in .git/config
        logger.info("Cloned repository into %s", self.repo_path)
        return repo.active_branch.name
