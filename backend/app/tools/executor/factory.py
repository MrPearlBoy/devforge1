"""Executor selection + a disabled provider for locked-down deployments."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.core.errors import ExecutionError
from app.core.logging import get_logger
from app.tools.executor.base import ExecutionResult, SandboxExecutor
from app.tools.executor.docker_executor import DockerExecutor
from app.tools.executor.subprocess_executor import SubprocessExecutor

logger = get_logger("devforge.executor")


class DisabledExecutor(SandboxExecutor):
    """Used when ``EXECUTION_PROVIDER=disabled``: refuses everything, loudly."""

    name = "disabled"
    isolation = "none (execution disabled by configuration)"

    def run(self, command, *, cwd=None, env=None, timeout=None) -> ExecutionResult:  # noqa: ANN001
        raise ExecutionError(
            "Code execution is disabled for this deployment "
            "(EXECUTION_PROVIDER=disabled). Enable it to run tests in the sandbox."
        )

    def availability(self) -> dict:
        return {"provider": self.name, "available": False, "isolation": self.isolation,
                "note": "Set EXECUTION_PROVIDER=subprocess or docker to enable test execution."}


def build_executor() -> SandboxExecutor:
    provider = (settings.execution_provider or "subprocess").lower()
    if provider == "disabled" or not settings.execution_enabled:
        logger.info("Execution provider: disabled")
        return DisabledExecutor()
    if provider == "docker":
        docker = DockerExecutor()
        status = docker.availability()
        if status["available"]:
            logger.info("Execution provider: docker (%s)", status.get("image"))
            return docker
        logger.warning(
            "Docker sandbox requested but unavailable (%s) — falling back to restricted subprocess.",
            status.get("note", "daemon not reachable"),
        )
    executor = SubprocessExecutor()
    logger.info("Execution provider: %s", executor.name)
    return executor


@lru_cache
def get_executor() -> SandboxExecutor:
    return build_executor()


def reset_executor() -> None:
    get_executor.cache_clear()


def executor_status() -> dict:
    return get_executor().availability()
