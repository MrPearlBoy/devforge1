"""Restricted-subprocess sandbox (default provider).

Guarantees:

* no shell interpretation (``shell=False``), arguments passed as a list
* allow-listed binaries only, shell metacharacters rejected
* working directory clamped inside the DevForge workspace
* scrubbed environment (API keys/tokens never inherited)
* POSIX resource limits: CPU seconds, address space, file size, descriptors,
  subprocess count
* hard wall-clock timeout with process-group kill
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import resource
except ImportError:  # Windows does not provide POSIX resource limits.
    resource = None

from app.core.config import settings
from app.core.errors import ExecutionError
from app.core.logging import get_logger
from app.tools.executor.base import ExecutionResult, SandboxExecutor, truncate

logger = get_logger("devforge.executor.subprocess")


class SubprocessExecutor(SandboxExecutor):
    name = "subprocess"
    isolation = "restricted-subprocess (allow-list, rlimits, no shell, isolated cwd/env)"

    def _preexec(self):  # noqa: ANN202 - returns callable used in child process
        cpu_seconds = settings.execution_cpu_seconds
        memory_bytes = max(settings.execution_memory_mb, 256) * 1024 * 1024
        file_bytes = 64 * 1024 * 1024

        def _apply() -> None:  # pragma: no cover - runs in the forked child
            os.setsid()  # own process group so we can kill the whole tree
            limits = [
                (resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 5)),
                (resource.RLIMIT_FSIZE, (file_bytes, file_bytes)),
                (resource.RLIMIT_NOFILE, (512, 512)),
            ]
            if hasattr(resource, "RLIMIT_NPROC"):
                limits.append((resource.RLIMIT_NPROC, (128, 128)))
            if hasattr(resource, "RLIMIT_AS"):
                # Kept generous: Python + pytest reserve significant address space;
                # the hard guards are CPU time, wall clock and FSIZE.
                limits.append((resource.RLIMIT_AS, (memory_bytes, memory_bytes)))
            for resource_id, limit in limits:
                try:
                    resource.setrlimit(resource_id, limit)
                except (ValueError, OSError):  # pragma: no cover - platform specific
                    continue

        return _apply

    def run(self, command: list[str], *, cwd: str | Path | None = None,
            env: dict[str, str] | None = None, timeout: int | None = None) -> ExecutionResult:
        if not settings.execution_enabled:
            raise ExecutionError("Code execution is disabled (EXECUTION_ENABLED=false).")

        command = [str(part) for part in command]
        self.validate_command(command)
        # Map bare "python3" to the interpreter running DevForge when needed.
        if command[0] in {"python", "python3"}:
            command[0] = sys.executable
        workdir = self.resolve_cwd(cwd)
        timeout = int(timeout or settings.execution_timeout_seconds)
        started = time.perf_counter()
        _ = env  # non-sandbox env overrides are intentionally ignored

        try:
            process = subprocess.Popen(  # noqa: S603 - allow-listed, shell=False
                command,
                cwd=str(workdir),
                env=self.sandbox_env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                errors="replace",
                preexec_fn=self._preexec() if hasattr(os, "setsid") else None,
            )
        except FileNotFoundError as exc:
            raise ExecutionError(
                f"Executable '{command[0]}' is not installed in the sandbox.",
                detail={"command": command[0]},
            ) from exc

        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_tree(process)
            stdout, stderr = process.communicate()
            stderr = (stderr or "") + f"\n[DevForge] execution exceeded {timeout}s and was terminated."

        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout, cut_out = truncate(stdout or "")
        stderr, cut_err = truncate(stderr or "")
        return ExecutionResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
            timed_out=timed_out,
            provider=self.name,
            command=" ".join(Path(c).name if i == 0 else c for i, c in enumerate(command)),
            sandboxed=True,
            truncated=cut_out or cut_err,
            meta={"cwd": str(workdir), "timeout_seconds": timeout},
        )

    @staticmethod
    def _kill_tree(process: subprocess.Popen) -> None:  # pragma: no cover - timing dependent
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def availability(self) -> dict:
        return {
            "provider": self.name,
            "available": settings.execution_enabled,
            "isolation": self.isolation,
            "timeout_seconds": settings.execution_timeout_seconds,
            "memory_mb": settings.execution_memory_mb,
            "cpu_seconds": settings.execution_cpu_seconds,
            "allowed_commands": sorted(settings.allowed_commands),
        }
