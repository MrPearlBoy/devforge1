"""Authentication and authorisation behaviour."""
from __future__ import annotations


def test_health_reports_mock_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ai"]["mode"] == "mock"
    assert body["database"]["connected"] is True


def test_config_endpoint_exposes_ai_and_sandbox_settings(client):
    body = client.get("/api/config").json()
    assert body["mock_mode"] is True
    assert body["execution_enabled"] is True
    assert body["max_stage_iterations"] >= 1


def test_register_returns_token_and_profile(client):
    response = client.post("/api/auth/register", json={
        "email": "signup-user@example.com", "password": "password123", "full_name": "Sign Up",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "signup-user@example.com"
    assert "password" not in body["user"]


def test_register_rejects_duplicate_email(client, auth):
    response = client.post("/api/auth/register", json={
        "email": "owner@example.com", "password": "password123"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_register_rejects_short_password(client):
    response = client.post("/api/auth/register", json={
        "email": "short@example.com", "password": "short"})
    assert response.status_code == 422


def test_login_success_and_failure(client, auth):
    ok = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "password123"})
    assert ok.status_code == 200
    bad = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "not-the-password"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={
        "email": "nobody@example.com", "password": "password123"})
    assert unknown.status_code == 401  # identical message: no account enumeration


def test_me_requires_token(client, auth):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    me = client.get("/api/auth/me", headers=auth)
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"


def test_projects_require_authentication(client):
    assert client.get("/api/projects").status_code == 401
    assert client.post("/api/projects", json={"name": "Nope"}).status_code == 401
