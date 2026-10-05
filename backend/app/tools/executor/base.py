"""Sandbox execution abstraction.

DevForge may run AI-generated code, so execution is always mediated by this
interface.  The default provider is a *restricted subprocess* (allow-listed
binaries, no shell, CPU/memory/file limits, process-group kill on timeout);
a Docker provider offers stronger isolation when a daemon is available.

Rule 12 of the project rules: arbitrary generated code is never executed with
unrestricted host privileges.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings
from app.core.errors import ExecutionError

MAX_CAPTURE_BYTES = 200_000


@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    provider: str = ""
    command: str = ""
    sandboxed: bool = True
    truncated: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "provider": self.provider,
            "command": self.command,
            "sandboxed": self.sandboxed,
            "truncated": self.truncated,
            "ok": self.ok,
        }


class SandboxExecutor(ABC):
    """Runs a command inside a sandbox rooted at a project workspace."""

    name = "abstract"
    #: Advertised isolation level, surfaced in the UI so users know the guarantees.
    isolation = "unknown"

    def __init__(self, *, workspace_root: Path | None = None) -> None:
        self.workspace_root = Path(workspace_root) if workspace_root else settings.workspace_path

    # ------------------------------------------------------------------ checks
    def validate_command(self, command: list[str]) -> None:
        if not command:
            raise ExecutionError("No command supplied.")
        binary = Path(command[0]).name
        if binary not in settings.allowed_commands:
            raise ExecutionError(
                f"Command '{binary}' is not on the DevForge execution allow-list.",
                detail={"allowed": sorted(settings.allowed_commands)},
            )
        for argument in command:
            if any(char in argument for char in (";", "|", "&", "$(", "`", ">", "<", "\n")):
                raise ExecutionError(
                    "Command arguments contain shell metacharacters and were rejected.",
                    detail={"argument": argument[:120]},
                )

    def resolve_cwd(self, cwd: str | Path | None) -> Path:
        candidate = Path(cwd) if cwd else self.workspace_root
        candidate = candidate.resolve()
        root = self.workspace_root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ExecutionError(
                "Refusing to execute outside the DevForge workspace.",
                detail={"cwd": str(candidate)},
            )
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate

    def sandbox_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Minimal environment: no inherited secrets ever reach generated code."""
        import os

        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "HOME": str(self.workspace_root),
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "DEVFORGE_SANDBOX": "1",
            "CI": "1",
        }
        if os.name == "nt":
            for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "COMSPEC"):
                if key in os.environ:
                    env[key] = os.environ[key]
        env.update(extra or {})
        return env

    # -------------------------------------------------------------------- api
    @abstractmethod
    def run(
        self,
        command: list[str],
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """Execute ``command`` and return a structured result."""

    def availability(self) -> dict:
        return {"provider": self.name, "available": True, "isolation": self.isolation}


def truncate(text: str, limit: int = MAX_CAPTURE_BYTES) -> tuple[str, bool]:
    if text is None:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit] + f"\n... [truncated {len(text) - limit} characters]", True
