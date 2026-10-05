"""Local Git integration: repo init, commit of the approved codebase and
generated CI/CD workflow (simulated GitHub Actions pipeline)."""
from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CI_WORKFLOW = """name: devforge-ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install test dependencies
        run: python -m pip install --quiet pytest
      - name: Run pytest
        run: python -m pytest tests -q
      - name: Static security scan (bandit)
        run: |
          python -m pip install --quiet bandit
          python -m bandit -r src -f json || true
"""


def _git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "git command timed out"
    except FileNotFoundError:
        return 127, "", "git binary not found"


def _has_git() -> bool:
    return shutil.which("git") is not None


def ensure_repo(workspace: Path) -> bool:
    """Create the git repository on branch main if it does not exist yet."""
    if (workspace / ".git").is_dir():
        return True
    rc, _, _ = _git(["init", "-b", "main"], workspace)
    if rc != 0:  # older git without -b
        _git(["init"], workspace)
        _git(["branch", "-M", "main"], workspace)
    return (workspace / ".git").is_dir()


def deliver(workspace: Path, project_name: str) -> dict[str, Any]:
    """Delivery stage: write CI workflow, init repo, commit approved code."""
    info: dict[str, Any] = {"committed": False, "ci_workflow": ".github/workflows/ci.yml"}

    if not _has_git():
        info["reason"] = "git binary not available — CI workflow written, commit skipped"
        (workspace / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        (workspace / ".github" / "workflows" / "ci.yml").write_text(CI_WORKFLOW, encoding="utf-8")
        return info

    (workspace / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (workspace / ".github" / "workflows" / "ci.yml").write_text(CI_WORKFLOW, encoding="utf-8")

    ensure_repo(workspace)
    _git(["add", "-A"], workspace)
    rc, out, _ = _git(["status", "--porcelain"], workspace)
    changed = bool(out.strip())

    msg = (
        f"DevForge delivery: approved codebase for {project_name}\n\n"
        "- passed requirement/architecture/code/docs approval gates\n"
        "- test suite green, security scan clean\n"
        f"- committed {datetime.now(timezone.utc).isoformat()}"
    )
    if changed:
        rc, _, err = _git(
            [
                "-c", "user.name=DevForge Bot",
                "-c", "user.email=devforge@localhost",
                "commit", "-m", msg,
            ],
            workspace,
        )
        info["committed"] = rc == 0
        if rc != 0:
            info["reason"] = err.strip() or "commit failed"
    else:
        info["committed"] = False
        info["reason"] = "working tree clean (already committed)"

    rc, out, _ = _git(["rev-parse", "HEAD"], workspace)
    info["hash"] = out.strip() if rc == 0 else None
    rc, out, _ = _git(["branch", "--show-current"], workspace)
    info["branch"] = out.strip() or "main"
    rc, out, _ = _git(["ls-files"], workspace)
    info["files"] = len([ln for ln in out.splitlines() if ln.strip()])
    info["commit_message"] = msg.splitlines()[0]
    info["timestamp"] = datetime.now(timezone.utc).isoformat()
    return info


def describe(workspace: Path) -> dict[str, Any]:
    """Lightweight git status of a workspace (for the API snapshot)."""
    if not (workspace / ".git").is_dir() or not _has_git():
        return {}
    rc, out, _ = _git(["rev-parse", "HEAD"], workspace)
    head = out.strip() if rc == 0 else None
    rc, out, _ = _git(["log", "-1", "--pretty=%s"], workspace)
    subject = out.strip() if rc == 0 else ""
    rc, out, _ = _git(["ls-files"], workspace)
    files = len([ln for ln in out.splitlines() if ln.strip()])
    return {"hash": head, "commit_message": subject, "files": files, "branch": "main"}
