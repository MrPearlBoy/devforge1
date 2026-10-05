"""Testing Agent.

Generates a test plan plus runnable pytest files, executes them through the
sandbox (``TestRunner`` → ``SandboxExecutor``) and attaches the structured results
to the outcome so the runtime can persist ``test_runs`` / ``test_results``.

Failures are reported per test with the captured assertion output, which is exactly
what the Developer Agent needs for its fix loop — no failure is ever hidden or
invented.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.base import AgentOutcome, ArtifactDraft, BaseAgent
from app.agents.common.domain_inference import DomainModel, infer_domain
from app.agents.testing.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.agents.testing.schemas import TestPlan
from app.core.logging import get_logger
from app.models.enums import ArtifactType, Stage, TraceNodeType
from app.services.agent_registry import get_agent_spec
from app.services.project_context import AgentContext
from app.services.workspace import WorkspaceService
from app.tools.executor.base import ExecutionResult
from app.tools.test_runner import ParsedTestRun, TestRunner

logger = get_logger("devforge.agent.testing")


class TestingAgent(BaseAgent):
    spec = get_agent_spec("testing")
    prompt_version = PROMPT_VERSION
    output_schema = TestPlan

    # ------------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        return build_user_prompt(context.to_prompt_block(), task)

    # --------------------------------------------------------------- mock plan
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        cases = payload.get("test_cases", [])
        files = payload.get("files", [])
        markdown = self._plan_markdown(payload, context)

        trace_pairs: list[dict] = []
        for item in files:
            for requirement_ref in item.get("requirement_refs", []):
                trace_pairs.append(
                    {
                        "source_type": TraceNodeType.REQUIREMENT.value,
                        "source_ref": requirement_ref,
                        "source_label": f"Requirement {requirement_ref}",
                        "target_type": TraceNodeType.TEST.value,
                        "target_ref": f"TEST {item['path']}",
                        "target_label": item.get("summary", item["path"]),
                        "relation": "verified_by",
                    }
                )

        return AgentOutcome(
            agent_key=self.key,
            stage=self.stage,
            content=markdown,
            summary=f"Prepared {len(cases)} test case(s) across {len(files)} file(s)",
            artifacts=[
                ArtifactDraft(
                    artifact_type=ArtifactType.TEST_PLAN.value,
                    stage=Stage.TESTING.value,
                    title="Test plan and test suite",
                    content=markdown,
                    summary=f"{len(cases)} test cases in {len(files)} file(s)",
                    path="tests/test_plan.md",
                    data=payload,
                    trace_refs=[case["id"] for case in cases],
                )
            ],
            structured=payload,
            trace_pairs=trace_pairs,
            auto_apply_files=[
                {"path": item["path"], "content": item["content"], "operation": "create",
                 "summary": item.get("summary", ""), "language": "python"}
                for item in files
            ],
            meta={"case_count": len(cases), "file_count": len(files)},
        )

    # ---------------------------------------------------------- execution phase
    def run(self, context: AgentContext, task: str = "") -> AgentOutcome:
        """Plan → write tests → execute in the sandbox → attach structured results."""
        outcome = super().run(context, task)
        workspace = WorkspaceService()

        # Test files are auxiliary artifacts: the agent writes them before execution
        # (the target of the test is the approved product code, not the tests).
        for item in outcome.auto_apply_files:
            try:
                workspace.write_text(context.project_id, item["path"], item["content"])
            except Exception as exc:
                outcome.warnings.append(f"Could not write test file {item['path']}: {exc}")

        project_dir = workspace.project_dir(context.project_id)
        try:
            parsed = TestRunner().run(project_dir)
            outcome.meta["test_run"] = self._test_run_payload(parsed)
            outcome.summary = (
                f"{parsed.passed}/{parsed.total} tests passed "
                f"({parsed.failed} failed, {parsed.errors} errors, {parsed.duration_ms} ms)"
            )
            outcome.artifacts.append(
                ArtifactDraft(
                    artifact_type=ArtifactType.TEST_RESULTS.value,
                    stage=Stage.TESTING.value,
                    title="Test execution results",
                    content=self._results_markdown(parsed),
                    summary=outcome.summary,
                    path="tests/test_results.json",
                    data=self._test_run_payload(parsed),
                    trace_refs=[
                        result.name for result in parsed.results if result.status == "PASSED"
                    ][:80],
                )
            )
            if parsed.failed or parsed.errors:
                failing = [result.name for result in parsed.results
                           if result.status in {"FAILED", "ERROR"}][:5]
                outcome.warnings.append(
                    "Test failures must be fixed by the Developer Agent before delivery: "
                    + ", ".join(failing)
                )
        except Exception as exc:
            logger.warning("Test execution failed: %s", exc)
            outcome.warnings.append(
                f"Tests could not be executed in the sandbox: {exc}. "
                "The plan is stored, but no execution results are available."
            )
            outcome.meta["test_run"] = {
                "status": "ERROR", "total": 0, "passed": 0, "failed": 0, "skipped": 0,
                "errors": 0, "duration_ms": 0, "results": [], "raw_output": str(exc)[:4000],
                "command": "", "provider": "", "notes": ["Sandbox execution failed."],
            }
        return outcome

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _test_run_payload(parsed: ParsedTestRun) -> dict:
        return {
            "status": parsed.status,
            "total": parsed.total,
            "passed": parsed.passed,
            "failed": parsed.failed,
            "skipped": parsed.skipped,
            "errors": parsed.errors,
            "duration_ms": parsed.duration_ms,
            "command": parsed.command,
            "provider": parsed.provider,
            "parser": parsed.parser,
            "raw_output": parsed.raw_output[-20000:],
            "notes": parsed.notes,
            "layout": parsed.layout,
            "results": [
                {
                    "name": result.name,
                    "file_path": result.file_path,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "message": result.message[:2000],
                }
                for result in parsed.results
            ],
        }

    @staticmethod
    def _domain(context: AgentContext) -> DomainModel:
        requirements = next(
            (artifact.get("data") or {} for artifact in context.artifacts.values()
             if artifact.get("type") == ArtifactType.REQUIREMENTS.value),
            {},
        )
        source_text = " ".join(
            [
                context.project.get("requirement_input", ""),
                " ".join(
                    f"{item.get('title', '')} {item.get('description', '')}"
                    for item in requirements.get("functional_requirements", [])
                ),
            ]
        )
        return infer_domain(
            source_text,
            requirements.get("functional_requirements"),
            roles=[role.get("name", "") for role in requirements.get("user_roles", [])],
        )

    @staticmethod
    def _sample_payload(entity) -> dict:  # noqa: ANN001 - EntitySpec
        payload = {
            "title": "Sample record",
            "name": "Sample record",
            "description": "Created by the rules test suite",
        }
        return {field.name: payload.get(field.name, f"sample {field.name}")
                for field in entity.fields if field.required}

    def _rules_test_file(self, domain: DomainModel, entity, sample: dict) -> str:  # noqa: ANN001
        payload_json = ",\n        ".join(f'"{key}": {value!r}' for key, value in sample.items())
        has_status = any(field.name == "status" for field in entity.fields)
        has_completed = any(field.name == "completed_at" for field in entity.fields)
        status_test = ""
        if has_status:
            status_test = f'''

def test_status_change_is_persisted(client: TestClient) -> None:
    """TEST-005 — a status change must survive a fresh read."""
    headers = _auth_headers(client)
    created = client.post("/api/{entity.table}", json={{{payload_json}}}, headers=headers).json()
    updated = client.patch(f"/api/{entity.table}/{{created['id']}}/status",
                           json={{"status": "in-progress"}}, headers=headers)
    assert updated.status_code == 200
    reread = client.get(f"/api/{entity.table}/{{created['id']}}", headers=headers)
    assert reread.json()["status"] == "in-progress"
'''
        completion_test = ""
        if has_completed:
            completion_test = f'''

def test_completion_sets_timestamp() -> None:
    """TEST-006 — completing a record records when it happened."""
    with TestClient(create_app()) as client:
        headers = _auth_headers(client)
        created = client.post("/api/{entity.table}", json={{{payload_json}}},
                              headers=headers).json()
        done = client.post(f"/api/{entity.table}/{{created['id']}}/complete", headers=headers)
        assert done.status_code == 200
        assert done.json()["completed_at"] is not None
'''
        return f'''"""Business-rule tests for the {entity.name} resource (generated by the Testing Agent).

These tests are written against the public HTTP API so they survive internal
refactoring. Each test maps to the requirement ids recorded in the test plan.
"""
from __future__ import annotations

import os
import tempfile
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", f"sqlite:///{{tempfile.mkdtemp()}}/rules.db")
os.environ.setdefault("JWT_SECRET", "unit-test-secret-key-0123456789abcdef")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

PAYLOAD = {{
        {payload_json},
    }}


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client


def _auth_headers(client: TestClient) -> dict:
    email = f"rules-{{uuid.uuid4().hex[:8]}}@example.com"
    client.post("/api/auth/register", json={{"full_name": "Rules Tester", "email": email,
                                             "password": "supersecret123"}})
    token = client.post("/api/auth/login",
                        json={{"email": email, "password": "supersecret123"}}).json()["access_token"]
    return {{"Authorization": f"Bearer {{token}}"}}
{status_test}{completion_test}

def test_listing_honours_limit_and_order(client: TestClient) -> None:
    """TEST-002 — paging works and the newest record comes first."""
    headers = _auth_headers(client)
    for index in range(3):
        body = dict(PAYLOAD)
        client.post("/api/{entity.table}", json=body, headers=headers)

    response = client.get("/api/{entity.table}?limit=2", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) <= 2
    created = [item["created_at"] for item in response.json()]
    assert created == sorted(created, reverse=True)


def test_empty_payload_is_rejected(client: TestClient) -> None:
    """TEST-004 — required fields are enforced at the API boundary."""
    headers = _auth_headers(client)
    response = client.post("/api/{entity.table}", json={{}}, headers=headers)
    assert response.status_code == 422


def test_ownership_isolation(client: TestClient) -> None:
    """TEST-003 — another account must not see this record."""
    owner = _auth_headers(client)
    created = client.post("/api/{entity.table}", json=PAYLOAD, headers=owner).json()
    stranger = _auth_headers(client)
    assert client.get(f"/api/{entity.table}/{{created['id']}}", headers=stranger).status_code == 404


def test_unknown_identifier_returns_404(client: TestClient) -> None:
    """Deleting or reading a non-existent record is a clean 404, not a 500."""
    headers = _auth_headers(client)
    assert client.get(f"/api/{entity.table}/{{uuid.uuid4()}}", headers=headers).status_code == 404
'''

    def _plan_markdown(self, payload: dict, context: AgentContext) -> str:
        lines = [
            f"# Test Plan — {context.project.get('name', 'project')}",
            "",
            f"_Produced by the **Testing Agent** ({self.prompt_version}) — tests are executed in "
            "the DevForge sandbox immediately after this plan is stored._",
            "",
            "## Strategy",
            "",
            payload.get("strategy", ""),
            "",
            "## Scope",
            "",
        ]
        lines += [f"- {item}" for item in payload.get("scope", [])] or ["- Not specified"]
        lines += ["", "## Environments", ""]
        lines += [f"- {item}" for item in payload.get("environments", [])] or ["- Sandbox"]
        lines += ["", "## Test cases", "",
                  "| ID | Name | Type | Target | Requirement refs |", "| --- | --- | --- | --- | --- |"]
        for case in payload.get("test_cases", []):
            lines.append(
                f"| {case['id']} | {case['name']} | {case.get('type', '')} | "
                f"`{case.get('target', '')}` | {', '.join(case.get('requirement_refs', [])) or '—'} |"
            )
        lines += ["", "## Test files", ""]
        for item in payload.get("files", []):
            lines += [f"### `{item['path']}`", "", item.get("summary", ""), ""]
            lines += ["```python", item["content"].rstrip(), "```", ""]
        lines += ["## Exit criteria", ""]
        lines += [f"- {item}" for item in payload.get("exit_criteria", [])] or ["- All tests pass"]
        if payload.get("risks"):
            lines += ["", "## Risks / not covered", ""]
            lines += [f"- {item}" for item in payload["risks"]]
        if payload.get("notes"):
            lines += ["", "## Notes", ""]
            lines += [f"- {item}" for item in payload["notes"]]
        return "\n".join(lines)

    def _results_markdown(self, parsed: ParsedTestRun) -> str:
        status_icon = {"PASSED": "PASSED", "FAILED": "FAILED", "ERROR": "ERROR"}.get(
            parsed.status, parsed.status)
        lines = [
            "# Test Execution Results",
            "",
            f"**Status:** {status_icon}  ",
            f"**Totals:** {parsed.total} collected · {parsed.passed} passed · {parsed.failed} failed · "
            f"{parsed.skipped} skipped · {parsed.errors} errors  ",
            f"**Duration:** {parsed.duration_ms} ms  ",
            f"**Command:** `{parsed.command}`  ",
            f"**Sandbox provider:** {parsed.provider}  ",
            f"**Parser:** {parsed.parser}",
            "",
            "## Test results",
            "",
            "| Test | File | Status | Message |",
            "| --- | --- | --- | --- |",
        ]
        for result in parsed.results:
            message = (result.message or "").replace("\n", " ")[:180]
            lines.append(
                f"| `{result.name.split('::')[-1]}` | `{result.file_path or '-'}` | "
                f"{result.status} | {message or '—'} |"
            )
        if not parsed.results:
            lines.append("| — | — | — | No individual results parsed |")

        if parsed.notes:
            lines += ["", "## Execution notes", ""]
            lines += [f"- {note}" for note in parsed.notes]
        lines += [
            "",
            "## Raw output (tail)",
            "",
            "```text",
            parsed.raw_output[-4000:].rstrip(),
            "```",
            "",
            "_Failures are routed back to the Developer Agent for correction; the workflow only "
            "advances to the Security stage when the suite is green or a human explicitly accepts "
            "the failures._",
        ]
        return "\n".join(lines)
