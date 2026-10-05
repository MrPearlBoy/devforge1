"""Seed a demo account and the §37 Student Task Management System scenario.

    python scripts/seed_demo.py                 # demo user + project only
    python scripts/seed_demo.py --run-workflow  # also drive the agent workflow to completion

The workflow option approves every gate as the human, so the seeded workspace already
contains generated code, tests, a security report and documentation — ideal for a demo
or a viva where you want the UI populated before you start talking.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("DEVFORGE_MODE", "mock")

from sqlalchemy import select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.enums import ApprovalDecision, WorkflowStatus  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent_registry import seed_agent_catalog  # noqa: E402
from app.services.approval_service import ApprovalService  # noqa: E402
from app.services.workspace import WorkspaceService  # noqa: E402
from app.workflows.engine import WorkflowEngine  # noqa: E402

DEMO_EMAIL = "demo@devforge.dev"
DEMO_PASSWORD = "devforge123"

REQUIREMENT = (
    "Build a web application where students can create tasks, update tasks, delete tasks "
    "and mark tasks as completed. Students should also be able to view their pending tasks "
    "and filter them by deadline. An administrator must be able to view all users and remove "
    "inactive accounts.\n\n"
    "The application must be usable on a mobile browser, keep an audit trail of task changes, "
    "and be deployable on a single small server."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-workflow", action="store_true",
                        help="Also run the SDLC workflow, approving every human gate.")
    parser.add_argument("--email", default=DEMO_EMAIL)
    parser.add_argument("--password", default=DEMO_PASSWORD)
    parser.add_argument("--name", default="Student Task Management System")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    seed_agent_catalog(db)

    user = db.scalar(select(User).where(User.email == args.email))
    if user is None:
        user = User(email=args.email, full_name="Demo Reviewer",
                    hashed_password=hash_password(args.password), role="ADMIN")
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"created demo user {args.email} (password: {args.password})")
    else:
        print(f"demo user {args.email} already exists")

    slug = args.name.lower().replace(" ", "-")[:200]
    project = db.scalar(select(Project).where(Project.slug == slug))
    if project is None:
        project = Project(
            name=args.name,
            description=("Final-year demo scenario: students manage coursework tasks while an "
                         "administrator manages accounts."),
            slug=slug,
            requirement_input=REQUIREMENT,
            tech_stack="FastAPI, SQLite, pytest",
            tags=["demo", "education", "crud"],
            owner_id=user.id,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        WorkspaceService().ensure_project(project.id)
        print(f"created project '{args.name}' ({project.id})")
    else:
        print(f"project '{args.name}' already exists ({project.id})")

    if args.run_workflow:
        engine = WorkflowEngine()
        run = engine.start(project.id, user=user, background=False,
                          instructions="Optimise for clarity in a live demonstration.")
        while run.status in {WorkflowStatus.AWAITING_APPROVAL.value, WorkflowStatus.PAUSED.value}:
            pending = ApprovalService(db).latest_pending(project.id)
            if pending is None:
                break
            print(f"  approving gate: {pending.gate} ({pending.stage})")
            run = engine.resume(run.id, user=user, decision=ApprovalDecision.APPROVE,
                               comments="Approved by the demo seed script.",
                               approval_id=pending.id, background=False)
            db.expire_all()
        print(f"workflow finished with status {run.status}")
        if run.last_error:
            print(f"  last error: {run.last_error[:200]}")

    db.close()
    print("\nNext steps:")
    print(f"  1. start the API:      uvicorn app.main:app --reload --port 8000")
    print(f"  2. start the UI:       cd ../frontend && npm run dev")
    print(f"  3. sign in with:       {args.email} / {args.password}")
    print(f"  4. database in use:    {settings.database_url}")
    print(f"  5. workspaces:         {settings.workspace_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
