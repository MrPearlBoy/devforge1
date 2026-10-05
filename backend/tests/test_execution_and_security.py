"""Sandboxed test execution, security findings and the traceability matrix."""
from __future__ import annotations


def test_latest_test_run_contains_results(client, auth, project, completed_run):
    run = client.get(f"/api/projects/{project['id']}/tests/latest", headers=auth).json()
    assert run is not None
    assert run["status"] == "PASSED", run.get("report", {}).get("raw_output", "")[:400]
    assert run["total"] >= 5
    assert run["passed"] == run["total"]
    assert run["provider"]  # the sandbox provider that executed the suite
    assert len(run["results"]) == run["total"]
    assert all(item["name"] for item in run["results"])


def test_manual_test_run_executes_in_the_sandbox(client, auth, project, completed_run):
    response = client.post(f"/api/projects/{project['id']}/tests/run", headers=auth,
                           json={"confirm_execution": True})
    assert response.status_code == 200, response.text
    assert response.json()["triggered_by"] == "MANUAL"
    assert response.json()["status"] == "PASSED"


def test_test_execution_requires_confirmation(client, auth, project):
    response = client.post(f"/api/projects/{project['id']}/tests/run", headers=auth,
                           json={"confirm_execution": False})
    assert response.status_code == 422


def test_run_history_is_kept(client, auth, project, completed_run):
    runs = client.get(f"/api/projects/{project['id']}/tests", headers=auth).json()
    assert len(runs) >= 1
    detail = client.get(f"/api/tests/{runs[0]['id']}", headers=auth).json()
    assert detail["id"] == runs[0]["id"]


def test_security_scan_produced_findings_and_summary(client, auth, project, completed_run):
    summary = client.get(f"/api/projects/{project['id']}/security/summary", headers=auth).json()
    assert summary["files_scanned"] > 0
    assert summary["artifact_id"]
    assert "not replace" in summary["disclaimer"].lower()

    findings = client.get(f"/api/projects/{project['id']}/security/findings",
                          headers=auth).json()
    assert findings, "the seeded project should produce at least one finding"
    for finding in findings:
        assert finding["severity"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
        assert finding["rule_id"] and finding["recommendation"]


def test_finding_triage_and_filtering(client, auth, project, completed_run):
    findings = client.get(f"/api/projects/{project['id']}/security/findings",
                          headers=auth).json()
    target = findings[0]
    updated = client.patch(f"/api/security/findings/{target['id']}", headers=auth,
                           json={"status": "FALSE_POSITIVE", "comment": "Demo only."})
    assert updated.status_code == 200
    assert updated.json()["status"] == "FALSE_POSITIVE"
    assert client.patch(f"/api/security/findings/{target['id']}", headers=auth,
                        json={"status": "NONSENSE"}).status_code == 422


def test_sandbox_refuses_commands_outside_the_allow_list(client, auth, project):
    response = client.post(f"/api/projects/{project['id']}/sandbox/run", headers=auth,
                           json={"command": "curl", "args": ["http://example.com"],
                                 "confirm_execution": True})
    assert response.status_code == 422
    assert "allow-list" in response.json()["error"]["message"] or \
           "allow" in str(response.json()).lower()


def test_sandbox_refuses_shell_metacharacters(client, auth, project):
    response = client.post(f"/api/projects/{project['id']}/sandbox/run", headers=auth,
                           json={"command": "python", "args": ["-c", "print(1); rm -rf /"],
                                 "confirm_execution": True})
    assert response.status_code == 422


def test_sandbox_info_documents_limits(client, auth, project):
    info = client.get(f"/api/projects/{project['id']}/sandbox", headers=auth).json()
    assert info["provider"] in {"subprocess", "docker"}
    assert info["limits"]["timeout_seconds"] > 0
    assert "pytest" in info["allowed_commands"]


def test_traceability_matrix_covers_the_sdlc(client, auth, project, completed_run):
    matrix = client.get(f"/api/projects/{project['id']}/trace", headers=auth).json()
    node_types = {node["type"] for node in matrix["nodes"]}
    assert {"REQUIREMENT", "ARCHITECTURE", "CODE", "TEST", "SECURITY", "DOCUMENTATION"} <= node_types
    coverage = matrix["coverage"]
    assert coverage["requirements"] > 0
    assert coverage["with_architecture"] == coverage["requirements"]
    assert coverage["percent"]["with_architecture"] == 100
    assert coverage["percent"]["with_code"] > 0
    assert isinstance(matrix["gap_report"], list)


def test_trace_chain_and_coverage_endpoints(client, auth, project, completed_run):
    chain = client.get(f"/api/projects/{project['id']}/trace/ref/REQ-001", headers=auth)
    assert chain.status_code == 200
    assert chain.json()["root"]["ref"] == "REQ-001"
    assert chain.json()["links"]

    coverage = client.get(f"/api/projects/{project['id']}/trace/coverage", headers=auth).json()
    assert "percent" in coverage["coverage"]

    assert client.get(f"/api/projects/{project['id']}/trace/ref/REQ-999",
                      headers=auth).status_code == 404


def test_audit_trail_records_the_full_lifecycle(client, auth, project, completed_run):
    activity = client.get(f"/api/projects/{project['id']}/activity", headers=auth).json()
    actions = {item["action"] for item in activity}
    for expected in ("workflow.started", "approval.approved", "code.changes_applied",
                     "tests.executed", "security.scan_completed"):
        assert expected in actions, (expected, sorted(actions))
    assert all(item["created_at"] for item in activity)

    summary = client.get(f"/api/projects/{project['id']}/activity/summary",
                         headers=auth).json()
    assert summary["total"] >= len(activity) > 0
