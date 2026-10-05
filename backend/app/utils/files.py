"""Safe workspace filesystem helpers.

Every generated file lives under ``workspaces/{project_id}/``. All path
handling goes through :func:`safe_write` / :func:`read_file_safe`, which
reject absolute paths and any ``..`` traversal that would escape the
project workspace.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.core.config import get_settings

_EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
}
_HIDDEN_DIR_ALLOWLIST = {".github"}


def workspace_root(project_id: str) -> Path:
    return get_settings().workspaces_path / project_id


def _safe_path(workspace: Path, rel: str) -> Path:
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel:
        raise ValueError("empty file path")
    if rel.startswith("..") or "/../" in rel:
        raise ValueError(f"unsafe file path: {rel!r}")
    p = workspace / rel
    root = workspace.resolve()
    rp = p.resolve()
    if rp != root and root not in rp.parents:
        raise ValueError(f"file path escapes the workspace: {rel!r}")
    return p


def safe_write(workspace: Path, rel: str, content: str) -> Path:
    """Write ``content`` to ``workspace/rel`` after traversal checks."""
    p = _safe_path(workspace, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def read_file_safe(workspace: Path, rel: str) -> str:
    p = _safe_path(workspace, rel)
    if not p.is_file():
        raise ValueError(f"file not found: {rel}")
    if p.stat().st_size > 1_000_000:
        raise ValueError("file too large to display (>1 MB)")
    return p.read_text(encoding="utf-8", errors="replace")


def file_tree(workspace: Path) -> list[dict[str, Any]]:
    """List workspace files (skipping VCS/cache dirs) as sorted entries."""
    out: list[dict[str, Any]] = []
    if not workspace.exists():
        return out
    for root, dirs, files in os.walk(workspace):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in _EXCLUDED_DIRS and not (d.startswith(".") and d not in _HIDDEN_DIR_ALLOWLIST)
        )
        for fn in sorted(files):
            if fn.startswith(".") and fn != ".gitignore":
                continue
            p = Path(root) / fn
            rel = p.relative_to(workspace).as_posix()
            out.append({"path": rel, "size": p.stat().st_size, "type": "file"})
    return out
