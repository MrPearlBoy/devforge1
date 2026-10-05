"""DevForge workflow engine — an explicit asynchronous state machine.

State graph
-----------
    created → requirement ──G1──► architecture ──G2──► coding ──G3──► testing
                  ▲                     │                  │  ▲           │
                  └────── reject ───────┘        reject ───┘  │  │ fail(D4)├──► coding (heal, no gate)
                                                          G3  │  │ pass     │
                                                            (auto)│  ▼      │
                                                       documentation ◄── security ──┘
                                                          │   ▲     │ findings(D5)
                                                          G6  └───── (fix, no gate)
                                                          ▼
                                                        delivery → completed

* G1/G2/G3/G6 are human approval gates: the machine halts (status
  ``waiting_approval``) until the reviewer sends a decision via the
  approvals API. ``rejected`` / ``changes_requested`` re-runs the same
  stage with the reviewer's feedback (bounded by ``max_gate_iterations``).
* D4 (tests) and D5 (security) are automated decision loops: on failure the
  Coding Agent is re-invoked in heal/fix mode WITHOUT a human gate, bounded
  by ``max_test_heals`` / ``max_security_fixes``; exceeding the bound fails
  the workflow with a clear error (rollback point for the human).
* Every transition, artifact write, scan and decision is persisted to
  ``workflow_events`` (audit trail) and streamed over SSE.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.architecture_agent import ArchitectureAgent
from app.agents.coding_agent import CodingAgent
from app.agents.documentation_agent import DocumentationAgent
from app.agents.requirement_agent import RequirementAgent
from app.agents.security_agent import SecurityAgent
from app.agents.testing_agent import TestingAgent
from app.core.config import get_settings
from app.core.errors import WorkflowError
from app.db.models import Approval, Project, SecurityFinding as SecurityFindingRow
from app.db.models import TestResult, WorkflowEvent
from app.db.session import SessionLocal
from app.execution import git_service, runner
from app.llm.client import LLMClient, create_llm
from app.orchestrator.state import (
    GATE_TITLES,
    DECISIONS,
    DocsArtifact,
    SecurityReport,
    TestReport,
    WorkflowState,
)
from app.streaming.bus import get_bus
from app.utils.files import safe_write, workspace_root
from app.utils.render import render_architecture_md, render_api_schema_json, render_requirements_md

log = logging.getLogger("devforge.engine")
settings = get_settings()

_engines: dict[str, "WorkflowEngine"] = {}


def get_engine(project_id: str) -> "WorkflowEngine":
    if project_id not in _engines:
        _engines[project_id] = WorkflowEngine(project_id)
    return _engines[project_id]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowEngine:
    """One engine instance per project; runs as a single asyncio task."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        p = self._fetch_project()
        if p is None:
            raise WorkflowError(f"project {project_id} not found")
        self.name = p.name
        self.task = p.task
        self.state = self._load_state(p)
        self.client: Optional[LLMClient] = None
        self._approval = asyncio.Event()
        self._decision: dict[str, Any] = {}
        self._task: Optional[asyncio.Task] = None
        self.bus = get_bus()

    # ------------------------------------------------------------------ util
    def _fetch_project(self) -> Optional[Project]:
        with SessionLocal() as db:
            return db.get(Project, self.project_id)

    @staticmethod
    def _load_state(p: Project) -> WorkflowState:
        if p.artifacts:
            try:
                return WorkflowState.model_validate(json.loads(p.artifacts))
            except (json.JSONDecodeError, ValueError):
                log.warning("could not restore workflow state for %s — starting fresh", p.id)
        return WorkflowState(project_id=p.id)

    def _persist(self, fields: dict[str, Any]) -> None:
        with SessionLocal() as db:
            p = db.get(Project, self.project_id)
            if p is None:
                return
            for k, v in fields.items():
                setattr(p, k, v)
            p.updated_at = datetime.now(timezone.utc)
            db.commit()

    def _sync(self) -> None:
        """Persist state columns + broadcast a live state frame."""
        self._persist(
            {
                "stage": self.state.stage,
                "status": self.state.status,
                "awaiting_gate": self.state.awaiting_gate,
                "error": self.state.error,
                "artifacts": self.state.model_dump_json(),
                "llm_provider": self.client.name if self.client else "",
            }
        )
        self.bus.publish(
            self.project_id,
            {
                "type": "state",
                "stage": self.state.stage,
                "message": f"stage={self.state.stage} status={self.state.status}",
                "payload": {
                    "stage": self.state.stage,
                    "status": self.state.status,
                    "awaiting_gate": self.state.awaiting_gate,
                    "iterations": self.state.iterations,
                    "error": self.state.error,
                },
                "ts": _now_iso(),
                "project_id": self.project_id,
            },
        )

    async def _emit(self, etype: str, message: str, payload: Optional[dict[str, Any]] = None) -> None:
        payload = payload or {}
        event = {
            "type": etype,
            "stage": self.state.stage,
            "message": message,
            "payload": payload,
            "ts": _now_iso(),
            "project_id": self.project_id,
        }
        with SessionLocal() as db:
            db.add(
                WorkflowEvent(
                    project_id=self.project_id,
                    type=etype,
                    stage=self.state.stage,
                    message=message,
                    payload=json.dumps(payload, default=str),
                )
            )
            db.commit()
        self.bus.publish(self.project_id, event)
        log.info("[%s][%s] %s", self.project_id[:8], etype, message)

    async def _fail(self, message: str) -> None:
        self.state.stage = "failed"
        self.state.status = "failed"
        self.state.error = message
        self.state.awaiting_gate = None
        self._sync()
        await self._emit("error", f"workflow FAILED: {message}", {"error": message})

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> bool:
        """Start (or resume) the workflow loop. Returns False if already running."""
        if self._task is not None and not self._task.done():
            return False
        self.client = create_llm()
        self._persist({"llm_provider": self.client.name})
        if self.state.stage == "completed":
            return False
        if self.state.stage == "failed":
            self.state.stage = self.state.stage  # keep; user must reset via API
            # allow retry: jump back to the stage before failure is not tracked,
            # so we restart from the first stage with existing artifacts intact.
            self.state.stage = "created" if self.state.requirement is None else (
                "requirement" if self.state.architecture is None
                else "coding" if self.state.code is None
                else "testing"
            )
            self.state.error = None
        await self._emit("system", f"workflow started (llm provider: {self.client.name})", {"provider": self.client.name})
        self._task = asyncio.create_task(self._run_loop())
        return True

    def submit_approval(self, gate: str, decision: str, comment: Optional[str]) -> bool:
        """Record a gate decision and wake the waiting engine. Returns False
        when the gate is not currently pending."""
        if decision not in DECISIONS:
            return False
        if self.state.awaiting_gate != gate:
            return False
        self._decision = {"gate": gate, "decision": decision, "comment": comment}
        with SessionLocal() as db:
            db.add(Approval(project_id=self.project_id, gate=gate, decision=decision, comment=comment))
            db.commit()
        self._approval.set()
        return True

    def _take_decision(self) -> dict[str, Any]:
        d = self._decision
        self._decision = {}
        return d

    async def _await_gate(self, gate: str) -> dict[str, Any]:
        """Interrupt point: halt until a human decides (G1/G2/G3/G6)."""
        st = self.state
        st.awaiting_gate = gate
        st.status = "waiting_approval"
        self._sync()
        summary = self._gate_summary(gate)
        await self._emit(
            "approval_requested",
            f"Gate {GATE_TITLES[gate]} — human approval required",
            {"gate": gate, "title": GATE_TITLES[gate], "summary": summary},
        )
        self._approval.clear()
        await self._approval.wait()
        st.awaiting_gate = None
        st.status = "running"
        d = self._take_decision()
        await self._emit("approval_recorded", f"Gate {GATE_TITLES[gate]} → {d['decision']}", d)
        self._sync()
        return d

    def _gate_summary(self, gate: str) -> str:
        st = self.state
        if gate == "requirement" and st.requirement:
            return (
                f"{len(st.requirement.functional_requirements)} functional requirements, "
                f"{len(st.requirement.user_stories)} user stories"
            )
        if gate == "architecture" and st.architecture:
            return (
                f"{len(st.architecture.api_endpoints)} API endpoints, "
                f"{len(st.architecture.modules)} modules"
            )
        if gate == "code" and st.code:
            return f"{len(st.code.files)} files generated in the workspace"
        if gate == "docs" and st.docs:
            return "README + API reference + architecture summary generated"
        return ""

    # ------------------------------------------------------------ main loop
    async def _run_loop(self) -> None:
        guard = 0
        try:
            while guard < 64:
                guard += 1
                stage = self.state.stage
                if stage in ("completed", "failed"):
                    break
                handler = {
                    "created": self._stage_requirement,
                    "requirement": self._stage_requirement,
                    "architecture": self._stage_architecture,
                    "coding": self._stage_coding,
                    "testing": self._stage_testing,
                    "security": self._stage_security,
                    "documentation": self._stage_documentation,
                    "delivery": self._stage_delivery,
                }.get(stage)
                if handler is None:
                    await self._fail(f"unknown stage '{stage}'")
                    break
                await handler()
            if self.state.stage not in ("completed", "failed"):
                await self._fail("workflow guard limit reached (too many transitions)")
        except Exception as exc:  # noqa: BLE001 — surface any crash as a failed stage
            log.exception("workflow crashed for project %s", self.project_id)
            await self._fail(f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------- stages
    async def _stage_requirement(self) -> None:
        st = self.state
        st.stage = "requirement"
        st.status = "running"
        self._sync()
        it = st.iterations.get("requirement", 0)
        await self._emit("stage", f"Requirement Agent starting (iteration {it + 1})")
        ctx = {
            "task": self.task,
            "project_name": self.name,
            "feedback": st.feedback.get("requirement"),
            "iteration": it,
        }
        spec = await RequirementAgent().run(ctx, self._emit, self.client)
        st.requirement = spec
        ws = workspace_root(self.project_id)
        safe_write(ws, "requirements/requirements.md", render_requirements_md(self.name, self.task, spec))
        await self._emit("artifact", "wrote requirements/requirements.md", {"path": "requirements/requirements.md"})
        self._sync()

        decision = await self._await_gate("requirement")
        if decision["decision"] == "approved":
            st.stage = "architecture"
        else:
            it += 1
            if it >= settings.max_gate_iterations:
                await self._fail(f"requirement stage rejected {it} times — giving up (reviewer: keep feedback actionable)")
                return
            st.iterations["requirement"] = it
            st.feedback["requirement"] = decision["comment"] or "Rejected by reviewer — tighten scope and make acceptance criteria measurable."
            st.stage = "requirement"
        self._sync()

    async def _stage_architecture(self) -> None:
        st = self.state
        st.stage = "architecture"
        st.status = "running"
        self._sync()
        it = st.iterations.get("architecture", 0)
        await self._emit("stage", f"Architecture Agent starting (iteration {it + 1})")
        ctx = {
            "task": self.task,
            "project_name": self.name,
            "requirements": st.requirement.model_dump() if st.requirement else None,
            "feedback": st.feedback.get("architecture"),
            "iteration": it,
        }
        spec = await ArchitectureAgent().run(ctx, self._emit, self.client)
        st.architecture = spec
        ws = workspace_root(self.project_id)
        safe_write(ws, "architecture/architecture.md", render_architecture_md(self.name, spec))
        safe_write(ws, "architecture/api_schema.json", render_api_schema_json(spec))
        await self._emit("artifact", "wrote architecture/architecture.md + architecture/api_schema.json", {})
        self._sync()

        decision = await self._await_gate("architecture")
        if decision["decision"] == "approved":
            st.stage = "coding"
        else:
            it += 1
            if it >= settings.max_gate_iterations:
                await self._fail(f"architecture stage rejected {it} times — giving up")
                return
            st.iterations["architecture"] = it
            st.feedback["architecture"] = decision["comment"] or "Rejected by reviewer — simplify the design."
            st.stage = "architecture"
        self._sync()

    async def _stage_coding(self) -> None:
        st = self.state
        st.stage = "coding"
        st.status = "running"
        self._sync()
        feedback = st.feedback.get("code") or ""
        mode = "initial"
        if feedback.startswith("SECURITY_FINDINGS"):
            mode = "security"
        elif feedback:
            mode = "heal"
        await self._emit("stage", f"Coding Agent starting (mode={mode})")
        ctx = {
            "task": self.task,
            "project_name": self.name,
            "requirements": st.requirement.model_dump() if st.requirement else None,
            "architecture": st.architecture.model_dump() if st.architecture else None,
            "mode": mode,
            "feedback": feedback or None,
            "previous_files": [f.path for f in st.code.files] if st.code else [],
        }
        artifact = await CodingAgent().run(ctx, self._emit, self.client)
        if not artifact.files:
            await self._fail("Coding Agent produced no files")
            return
        st.code = artifact
        ws = workspace_root(self.project_id)
        for f in artifact.files:
            safe_write(ws, f.path, f.content)
            await self._emit("file", f"wrote {f.path} ({len(f.content)} chars)", {"path": f.path})
        st.feedback.pop("code", None)
        self._sync()

        if st.skip_code_gate:
            st.skip_code_gate = False
            await self._emit("auto", "decision loop: self-heal in progress — continuing to Testing without a human gate", {})
            st.stage = "testing"
            self._sync()
            return

        decision = await self._await_gate("code")
        if decision["decision"] == "approved":
            st.stage = "testing"
        else:
            it = st.iterations.get("code", 0) + 1
            if it >= settings.max_gate_iterations:
                await self._fail(f"code stage rejected {it} times — giving up")
                return
            st.iterations["code"] = it
            st.feedback["code"] = decision["comment"] or "Code rejected by reviewer — revise the implementation."
            st.stage = "coding"
        self._sync()

    async def _stage_testing(self) -> None:
        st = self.state
        st.stage = "testing"
        st.status = "running"
        self._sync()
        await self._emit("stage", "Testing Agent generating test suite")
        ctx = {
            "project_name": self.name,
            "requirements": st.requirement.model_dump() if st.requirement else None,
            "architecture": st.architecture.model_dump() if st.architecture else None,
            "files": [{"path": f.path, "content": f.content} for f in (st.code.files if st.code else [])],
        }
        tests = await TestingAgent().run(ctx, self._emit, self.client)
        if not tests.files:
            await self._fail("Testing Agent produced no test files")
            return
        ws = workspace_root(self.project_id)
        for f in tests.files:
            safe_write(ws, f.path, f.content)
            await self._emit("file", f"wrote {f.path} ({len(f.content)} chars)", {"path": f.path})

        await self._emit("tests", "Decision loop D4: executing pytest in the sandbox…", {})
        report = await asyncio.to_thread(runner.run_pytest, ws, settings.test_timeout)
        st.tests = TestReport(**report)
        with SessionLocal() as db:
            db.add(
                TestResult(
                    project_id=self.project_id,
                    run_number=st.iterations.get("test_heals", 0) + 1,
                    passed=report["passed"],
                    total=report["total"],
                    failed=report["failed_count"],
                    exit_code=report["exit_code"],
                    duration_s=report["duration_s"],
                    summary=report["summary"],
                    output=report["output"][:40000],
                )
            )
            db.commit()
        await self._emit(
            "tests",
            f"pytest: {report['summary']} ({report['duration_s']:.2f}s)",
            {"passed": report["passed"], "summary": report["summary"], "failures": report["failures"], "output": report["output"][-8000:]},
        )
        self._sync()

        if report["passed"]:
            st.stage = "security"
        else:
            heals = st.iterations.get("test_heals", 0) + 1
            if heals > settings.max_test_heals:
                await self._fail(f"tests still failing after {settings.max_test_heals} self-heal attempts: {report['summary']}")
                return
            st.iterations["test_heals"] = heals
            st.feedback["code"] = (
                "TEST_FAILURES:\n"
                + "\n".join(report["failures"][:8])
                + "\nOutput tail:\n"
                + report["output"][-4000:]
            )
            st.skip_code_gate = True
            st.stage = "coding"
            await self._emit("auto", f"D4 failed → routing to Coding Agent for self-heal (attempt {heals}/{settings.max_test_heals})", {})
        self._sync()

    async def _stage_security(self) -> None:
        st = self.state
        st.stage = "security"
        st.status = "running"
        self._sync()
        report = await SecurityAgent().run(workspace_root(self.project_id), self._emit, settings.scan_timeout)
        st.security = report
        with SessionLocal() as db:
            db.query(SecurityFindingRow).filter_by(project_id=self.project_id, status="open").update({"status": "resolved"})
            for f in report.findings:
                db.add(
                    SecurityFindingRow(
                        project_id=self.project_id,
                        severity=f.severity,
                        category=f.category,
                        message=f.message,
                        file=f.file or None,
                        line=f.line,
                        status="open",
                    )
                )
            db.commit()
        self._sync()

        blocking = [f for f in report.findings if f.severity == "HIGH"]
        if report.clean:
            st.stage = "documentation"
        else:
            fixes = st.iterations.get("security_fixes", 0) + 1
            if fixes > settings.max_security_fixes:
                await self._fail(f"security findings remain after {settings.max_security_fixes} fix loops")
                return
            st.iterations["security_fixes"] = fixes
            st.feedback["code"] = "SECURITY_FINDINGS:\n" + json.dumps([f.model_dump() for f in blocking], indent=2)[:6000]
            st.skip_code_gate = True
            st.stage = "coding"
            await self._emit("auto", f"D5 failed → routing to Coding Agent for security fix (attempt {fixes}/{settings.max_security_fixes})", {})
        self._sync()

    async def _stage_documentation(self) -> None:
        st = self.state
        st.stage = "documentation"
        st.status = "running"
        self._sync()
        it = st.iterations.get("documentation", 0)
        await self._emit("stage", f"Documentation Agent starting (iteration {it + 1})")
        ctx = {
            "project_name": self.name,
            "task": self.task,
            "requirements": st.requirement.model_dump() if st.requirement else None,
            "architecture": st.architecture.model_dump() if st.architecture else None,
            "files": [{"path": f.path, "description": f.description} for f in (st.code.files if st.code else [])],
            "run_instructions": st.code.run_instructions if st.code else "",
            "tests": st.tests.model_dump() if st.tests else None,
            "security": {"clean": st.security.clean, "tool": st.security.tool} if st.security else None,
            "feedback": st.feedback.get("docs"),
            "iteration": it,
        }
        docs: DocsArtifact = await DocumentationAgent().run(ctx, self._emit, self.client)
        st.docs = docs
        ws = workspace_root(self.project_id)
        safe_write(ws, "README.md", docs.readme)
        safe_write(ws, "docs/api.md", docs.api_documentation)
        safe_write(ws, "docs/architecture.md", docs.architecture_summary)
        await self._emit("artifact", "wrote README.md, docs/api.md, docs/architecture.md", {})
        self._sync()

        decision = await self._await_gate("docs")
        if decision["decision"] == "approved":
            st.stage = "delivery"
        else:
            it += 1
            if it >= settings.max_gate_iterations:
                await self._fail(f"docs stage rejected {it} times — giving up")
                return
            st.iterations["documentation"] = it
            st.feedback["docs"] = decision["comment"] or "Docs rejected by reviewer — revise."
            st.stage = "documentation"
        self._sync()

    async def _stage_delivery(self) -> None:
        st = self.state
        st.stage = "delivery"
        st.status = "running"
        self._sync()
        await self._emit("git", "Delivery & GitSync: initializing git repo + CI/CD workflow in workspace…")
        ws = workspace_root(self.project_id)
        git_info = await asyncio.to_thread(git_service.deliver, ws, self.name)
        st.git = git_info
        self._sync()
        await self._emit(
            "git",
            f"committed {git_info.get('files', 0)} files on {git_info.get('branch', 'main')} "
            f"(commit {(git_info.get('hash') or '?')[:8]})",
            git_info,
        )
        st.stage = "completed"
        st.status = "completed"
        st.error = None
        self._sync()
        await self._emit("done", "Delivery complete — codebase approved, committed and CI workflow configured", {"git": git_info})
