"""Shared pytest fixtures.

The suite runs against an isolated SQLite database and a temporary workspace, in mock
mode, so it never touches development data or an LLM provider.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP_ROOT = Path(tempfile.mkdtemp(prefix="devforge-tests-"))

os.environ["DATABASE_URL"] = f"sqlite:///{TMP_ROOT}/tests.db"
os.environ["WORKSPACE_ROOT"] = str(TMP_ROOT / "workspace")
os.environ["CHECKPOINT_PATH"] = str(TMP_ROOT / "checkpoints.sqlite")
os.environ["CHECKPOINT_BACKEND"] = "memory"
os.environ["SECRET_KEY"] = "test-secret-key-0123456789abcdefghijklmnop"
os.environ["DEVFORGE_MODE"] = "mock"
os.environ["EXECUTION_PROVIDER"] = "subprocess"
os.environ["AUTO_CREATE_SCHEMA"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import init_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.agent_registry import seed_agent_catalog  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402

REQUIREMENT = (
    "Build a web application where students can create tasks, update tasks, delete tasks and "
    "mark tasks as completed. Students should also be able to view their pending tasks and "
    "filter them by deadline. An administrator must be able to view all users and remove "
    "inactive accounts."
)


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    init_db()
    with SessionLocal() as db:
        seed_agent_catalog(db)


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def _register(client: TestClient, email: str) -> tuple[dict, dict]:
    response = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "full_name": email.split("@")[0].title(),
    })
    if response.status_code == 409:  # already registered by another test module
        response = client.post("/api/auth/login", json={
            "email": email, "password": "password123"})
        assert response.status_code == 200, response.text
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, response.json()["user"]


@pytest.fixture(scope="session")
def auth(client) -> dict:
    """Bearer headers for the project owner."""
    headers, _user = _register(client, "owner@example.com")
    return headers


@pytest.fixture(scope="session")
def other_auth(client) -> dict:
    headers, _user = _register(client, "stranger@example.com")
    return headers


@pytest.fixture(scope="session")
def account(client) -> dict:
    """The seeded owner account (email + profile)."""
    response = client.post("/api/auth/login", json={
        "email": "owner@example.com", "password": "password123"})
    return response.json()["user"]


@pytest.fixture(scope="session")
def project(client, auth) -> dict:
    response = client.post("/api/projects", headers=auth, json={
        "name": "Student Task Management System",
        "description": "Coursework tracker (test fixture).",
        "requirement_input": REQUIREMENT,
        "tags": ["test"],
    })
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="session")
def completed_run(client, auth, project) -> dict:
    """Drive the whole workflow once; later tests inspect the resulting state."""
    import time

    START_TIMEOUT = 300
    response = client.post(f"/api/projects/{project['id']}/workflow/start", headers=auth,
                           json={"instructions": "Test fixture run."})
    assert response.status_code == 200, response.text
    run_id = response.json()["id"]

    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        overview = client.get(f"/api/projects/{project['id']}/workflow",
                              headers=auth).json()
        status = (overview.get("run") or {}).get("status")
        if status in {"COMPLETED", "FAILED"}:
            break
        pending = overview.get("pending_approval")
        if pending:
            client.post(f"/api/approvals/{pending['id']}/approve", headers=auth,
                        json={"comments": "Approved by the test suite."})
        else:
            time.sleep(0.3)

    overview = client.get(f"/api/projects/{project['id']}/workflow", headers=auth).json()
    assert (overview.get("run") or {}).get("status") == "COMPLETED", overview
    return overview["run"]
