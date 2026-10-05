"""Agent catalogue, executions, chat and the change-set approval rule."""
from __future__ import annotations

AGENT_KEYS = {"requirement", "architecture", "developer", "testing", "security", "documentation"}


def test_agent_catalogue_is_seeded(client, auth):
    agents = client.get("/api/agents", headers=auth).json()
    assert {agent["key"] for agent in agents} == AGENT_KEYS
    assert all(agent["is_active"] for agent in agents)


def test_agent_specs_describe_capabilities(client):
    specs = client.get("/api/agents/specs").json()
    assert len(specs) == 6
    assert all(spec["capabilities"] and spec["description"] for spec in specs)


def test_agent_status_reports_completed_executions(client, auth, project, completed_run):
    statuses = client.get(f"/api/projects/{project['id']}/agents/status", headers=auth).json()
    by_key = {item["agent_key"]: item for item in statuses}
    assert set(by_key) == AGENT_KEYS
    for key in AGENT_KEYS:
        assert by_key[key]["status"] == "SUCCEEDED", (key, by_key[key]["status"])
        assert by_key[key]["mode"] == "mock"
        assert by_key[key]["execution_id"]


def test_execution_log_records_every_agent(client, auth, project, completed_run):
    executions = client.get(f"/api/projects/{project['id']}/executions", headers=auth).json()
    assert {item["agent_key"] for item in executions} >= AGENT_KEYS
    assert all(item["duration_ms"] >= 0 for item in executions)
    assert all(item["trigger"] == "WORKFLOW" for item in executions)


def test_chat_reply_and_code_proposal_gate(client, auth, project, completed_run):
    response = client.post(f"/api/projects/{project['id']}/chat", headers=auth, json={
        "agent_key": "developer",
        "message": "Add a priority field to tasks and let users filter by it.",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"]
    assert body["mode"] == "mock"

    history = client.get(f"/api/projects/{project['id']}/chat", headers=auth,
                         params={"thread_id": "default"}).json()
    assert len(history) >= 2  # the human turn and the agent turn
    assert {item["role"] for item in history} == {"USER", "AGENT"}

    if body["proposed_changes"]:
        assert body["approval_id"], "a code proposal must open an approval gate"
        pending = client.get(f"/api/projects/{project['id']}/approvals/pending",
                             headers=auth).json()
        assert any(item["id"] == body["approval_id"] for item in pending)
        assert pending[0]["gate"] == "chat_change_request"
        decided = client.post(f"/api/approvals/{body['approval_id']}/changes", headers=auth,
                              json={"comments": "Not now, keep it for the next iteration."})
        assert decided.status_code == 200
        assert decided.json()["status"] == "CHANGES_REQUESTED"


def test_chat_rejects_unknown_agent(client, auth, project):
    response = client.post(f"/api/projects/{project['id']}/chat", headers=auth, json={
        "agent_key": "wizard", "message": "hello"})
    assert response.status_code == 422


def test_chat_requires_a_message(client, auth, project):
    assert client.post(f"/api/projects/{project['id']}/chat", headers=auth,
                       json={"message": ""}).status_code == 422


def test_action_labels_endpoint(client):
    labels = client.get("/api/activity/labels").json()
    assert labels["approval.approved"]
    assert labels["code.changes_applied"]
