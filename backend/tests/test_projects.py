"""Project CRUD, ownership boundaries and the dashboard payload."""
from __future__ import annotations


def test_create_project_derives_slug_and_stages(client, auth):
    response = client.post("/api/projects", headers=auth, json={
        "name": "Inventory Tracker!",
        "description": "Warehouse stock movements.",
        "requirement_input": "Track stock in and out of the warehouse with a simple API.",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "inventory-tracker"
    assert body["current_stage"] == "REQUIREMENTS"
    assert body["workflow_status"] == "NOT_STARTED"
    assert body["progress_percent"] == 0


def test_project_crud_round_trip(client, auth, project):
    listed = client.get("/api/projects", headers=auth).json()
    assert any(item["id"] == project["id"] for item in listed)
    summary = next(item for item in listed if item["id"] == project["id"])
    assert summary["owner_name"]
    assert "pending_approvals" in summary and "open_findings" in summary

    updated = client.put(f"/api/projects/{project['id']}", headers=auth,
                         json={"description": "Updated description.", "tags": ["demo", "qa"]})
    assert updated.status_code == 200
    assert updated.json()["description"] == "Updated description."
    assert updated.json()["tags"] == ["demo", "qa"]

    detail = client.get(f"/api/projects/{project['id']}", headers=auth)
    assert detail.status_code == 200
    assert detail.json()["requirement_input"]


def test_other_users_cannot_reach_a_project(client, other_auth, project):
    assert client.get(f"/api/projects/{project['id']}", headers=other_auth).status_code == 403
    assert client.delete(f"/api/projects/{project['id']}", headers=other_auth).status_code == 403
    assert client.get(f"/api/projects/{project['id']}/artifacts",
                      headers=other_auth).status_code == 403


def test_dashboard_payload_shape(client, auth, project):
    body = client.get(f"/api/projects/{project['id']}/dashboard", headers=auth).json()
    assert {stage["stage"] for stage in body["stages"]} >= {
        "REQUIREMENTS", "ARCHITECTURE", "DEVELOPMENT", "TESTING", "SECURITY", "DOCUMENTATION",
    }
    assert "project" in body and body["project"]["id"] == project["id"]
    assert "ai_config" in body and body["ai_config"]["mode"] == "live"
    assert isinstance(body["agent_activity"], list)


def test_tasks_are_human_editable(client, auth, project):
    created = client.post(f"/api/projects/{project['id']}/tasks", headers=auth, json={
        "title": "Write the viva slides", "description": "20 minutes, six agents.",
        "priority": "HIGH",
    })
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["source"] == "HUMAN"

    patched = client.patch(f"/api/projects/{project['id']}/tasks/{task_id}", headers=auth,
                           json={"status": "DONE"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "DONE"

    tasks = client.get(f"/api/projects/{project['id']}/tasks", headers=auth).json()
    assert any(item["id"] == task_id for item in tasks)


def test_project_validation(client, auth):
    assert client.post("/api/projects", headers=auth, json={"name": "x"}).status_code == 422
    assert client.get("/api/projects/00000000-0000-0000-0000-000000000000",
                      headers=auth).status_code == 404
