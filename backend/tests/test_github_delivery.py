"""GitHub integration: token handling, the confirmation rule and delivery readiness."""
from __future__ import annotations

REPO_URL = "https://github.com/devforge-demo/student-task-management.git"


def test_repository_status_before_connecting(client, auth, project):
    status = client.get(f"/api/projects/{project['id']}/repository", headers=auth).json()
    assert status["connected"] is False
    assert status["requires_confirmation"] is True


def test_connect_never_returns_the_token(client, auth, project):
    response = client.post(f"/api/projects/{project['id']}/repository", headers=auth, json={
        "url": REPO_URL, "token": "ghp_this_is_not_a_real_token", "clone": False,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["auth_configured"] is True
    assert body["owner"] == "devforge-demo"
    assert body["name"] == "student-task-management"
    assert "token" not in body and "token_encrypted" not in body
    assert body["working_branch"].startswith("devforge/")


def test_connect_validates_the_url(client, auth, project):
    bad = client.post(f"/api/projects/{project['id']}/repository", headers=auth,
                      json={"url": "https://gitlab.com/owner/repo.git", "clone": False})
    assert bad.status_code == 422


def test_local_repository_init_and_status(client, auth, project):
    assert client.post(f"/api/projects/{project['id']}/repository/init",
                       headers=auth).status_code == 200
    status = client.get(f"/api/projects/{project['id']}/repository", headers=auth).json()
    assert status["connected"] is True
    assert status["branch"]


def test_sync_plan_describes_the_change_without_acting(client, auth, project):
    plan = client.get(f"/api/projects/{project['id']}/repository/plan", headers=auth).json()
    assert plan["requires_confirmation"] is True
    assert plan["commit_message"]
    assert len(plan["files"]) >= 3
    assert any(item["path"].endswith("README.md") for item in plan["files"])


def test_remote_writes_require_explicit_confirmation(client, auth, project):
    unconfirmed_push = client.post(f"/api/projects/{project['id']}/repository/push",
                                   headers=auth, json={"confirm": False})
    assert unconfirmed_push.status_code == 422
    unconfirmed_commit = client.post(f"/api/projects/{project['id']}/repository/commit",
                                     headers=auth, json={
                                         "message": "should not happen", "confirm": False})
    assert unconfirmed_commit.status_code == 422

    operations = client.get(f"/api/projects/{project['id']}/repository/operations",
                            headers=auth).json()
    assert all(item["confirmed_by_user"] for item in operations), "every remote write is confirmed"
    assert not any(item["operation"] == "PUSH" for item in operations)


def test_confirmed_commit_creates_a_commit_and_an_audit_entry(client, auth, project):
    response = client.post(f"/api/projects/{project['id']}/repository/commit", headers=auth,
                           json={"message": "feat: add the generated student task system",
                                 "confirm": True})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha"] and len(body["sha"]) >= 7
    assert body["files"] > 0

    commits = client.get(f"/api/projects/{project['id']}/repository/commits",
                         headers=auth).json()
    assert commits and commits[0]["sha"].startswith(body["sha"][:7])

    activity = client.get(f"/api/projects/{project['id']}/activity", headers=auth).json()
    assert any(item["action"] == "github.committed" for item in activity)


def test_delivery_readiness_reflects_the_checklist(client, auth, project, completed_run):
    body = client.get(f"/api/projects/{project['id']}/repository/delivery", headers=auth).json()
    assert len(body["checklist"]) >= 6
    assert body["repository"]["url"] == REPO_URL
    assert body["branch"]
    assert body["changed_files"] >= 0
    done = {item["item"] for item in body["checklist"] if item["done"]}
    assert "Requirement and architecture approved" in done
    assert "Documentation generated" in done
    if body["ready"]:
        assert body["message"].startswith("Everything is approved")
    else:
        assert any(not item["done"] for item in body["checklist"])


def test_disconnect_keeps_the_workspace(client, auth, project):
    response = client.delete(f"/api/projects/{project['id']}/repository", headers=auth)
    assert response.status_code == 200
    status = client.get(f"/api/projects/{project['id']}/repository", headers=auth).json()
    assert status["connected"] is False
    tree = client.get(f"/api/projects/{project['id']}/workspace", headers=auth).json()
    assert tree["total_files"] > 0
