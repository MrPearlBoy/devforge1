"""Smoke test: run the Requirement Agent end-to-end in mock mode.

Creates a throwaway SQLite database, a user and a project, then executes the
agent through the runtime exactly as the workflow would.

Usage:  python scripts/smoke_requirement_agent.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP = tempfile.mkdtemp(prefix="devforge-smoke-")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP}/smoke.db"
os.environ["WORKSPACE_ROOT"] = f"{TMP}/workspace"
os.environ["DEVFORGE_MODE"] = "mock"
os.environ["SECRET_KEY"] = "smoke-test-secret-key-0123456789abcdef"

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.enums import ExecutionTrigger  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent_registry import seed_agent_catalog  # noqa: E402
from app.services.agent_runtime import AgentRunRequest, AgentRuntime  # noqa: E402
from app.services.workspace import WorkspaceService  # noqa: E402

REQUIREMENT = (
    "Build a web application where students can create tasks, update tasks, "
    "delete tasks and mark tasks as completed. Students should also be able to "
    "view their pending tasks and filter them by deadline. An administrator must "
    "be able to view all users and remove inactive accounts."
)


def main() -> int:
    init_db()
    db = SessionLocal()
    seed_agent_catalog(db)

    user = User(email="smoke@devforge.test", full_name="Smoke Tester",
                hashed_password=hash_password("password123"))
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = WorkspaceService()
    project = Project(
        name="Student Task Management System",
        description="Track student tasks",
        slug="student-task-management-system",
        requirement_input=REQUIREMENT,
        owner_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    workspace.ensure_project(project.id)

    runtime = AgentRuntime(db, workspace=workspace)
    outcome, execution = runtime.execute(
        AgentRunRequest(
            project_id=project.id,
            agent_key="requirement",
            task="Produce the requirement specification.",
            trigger=ExecutionTrigger.WORKFLOW,
            user=user,
        )
    )

    print("== execution ==")
    print(f"status={execution.status} mode={execution.mode} model={execution.llm_model} "
          f"duration={execution.duration_ms}ms tokens={execution.total_tokens}")
    print("summary:", execution.output_summary)
    print("\n== artifacts ==")
    for artifact in outcome.artifacts:
        print(f"{artifact.artifact_type} -> {artifact.path} (trace refs: {len(artifact.trace_refs)})")

    markdown = outcome.artifacts[0].content
    print(f"\n== requirements.md ({len(markdown)} chars) ==")
    print(markdown[:1800])
    print("...\n")
    stored = workspace.read_text(project.id, "requirements/requirements.md")[0]
    print("materialised in workspace:", len(stored) == len(markdown))

    payload = outcome.structured
    print("\n== structured payload ==")
    print("functional:", len(payload["functional_requirements"]),
          "| nfr:", len(payload["non_functional_requirements"]),
          "| roles:", len(payload["user_roles"]),
          "| use cases:", len(payload["use_cases"]),
          "| open questions:", len(payload["open_questions"]))
    for requirement in payload["functional_requirements"][:5]:
        print(f"  {requirement['id']} [{requirement['priority']}] {requirement['title']}")

    # knowledge index should now hold requirement chunks
    from app.services.knowledge import KnowledgeService

    hits = KnowledgeService().search(db, project_id=project.id,
                                     query="mark tasks as completed", limit=3)
    print("\n== knowledge retrieval ==")
    for hit in hits:
        print(f"  score={hit.score} source={hit.source_ref} :: {hit.content[:80]!r}")

    db.close()
    print("\nSMOKE OK — workspace:", TMP)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
