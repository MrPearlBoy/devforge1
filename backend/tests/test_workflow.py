"""The LangGraph workflow: gates, artefacts and the mock-mode agent outputs."""
from __future__ import annotations


def test_developer_receives_actionable_test_and_security_feedback(monkeypatch):
    from app.workflows import nodes

    scan = {
        "counts": {"HIGH": 1},
        "files_scanned": 4,
        "findings": [
            {
                "severity": "HIGH",
                "rule_id": "SEC-001",
                "title": "Weak signing secret",
                "file_path": "app/config.py",
                "line": 4,
                "description": "The JWT signing key is weak.",
                "evidence": "SECRET = 'x'",
                "recommendation": "Load a strong secret from the environment.",
            }
        ],
    }
    security_results = nodes._security_result_payload(scan)
    captured = {}

    def capture_agent_call(state, agent_key, *, stage, instructions="", **kwargs):
        captured.update(
            agent_key=agent_key,
            stage=stage,
            instructions=instructions,
            task=kwargs.get("task", ""),
        )
        return {}

    monkeypatch.setattr(nodes, "_agent_node", capture_agent_call)
    nodes.developer_agent_node(
        {
            "instructions": "Keep the patch focused.",
            "approval_status": "REQUEST_CHANGES",
            "approval": {
                "gate": "test_review",
                "comments": "Handle expired tokens in the login flow.",
                "instructions": "Preserve the current response schema.",
            },
            "security_results": security_results,
            "test_results": {
                "status": "FAILED",
                "results": [
                    {
                        "name": "test_login",
                        "file_path": "tests/test_auth.py",
                        "status": "FAILED",
                        "message": "Expected 200, got 500",
                    }
                ],
            },
        }
    )

    assert captured["agent_key"] == "developer"
    assert captured["stage"] == "DEVELOPMENT"
    assert "Fix the reported failing tests" in captured["task"]
    assert "Remediate the Security Agent findings" in captured["task"]
    assert "test_review review" in captured["task"]
    assert "Handle expired tokens" in captured["task"]
    assert "test_login" in captured["task"]
    assert "tests/test_auth.py" in captured["task"]
    assert "test_login" in captured["instructions"]
    assert "Expected 200, got 500" in captured["instructions"]
    assert "SEC-001" in captured["instructions"]
    assert "app/config.py:4" in captured["instructions"]
    assert "Load a strong secret from the environment" in captured["instructions"]


def test_approved_empty_developer_revision_does_not_repeat_failing_tests():
    from app.models.enums import ApprovalDecision, Stage
    from app.workflows.graph import after_code_review

    assert after_code_review(
        {
            "approval_status": ApprovalDecision.APPROVE.value,
            "current_stage": Stage.DEVELOPMENT.value,
            "iterations": {Stage.DEVELOPMENT.value: 1},
            "max_stage_iterations": 3,
            "test_results": {"status": "FAILED"},
            "source_changes": {
                "file_count": 1,
                "additions": 0,
                "deletions": 0,
                "files": ["backend/app/main.py"],
            },
        }
    ) == "escalate"


def test_project_context_includes_and_prioritizes_failed_backend_test(tmp_path, monkeypatch):
    from app.services.project_context import ProjectContextService
    from app.services.workspace import WorkspaceService

    workspace = WorkspaceService(root=tmp_path)
    project_id = "context-test"
    for index in range(15):
        workspace.write_text(
            project_id, f"backend/app/module_{index:02}.py", f"VALUE = {index}\n"
        )
    failure_path = "backend/tests/test_regression.py"
    workspace.write_text(project_id, failure_path, "def test_regression():\n    assert False\n")

    context = ProjectContextService(db=None, workspace=workspace)
    monkeypatch.setattr(context, "search_project_knowledge", lambda *args, **kwargs: [])
    files = context.get_relevant_source_files(
        project_id,
        f"Fix failing test in {failure_path}",
    )

    assert failure_path in files
    assert "backend/app/module_00.py" in files
    assert len(files) == 12


def test_project_context_matches_test_runner_path_without_backend_prefix(
    tmp_path, monkeypatch
):
    from app.services.project_context import ProjectContextService
    from app.services.workspace import WorkspaceService

    workspace = WorkspaceService(root=tmp_path)
    project_id = "test-runner-path"
    for index in range(15):
        workspace.write_text(
            project_id, f"backend/app/module_{index:02}.py", f"VALUE = {index}\n"
        )
    workspace.write_text(
        project_id,
        "backend/tests/test_auth.py",
        "def test_login():\n    assert False\n",
    )

    context = ProjectContextService(db=None, workspace=workspace)
    monkeypatch.setattr(context, "search_project_knowledge", lambda *args, **kwargs: [])
    files = context.get_relevant_source_files(
        project_id, "Fix failing test tests/test_auth.py::test_login"
    )

    assert "backend/tests/test_auth.py" in files


def test_mock_developer_does_not_return_explanation_for_failed_test_feedback():
    from app.agents.developer.agent import DeveloperAgent
    from app.services.project_context import AgentContext
    from app.tools.llm.gateway import LLMGateway
    from app.tools.llm.mock_provider import MockProvider

    context = AgentContext(
        project_id="mock-repair",
        project={"name": "Repair test"},
        stage="DEVELOPMENT",
        source_files={
            "backend/app/main.py": "def answer():\n    return 41\n",
            "backend/tests/test_main.py": (
                "def test_answer():\n    assert answer() == 42\n"
            ),
        },
    )
    agent = DeveloperAgent(LLMGateway(MockProvider(), mode="mock"))

    payload = agent.mock_payload(
        context,
        "Fix the reported failing tests. "
        "tests/test_main.py::test_answer FAILED: assert 41 == 42",
    )

    assert payload["changes"] == []
    assert "MOCK MODE" in payload["analysis"]
    assert any("remain unresolved" in risk for risk in payload["risks"])


def test_mock_developer_does_not_claim_unknown_security_rule_is_fixed():
    from app.agents.developer.agent import DeveloperAgent
    from app.services.project_context import AgentContext
    from app.tools.llm.gateway import LLMGateway
    from app.tools.llm.mock_provider import MockProvider

    context = AgentContext(
        project_id="mock-security",
        project={"name": "Security test"},
        stage="DEVELOPMENT",
        source_files={"backend/app/config.py": "SECRET = 'weak'\n"},
        security_summary={
            "top_findings": [
                {
                    "rule_id": "SEC-UNKNOWN",
                    "severity": "HIGH",
                    "title": "Unrecognized security issue",
                    "file_path": "backend/app/config.py",
                    "line": 1,
                }
            ]
        },
    )
    agent = DeveloperAgent(LLMGateway(MockProvider(), mode="mock"))

    payload = agent.mock_payload(context, "Remediate the Security Agent findings.")

    assert payload["changes"] == []
    assert "SEC-UNKNOWN" in payload["analysis"]
    assert "No security finding is claimed to be fixed." in payload["notes"]


def test_workflow_completes_with_six_human_gates(client, auth, project, completed_run):
    assert completed_run["status"] == "COMPLETED"
    assert completed_run["engine"] == "langgraph"
    assert completed_run["total_steps"] >= 6
    iterations = completed_run["stage_iterations"]
    for stage in ("REQUIREMENTS", "ARCHITECTURE", "DEVELOPMENT", "TESTING", "SECURITY",
                  "DOCUMENTATION"):
        assert iterations.get(stage, 0) >= 1, f"{stage} never ran"


def test_every_stage_artifact_exists_and_is_approved(client, auth, project, completed_run):
    artifacts = client.get(f"/api/projects/{project['id']}/artifacts", headers=auth).json()
    types = {item["type"] for item in artifacts}
    for expected in ("REQUIREMENTS", "ARCHITECTURE", "CHANGE_SET", "TEST_PLAN", "TEST_RESULTS",
                     "SECURITY_REPORT", "DOCUMENTATION"):
        assert expected in types, f"missing artifact {expected}"
    assert all(item["status"] != "REJECTED" for item in artifacts)
    approved = [item for item in artifacts if item["status"] == "APPROVED"]
    assert len(approved) >= 5


def test_workflow_overview_reports_stage_progress(client, auth, project, completed_run):
    overview = client.get(f"/api/projects/{project['id']}/workflow", headers=auth).json()
    statuses = {stage["stage"]: stage["status"] for stage in overview["stages"]}
    for stage in ("REQUIREMENTS", "ARCHITECTURE", "DEVELOPMENT", "TESTING", "SECURITY",
                  "DOCUMENTATION"):
        assert statuses[stage] == "COMPLETED", (stage, statuses)
    assert overview["pending_approval"] is None
    assert overview["can_resume"] is False
    assert overview["iteration_budget"]["max_stage_iterations"] >= 1


def test_steps_are_recorded_for_audit(client, auth, project, completed_run):
    steps = client.get(
        f"/api/projects/{project['id']}/workflow/runs/{completed_run['id']}/steps",
        headers=auth).json()
    assert len(steps) >= 6
    assert steps[0]["step_index"] == 1


def test_approval_history_is_complete_and_attributed(client, auth, project, completed_run):
    approvals = client.get(f"/api/projects/{project['id']}/approvals", headers=auth).json()
    workflow_gates = {"requirements_approval", "architecture_approval", "code_review",
                      "test_review", "security_review", "documentation_approval"}
    assert workflow_gates <= {item["gate"] for item in approvals}
    stage_gates = [item for item in approvals if item["gate"] in workflow_gates]
    assert stage_gates
    assert all(item["status"] == "APPROVED" for item in stage_gates)
    assert all(item["decided_by_user_id"] for item in stage_gates)
    assert all(item["decided_at"] for item in stage_gates)
    assert all(item["artifact_title"] for item in stage_gates)


def test_regenerated_project_contains_tests_and_docs(client, auth, project, completed_run):
    tree = client.get(f"/api/projects/{project['id']}/workspace", headers=auth).json()
    paths = {item["path"] for group in tree["groups"].values() for item in group}
    assert "README.md" in paths
    assert "backend/app/main.py" in paths
    assert "backend/tests/test_tasks_api.py" in paths
    assert "tests/test_plan.md" in paths
    assert "security/security_report.md" in paths
    assert "documentation/INDEX.md" in paths


def test_workspace_file_can_be_read(client, auth, project, completed_run):
    response = client.get(f"/api/projects/{project['id']}/workspace/file", headers=auth,
                          params={"path": "README.md"})
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "markdown"
    assert "DevForge" in body["content"] or "Student Task" in body["content"]


def test_workspace_path_traversal_is_refused(client, auth, project, completed_run):
    response = client.get(f"/api/projects/{project['id']}/workspace/file", headers=auth,
                          params={"path": "../../../../etc/passwd"})
    assert response.status_code in {400, 404, 422}
