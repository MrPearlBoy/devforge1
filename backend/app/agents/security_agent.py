"""Security Agent (SA): static vulnerability scan of the generated code.

The scan is executed locally in the execution sandbox
(:mod:`app.execution.runner`): ``bandit`` when installed, otherwise the
built-in AST + regex analyzer. The agent wraps that scan into the workflow
event stream and a typed :class:`SecurityReport`.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.execution import runner
from app.orchestrator.state import SecurityReport


class SecurityAgent:
    name = "Security Agent"
    stage = "security"

    async def run(self, workspace: Path, emit, timeout: float, context: dict[str, Any] | None = None) -> SecurityReport:
        del context  # reserved for LLM-driven deep review in a future version
        await emit("security", f"{self.name} scanning {workspace.name}/src (bandit or AST analyzer)...", {"stage": self.stage})
        report = await asyncio.to_thread(runner.run_security_scan, workspace, timeout)
        blocking = [f for f in report["findings"] if f["severity"] == "HIGH"]
        informational = len(report["findings"]) - len(blocking)
        verdict = "clean" if report["clean"] else f"{len(blocking)} blocking finding(s)"
        await emit(
            "security",
            f"scan complete via {report['tool']}: {verdict} ({informational} informational)",
            {"clean": report["clean"], "tool": report["tool"], "findings": report["findings"][:40]},
        )
        return SecurityReport(
            clean=report["clean"],
            tool=report["tool"],
            findings=report["findings"],
            output=report["output"][:20000],
        )
