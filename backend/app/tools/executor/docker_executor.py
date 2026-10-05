"""Docker-based sandbox (stronger isolation).

Runs generated code in a throwaway container with no network, a read-only
workspace mount, capped memory/CPU/PIDs and a non-root user.  Selected with
``EXECUTION_PROVIDER=docker``; if the daemon or image is unavailable the factory
falls back to the restricted-subprocess provider and says so explicitly.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.config import settings
from app.core.errors import ExecutionError
from app.core.logging import get_logger
from app.tools.executor.base import ExecutionResult, SandboxExecutor, truncate

logger = get_logger("devforge.executor.docker")


class DockerExecutor(SandboxExecutor):
    name = "docker"
    isolation = "docker container (no network, capped cpu/memory/pids, non-root user)"

    def __init__(self, *, workspace_root: Path | None = None, image: str | None = None) -> None:
        super().__init__(workspace_root=workspace_root)
        self.image = image or settings.docker_execution_image

    # ------------------------------------------------------------------ checks
    def _docker_binary(self) -> str:
        binary = shutil.which("docker")
        if not binary:
            raise ExecutionError("Docker is not installed on this host.")
        return binary

    def availability(self) -> dict:
        binary = shutil.which("docker")
        daemon_ok = False
        if binary:
            try:
                import subprocess

                probe = subprocess.run(  # noqa: S603
                    [binary, "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True, text=True, timeout=8, check=False,
                )
                daemon_ok = probe.returncode == 0
            except Exception:  # pragma: no cover - environment dependent
                daemon_ok = False
        return {
            "provider": self.name,
            "available": bool(binary and daemon_ok),
            "isolation": self.isolation,
            "image": self.image,
            "note": "Fallback to restricted subprocess when unavailable.",
        }

    # -------------------------------------------------------------------- run
    def run(self, command: list[str], *, cwd: str | Path | None = None,
            env: dict[str, str] | None = None, timeout: int | None = None) -> ExecutionResult:
        binary = self._docker_binary()
        self.validate_command(command)
        workdir = self.resolve_cwd(cwd)
        timeout = int(timeout or settings.execution_timeout_seconds)
        rel = workdir.relative_to(self.workspace_root.resolve())

        docker_command = [
            binary, "run", "--rm",
            "--network", "none",
            "--memory", f"{settings.execution_memory_mb}m",
            "--cpus", "1",
            "--pids-limit", "128",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
            "--user", "65534:65534",
            "-v", f"{workdir}:/workspace:rw",
            "-w", "/workspace",
            "-e", "PYTHONUNBUFFERED=1",
            "-e", "DEVFORGE_SANDBOX=1",
            self.image,
            *[str(part) for part in command],
        ]
        logger.info("Docker sandbox run: image=%s cwd=%s", self.image, rel)

        import subprocess

        started = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603 - docker CLI, fixed argv
                docker_command, capture_output=True, text=True, timeout=timeout, check=False,
                errors="replace",
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.perf_counter() - started) * 1000)
            return ExecutionResult(
                exit_code=-1,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr="[DevForge] container exceeded its time limit and was removed.",
                duration_ms=duration_ms,
                timed_out=True,
                provider=self.name,
                command=" ".join(command),
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout, cut_out = truncate(completed.stdout or "")
        stderr, cut_err = truncate(completed.stderr or "")
        return ExecutionResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            provider=self.name,
            command=" ".join(command),
            sandboxed=True,
            truncated=cut_out or cut_err,
            meta={"image": self.image, "mount": str(rel)},
        )
