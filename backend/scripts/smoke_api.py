"""End-to-end API smoke test.

Boots the FastAPI application with an isolated SQLite database and a temporary
workspace, then walks the whole platform through the real HTTP surface:

    register → login → create project → start workflow → approve every gate
    → inspect agents / artifacts / tests / security / trace / activity
    → chat with an agent → check delivery readiness

Run from ``backend/``::

    python scripts/smoke_api.py

Exits non-zero on the first failing assertion so it can gate CI.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP = tempfile.mkdtemp(prefix="devforge-api-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP}/api.db")
os.environ.setdefault("WORKSPACE_ROOT", f"{TMP}/workspace")
os.environ.setdefault("CHECKPOINT_PATH", f"{TMP}/checkpoints.sqlite")
os.environ.setdefault("SECRET_KEY", "api-smoke-secret-0123456789abcdefghij")
os.environ.setdefault("DEVFORGE_MODE", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

REQUIREMENT = (
    "Build a web application where students can create tasks, update tasks, delete tasks "
    "and mark tasks as completed. Students should also be able to view their pending tasks "
    "and filter them by deadline. An administrator must be able to view all users and remove "
    "inactive accounts."
)

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}{f' — {extra}' if extra else ''}")


def main() -> int:
    app = create_app()
    with TestClient(app) as client:
        print("\n=== platform ===")
        health = client.get("/api/health")
        check("GET /api/health", health.status_code == 200 and health.json()["status"] == "ok",
              str(health.json().get("ai", {})))
        config = client.get("/api/config").json()
        check("mock mode is reported to the UI", config["mock_mode"] is True
              and config["mode"] == "mock", f"provider={config['provider']}")

        print("\n=== auth ===")
        register = client.post("/api/auth/register", json={
            "email": "student@devforge.dev", "password": "password123",
            "full_name": "Final Year Student",
        })
        check("POST /api/auth/register -> 201", register.status_code == 201,
              str(register.status_code))
        token = register.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        duplicate = client.post("/api/auth/register", json={
            "email": "student@devforge.dev", "password": "password123"})
        check("duplicate registration -> 409", duplicate.status_code == 409)

        bad_login = client.post("/api/auth/login", json={
            "email": "student@devforge.dev", "password": "wrong-password"})
        check("wrong password -> 401", bad_login.status_code == 401)

        login = client.post("/api/auth/login", json={
            "email": "student@devforge.dev", "password": "password123"})
        check("POST /api/auth/login", login.status_code == 200)
        check("GET /api/auth/me", client.get("/api/auth/me", headers=headers).status_code == 200)
        check("unauthenticated project list -> 401",
              client.get("/api/projects").status_code == 401)

        print("\n=== project ===")
        created = client.post("/api/projects", headers=headers, json={
            "name": "Student Task Management System",
            "description": "Coursework tracker used as the DevForge demo scenario.",
            "requirement_input": REQUIREMENT,
            "tags": ["demo", "education"],
        })
        check("POST /api/projects -> 201", created.status_code == 201, str(created.status_code))
        project = created.json()
        project_id = project["id"]
        check("slug derived from the name", project["slug"].startswith("student-task"))
        check("GET /api/projects lists it",
              any(item["id"] == project_id for item in
                  client.get("/api/projects", headers=headers).json()))

        dashboard = client.get(f"/api/projects/{project_id}/dashboard", headers=headers)
        check("dashboard responds", dashboard.status_code == 200)
        check("dashboard lists the six stages plus delivery",
              len(dashboard.json()["stages"]) == 7, str(len(dashboard.json()["stages"])))

        print("\n=== agents ===")
        agents = client.get("/api/agents", headers=headers).json()
        check("six agents in the catalogue", len(agents) == 6, str(len(agents)))
        check("agent specs endpoint", len(client.get("/api/agents/specs", headers=headers).json()) == 6)

        print("\n=== workflow ===")
        started = client.post(f"/api/projects/{project_id}/workflow/start", headers=headers,
                              json={"instructions": "Keep the demo small and reviewable."})
        check("POST workflow/start", started.status_code == 200, str(started.status_code))
        run_id = started.json()["id"]

        gates_approved = 0
        chat_proposal_checked = False
        deadline = time.time() + 600
        while time.time() < deadline:
            overview = client.get(f"/api/projects/{project_id}/workflow", headers=headers).json()
            status = (overview.get("run") or {}).get("status", "")
            if status in {"COMPLETED", "FAILED"}:
                break
            pending = overview.get("pending_approval")
            if pending:
                stage = pending["stage"]
                decision = "approve"
                body = {"comments": f"Approved {stage} after review.", "instructions": ""}
                if stage == "TESTING" and not chat_proposal_checked:
                    # Talk to the Developer Agent first: a chat proposal must open its own gate.
                    chat = client.post(f"/api/projects/{project_id}/chat", headers=headers, json={
                        "agent_key": "developer",
                        "message": "Add a priority field to tasks and a filter for it.",
                        "allow_code_proposals": True,
                    })
                    if chat.status_code == 200:
                        payload = chat.json()
                        check("chat reply received", bool(payload["content"]))
                        if payload["proposed_changes"]:
                            check("chat proposal opened an approval gate",
                                  bool(payload["approval_id"]))
                            client.post(f"/api/approvals/{payload['approval_id']}/changes",
                                        headers=headers,
                                        json={"comments": "Hold this for the next iteration.",
                                              "instructions": ""})
                        chat_proposal_checked = True

                response = client.post(f"/api/approvals/{pending['id']}/{decision}",
                                       headers=headers, json=body)
                if response.status_code != 200:
                    print(f"    approval failed: {response.status_code} {response.text[:300]}")
                    break
                gates_approved += 1
                print(f"    approved gate {gates_approved}: {stage}")
            else:
                time.sleep(0.4)

        final = client.get(f"/api/projects/{project_id}/workflow", headers=headers).json()
        run = final.get("run") or {}
        check("workflow reached COMPLETED", run.get("status") == "COMPLETED",
              f"status={run.get('status')} error={run.get('last_error', '')[:160]}")
        check("six human gates were approved", gates_approved >= 6, f"{gates_approved} gates")
        check("stage iterations recorded", bool(run.get("stage_iterations")),
              str(run.get("stage_iterations")))
        check("run steps recorded",
              len(client.get(f"/api/projects/{project_id}/workflow/runs/{run_id}/steps",
                             headers=headers).json()) > 0)

        print("\n=== artifacts & workspace ===")
        artifacts = client.get(f"/api/projects/{project_id}/artifacts", headers=headers).json()
        types = {item["type"] for item in artifacts}
        for expected in ("REQUIREMENTS", "ARCHITECTURE", "CHANGE_SET", "TEST_PLAN",
                         "TEST_RESULTS", "SECURITY_REPORT", "DOCUMENTATION"):
            check(f"artifact produced: {expected}", expected in types)
        if artifacts:
            detail = client.get(f"/api/artifacts/{artifacts[0]['id']}", headers=headers)
            check("artifact detail readable", detail.status_code == 200
                  and bool(detail.json()["content"]))
        tree = client.get(f"/api/projects/{project_id}/workspace", headers=headers).json()
        files = [item for group in tree["groups"].values() for item in group]
        check("workspace has generated files", len(files) > 10, f"{len(files)} files")
        readme = next((item for item in files if item["path"] == "README.md"), None)
        if readme:
            content = client.get(f"/api/projects/{project_id}/workspace/file", headers=headers,
                                 params={"path": "README.md"})
            check("workspace file content", content.status_code == 200
                  and len(content.json()["content"]) > 100)

        print("\n=== tests & security ===")
        latest = client.get(f"/api/projects/{project_id}/tests/latest", headers=headers).json()
        check("latest test run present", bool(latest), str((latest or {}).get("status")))
        if latest:
            check("test run passed", latest["status"] == "PASSED",
                  f"{latest['passed']}/{latest['total']}")
            check("per-test results stored", len(latest["results"]) >= 5,
                  f"{len(latest['results'])} results")
        reruns = client.get(f"/api/projects/{project_id}/tests", headers=headers).json()
        check("test run history", len(reruns) >= 1, f"{len(reruns)} run(s)")
        summary = client.get(f"/api/projects/{project_id}/security/summary",
                             headers=headers).json()
        check("security summary present", summary["files_scanned"] > 0,
              f"{summary['files_scanned']} files, {summary['open_total']} open findings")
        findings = client.get(f"/api/projects/{project_id}/security/findings",
                              headers=headers).json()
        check("security findings stored", len(findings) > 0, f"{len(findings)} finding(s)")
        if findings:
            triage = client.patch(f"/api/security/findings/{findings[0]['id']}",
                                  headers=headers,
                                  json={"status": "ACKNOWLEDGED", "comment": "Triaged in smoke test"})
            check("finding triage works", triage.status_code == 200
                  and triage.json()["status"] == "ACKNOWLEDGED")
        sandbox = client.get(f"/api/projects/{project_id}/sandbox", headers=headers).json()
        check("sandbox limits exposed", bool(sandbox["allowed_commands"])
              and sandbox["limits"]["timeout_seconds"] > 0, sandbox["provider"])

        print("\n=== traceability ===")
        matrix = client.get(f"/api/projects/{project_id}/trace", headers=headers).json()
        check("trace matrix has nodes", len(matrix["nodes"]) > 20, f"{len(matrix['nodes'])} nodes")
        check("trace matrix has links", len(matrix["links"]) > 20, f"{len(matrix['links'])} links")
        coverage = matrix["coverage"].get("percent", {})
        check("requirements fully traced to architecture",
              coverage.get("with_architecture", 0) == 100, str(coverage))
        check("gap report available", isinstance(matrix["gap_report"], list),
              f"{len(matrix['gap_report'])} gap(s)")
        chain = client.get(f"/api/projects/{project_id}/trace/ref/REQ-001", headers=headers)
        check("REQ-001 chain resolves", chain.status_code == 200,
              f"{len(chain.json().get('links', [])) if chain.status_code == 200 else ''} links")

        print("\n=== activity ===")
        activity = client.get(f"/api/projects/{project_id}/activity", headers=headers).json()
        actions = {item["action"] for item in activity}
        for expected in ("workflow.started", "approval.approved", "code.changes_applied"):
            check(f"audit trail records {expected}", expected in actions)
        summary_activity = client.get(f"/api/projects/{project_id}/activity/summary",
                                      headers=headers).json()
        check("activity summary counts", summary_activity["total"] >= len(activity) > 0,
              f"{summary_activity['total']} entries")

        print("\n=== approvals ===")
        approvals = client.get(f"/api/projects/{project_id}/approvals", headers=headers).json()
        check("approval history kept (all decided)",
              len(approvals) >= 6 and all(item["status"] != "PENDING" for item in approvals),
              f"{len(approvals)} approvals")
        check("approvals record the deciding user",
              all(item["decided_by_user_id"] for item in approvals))

        print("\n=== github / delivery ===")
        status = client.get(f"/api/projects/{project_id}/repository", headers=headers).json()
        check("repository status endpoint", status["connected"] is False)
        connect = client.post(f"/api/projects/{project_id}/repository", headers=headers, json={
            "url": "https://github.com/devforge-demo/student-task-management.git",
            "token": "ghp_demo_token_not_real", "clone": False,
        })
        check("repository connect stores no plaintext token",
              connect.status_code == 200
              and connect.json()["auth_configured"] is True
              and "token" not in connect.json(), str(connect.status_code))
        init = client.post(f"/api/projects/{project_id}/repository/init", headers=headers)
        check("local git repository initialised", init.status_code == 200, str(init.status_code))
        plan = client.get(f"/api/projects/{project_id}/repository/plan", headers=headers).json()
        check("sync plan requires confirmation", plan["requires_confirmation"] is True
              and len(plan["files"]) >= 3, f"{len(plan['files'])} files")
        unconfirmed = client.post(f"/api/projects/{project_id}/repository/push", headers=headers,
                                  json={"confirm": False})
        check("push without confirmation refused", unconfirmed.status_code == 422,
              str(unconfirmed.status_code))
        commit = client.post(f"/api/projects/{project_id}/repository/commit", headers=headers,
                             json={"message": "feat: generate the student task system",
                                   "confirm": True})
        check("confirmed commit succeeds", commit.status_code == 200,
              str(commit.json() if commit.status_code != 200 else commit.json().get("sha", "")[:10]))
        operations = client.get(f"/api/projects/{project_id}/repository/operations",
                                headers=headers).json()
        check("git operations logged with human confirmation",
              any(item["confirmed_by_user"] for item in operations))
        readiness = client.get(f"/api/projects/{project_id}/repository/delivery",
                               headers=headers).json()
        outstanding = [item["item"] for item in readiness["checklist"] if not item["done"]]
        check("delivery checklist produced", len(readiness["checklist"]) >= 6
              and readiness["ready"] is True,
              readiness["message"] + (f" | outstanding: {outstanding}" if outstanding else ""))

        print("\n=== events ===")
        events = client.get(f"/api/projects/{project_id}/events/recent", headers=headers).json()
        check("recent events available", len(events) > 0, f"{len(events)} event(s)")

    print("\n================ SUMMARY ================")
    print(f"checks passed: {len(PASSED)}")
    if FAILED:
        print(f"checks FAILED: {len(FAILED)}")
        for item in FAILED:
            print(f"  - {item}")
    print("API RESULT:", "OK" if not FAILED else "FAILED")
    return 0 if not FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
