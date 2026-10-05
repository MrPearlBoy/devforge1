"""Project workspace: safe, sandboxed file storage for generated projects.

Every path is validated against the project root so a malicious or buggy agent
output can never escape the workspace (path traversal protection required by the
security specification).
"""
from __future__ import annotations

import difflib
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.errors import ExecutionError, NotFoundError, ValidationFailure

#: Directories created for every new project workspace.
WORKSPACE_LAYOUT: tuple[str, ...] = (
    "requirements",
    "architecture",
    "src",
    "tests",
    "security",
    "documentation",
    ".devforge",
)

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
    ".jsx": "javascript", ".json": "json", ".md": "markdown", ".mmd": "mermaid",
    ".yml": "yaml", ".yaml": "yaml", ".sql": "sql", ".html": "html", ".css": "css",
    ".txt": "text", ".toml": "toml", ".env": "dotenv", ".sh": "shell", ".dockerfile": "dockerfile",
    ".ini": "ini", ".cfg": "ini", ".lock": "text", ".csv": "csv", ".java": "java",
}

MAX_READ_BYTES = 400_000
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".pytest_cache"}


@dataclass
class FileInfo:
    path: str
    size: int
    language: str
    modified_at: datetime
    is_binary: bool = False


class WorkspaceService:
    """Filesystem operations for a project's generated source tree."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root else settings.workspace_path
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def project_dir(self, project_id: str) -> Path:
        if not project_id or "/" in project_id or "\\" in project_id or project_id.startswith("."):
            raise ValidationFailure("Invalid project identifier.")
        return self.root / project_id

    def ensure_project(self, project_id: str) -> Path:
        base = self.project_dir(project_id)
        # Only create the canonical layout when the workspace is brand new, so
        # agent-generated files are never clobbered.
        is_new = not base.exists()
        base.mkdir(parents=True, exist_ok=True)
        if is_new:
            for folder in WORKSPACE_LAYOUT:
                (base / folder).mkdir(parents=True, exist_ok=True)
        return base

    def resolve(self, project_id: str, relative_path: str, *, must_exist: bool = False) -> Path:
        """Resolve ``relative_path`` inside the project workspace, safely."""
        if relative_path is None:
            raise ValidationFailure("A file path is required.")
        cleaned = relative_path.strip().replace("\\", "/").lstrip("/")
        if cleaned in {".", "./"}:
            cleaned = ""  # project root
        if cleaned == ".." or cleaned.startswith("../") or "/../" in cleaned:
            raise ValidationFailure(
                "Path escapes the project workspace and was rejected.",
                detail={"path": relative_path},
            )
        base = self.project_dir(project_id).resolve()
        base.mkdir(parents=True, exist_ok=True)
        candidate = (base / cleaned).resolve()
        if base != candidate and base not in candidate.parents:
            raise ValidationFailure(
                "Path escapes the project workspace and was rejected.",
                detail={"path": relative_path},
            )
        if must_exist and not candidate.exists():
            raise NotFoundError(f"File '{cleaned}' was not found in the project workspace.")
        return candidate

    def relative(self, project_id: str, path: Path) -> str:
        return path.relative_to(self.project_dir(project_id).resolve()).as_posix()

    # ------------------------------------------------------------------- i/o
    def write_text(self, project_id: str, relative_path: str, content: str) -> FileInfo:
        target = self.resolve(project_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self.stat(project_id, relative_path)

    def read_text(self, project_id: str, relative_path: str, *, max_bytes: int = MAX_READ_BYTES) -> tuple[str, bool]:
        """Return ``(content, truncated)`` for a workspace file."""
        target = self.resolve(project_id, relative_path, must_exist=True)
        raw = target.read_bytes()
        truncated = len(raw) > max_bytes
        data = raw[:max_bytes]
        try:
            return data.decode("utf-8"), truncated
        except UnicodeDecodeError:
            raise ValidationFailure("File appears to be binary and cannot be displayed as text.")

    def delete(self, project_id: str, relative_path: str) -> None:
        target = self.resolve(project_id, relative_path, must_exist=True)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def exists(self, project_id: str, relative_path: str) -> bool:
        try:
            return self.resolve(project_id, relative_path).exists()
        except ValidationFailure:
            return False

    def stat(self, project_id: str, relative_path: str) -> FileInfo:
        target = self.resolve(project_id, relative_path, must_exist=True)
        st = target.stat()
        return FileInfo(
            path=relative_path,
            size=st.st_size,
            language=language_for(relative_path),
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            is_binary=is_probably_binary(target),
        )

    # --------------------------------------------------------------- listing
    def list_files(self, project_id: str, *, subdir: str = "", max_files: int = 2000) -> list[FileInfo]:
        base = self.resolve(project_id, subdir or ".")
        if not base.exists():
            return []
        files: list[FileInfo] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for filename in filenames:
                if filename.startswith(".DS_Store"):
                    continue
                full = Path(dirpath) / filename
                rel = full.relative_to(self.project_dir(project_id).resolve()).as_posix()
                st = full.stat()
                files.append(
                    FileInfo(
                        path=rel,
                        size=st.st_size,
                        language=language_for(rel),
                        modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                        is_binary=is_probably_binary(full),
                    )
                )
                if len(files) >= max_files:
                    return files
        return sorted(files, key=lambda f: f.path)

    def group_tree(self, project_id: str) -> dict[str, list[FileInfo]]:
        """Group workspace files by top-level folder (for the code explorer)."""
        groups: dict[str, list[FileInfo]] = {}
        for info in self.list_files(project_id):
            top = info.path.split("/", 1)[0] if "/" in info.path else "(root)"
            groups.setdefault(top, []).append(info)
        return dict(sorted(groups.items()))

    def read_tree(self, project_id: str, *, max_files: int = 40, max_bytes_per_file: int = 20_000) -> dict[str, str]:
        """Read source files for agent context ingestion."""
        out: dict[str, str] = {}
        for info in self.list_files(project_id, max_files=max_files * 3):
            if info.is_binary or info.size > 120_000:
                continue
            if not info.path.startswith(("src/", "backend/", "frontend/", "tests/",
                                         "requirements/", "architecture/", "documentation/",
                                         "security/")) and "/" in info.path:
                continue
            try:
                content, _ = self.read_text(project_id, info.path, max_bytes=max_bytes_per_file)
            except Exception:  # pragma: no cover - unreadable file, skip
                continue
            out[info.path] = content
            if len(out) >= max_files:
                break
        return out

    def write_project_metadata(self, project_id: str, metadata: dict) -> FileInfo:
        """Persist ``.devforge/project.json`` (workspace-level metadata mirror)."""
        import json

        return self.write_text(project_id, ".devforge/project.json",
                               json.dumps(metadata, indent=2, default=str))

    def write_workflow_metadata(self, project_id: str, snapshot: dict) -> FileInfo:
        import json

        return self.write_text(project_id, ".devforge/workflow.json",
                               json.dumps(snapshot, indent=2, default=str))

    def delete_project(self, project_id: str) -> None:
        shutil.rmtree(self.project_dir(project_id), ignore_errors=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def language_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if Path(path).name.lower() in {"dockerfile", "makefile"}:
        return Path(path).name.lower()
    return LANGUAGE_BY_SUFFIX.get(suffix, "text")


def is_probably_binary(path: Path, probe: int = 2048) -> bool:
    try:
        chunk = path.read_bytes()[:probe]
    except OSError:
        return False
    return b"\x00" in chunk


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def unified_diff(old: str, new: str, path: str, context: int = 3) -> str:
    """Return a unified diff (``---``/``+++`` prefixed) between two revisions."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}", n=context
    )
    text = "".join(diff)
    if not text:
        return ""
    return text if text.endswith("\n") else text + "\n"


def diff_stats(diff: str) -> tuple[int, int]:
    additions = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    return additions, deletions


def workspace_service() -> WorkspaceService:
    """Factory used by FastAPI dependencies and services."""
    return WorkspaceService()


def assert_safe_target(project_id: str, path: str) -> None:
    """Raise when ``path`` would escape the workspace (used before git staging)."""
    service = WorkspaceService()
    service.resolve(project_id, path)
    if path.startswith("..") or path.startswith("/"):
        raise ExecutionError("Unsafe path rejected by DevForge guard.")
