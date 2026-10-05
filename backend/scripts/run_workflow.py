"""Drive the complete DevForge SDLC workflow from the command line.

This exercises exactly the same orchestration the web workspace uses: the LangGraph
graph, the human approval interrupts, the agent runtime, the sandbox test execution
and the artifact/traceability storage. Approvals are supplied by this script to keep
the run non-interactive — in the platform they come from the human through the UI.

Usage:
    python scripts/run_workflow.py                 # approve every gate
    python scripts/run_workflow.py --reject-first  # request changes once, then approve
    python scripts/run_workflow.py --live          # use the configured LLM provider
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP = tempfile.mkdtemp(prefix="devforge-workflow-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP}/workflow.db")
os.environ.setdefault("WORKSPACE_ROOT", f"{TMP}/workspace")
os.environ.setdefault("CHECKPOINT_PATH", f"{TMP}/checkpoints.sqlite")
os.environ.setdefault("SECRET_KEY", "workflow-cli-secret-0123456789abcdefghij")

from sqlalchemy import func, select  # noqa: E402

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.artifact import Artifact  # noqa: E402
from app.models.enums import ApprovalDecision, WorkflowStatus  # noqa: E402
from app.models.knowledge import KnowledgeChunk  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent_registry import seed_agent_catalog  # noqa: E402
from app.services.trace import TraceService  # noqa: E402
from app.services.workspace import WorkspaceService  # noqa: E402
from app.workflows.engine import WorkflowEngine  # noqa: E402

REQUIREMENT = (
    "Build a web application where students can create tasks, update tasks, delete tasks "
    "and mark tasks as completed. Students should also be able to view their pending tasks "
    "and filter them by deadline. An administrator must be able to view all users and remove "
    "inactive accounts."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reject-first", action="store_true",
                        help="Request changes at the requirement gate once, then approve.")
    parser.add_argument("--live", action="store_true", help="Force live LLM mode.")
    parser.add_argument("--max-approvals", type=int, default=25)
    args = parser.parse_args()

    if args.live:
        os.environ["DEVFORGE_MODE"] = "live"
    else:
        os.environ["DEVFORGE_MODE"] = os.environ.get("DEVFORGE_MODE", "mock")

    init_db()
    db = SessionLocal()
    seed_agent_catalog(db)

    user = User(email="demo@devforge.test", full_name="Demo Human",
                hashed_password=hash_password("password123"), role="ADMIN")
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = WorkspaceService()
    project = Project(
        name="Student Task Management System",
        description="Students track coursework; administrators manage accounts.",
        slug="student-task-management-system",
        requirement_input=REQUIREMENT,
        owner_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    workspace.ensure_project(project.id)

    engine = WorkflowEngine()
    run = engine.start(project.id, user=user, background=False,
                      instructions="Keep the implementation small and demonstrable for a "
                                   "final-year project review.")
    print(f"run {run.id} -> status={run.status} stage={run.current_stage}")

    approvals = 0
    rejected_once = False
    while run.status in {WorkflowStatus.AWAITING_APPROVAL.value, WorkflowStatus.PAUSED.value} \
            and approvals < args.max_approvals:
        with SessionLocal() as session:
            from app.services.approval_service import ApprovalService

            pending = ApprovalService(session).latest_pending(project.id)
            if pending is None:
                print("no pending approval — stopping")
                break
            pending_id, stage, gate = pending.id, pending.stage, pending.gate
            artifact = session.get(Artifact, pending.artifact_id) if pending.artifact_id else None
            artifact_title = artifact.title if artifact else "(no artifact)"

        print(f"\n>>> HUMAN GATE [{stage}] {gate}: {artifact_title}")
        print("    options: APPROVE | REJECT | REQUEST_CHANGES")

        decision = ApprovalDecision.APPROVE
        comments = "Reviewed and approved in the workflow CLI."
        if args.reject_first and not rejected_once and stage == "REQUIREMENTS":
            decision = ApprovalDecision.REQUEST_CHANGES
            comments = ("Please add explicit acceptance criteria for filtering tasks by deadline "
                        "and note the assumption about authentication.")
            rejected_once = True
            print("    decision: REQUEST_CHANGES (round-trip test)")

        run = engine.resume(run.id, user=user, decision=decision, comments=comments,
                            approval_id=pending_id, background=False)
        approvals += 1
        print(f"    -> status={run.status} stage={run.current_stage} node={run.current_node}")

    print("\n================ FINAL STATE ================")
    print(f"status        : {run.status}")
    print(f"stage         : {run.current_stage}")
    print(f"steps         : {run.total_steps}")
    print(f"iterations    : {run.stage_iterations}")
    print(f"last error    : {run.last_error or '—'}")

    snapshot = run.state_snapshot or {}
    for key in ("test_results", "security_results", "source_changes", "delivery"):
        value = snapshot.get(key) or {}
        if key == "test_results" and value:
            print(f"{key:<13} : {value.get('passed')}/{value.get('total')} passed "
                  f"(status {value.get('status')})")
        elif key == "security_results" and value:
            print(f"{key:<13} : {value.get('findings')} findings {value.get('counts')}")
        elif key == "source_changes" and value:
            print(f"{key:<13} : {value.get('file_count')} files "
                  f"(+{value.get('additions')}/-{value.get('deletions')})")
        elif key == "delivery" and value:
            print(f"{key:<13} : {value.get('status')} — {value.get('reason', '')[:90]}")

    print("\n================ WORKSPACE ================")
    for info in workspace.list_files(project.id):
        print(f"  {info.path:<46} {info.size:>7} B")

    print("\n================ TRACEABILITY ================")
    matrix = TraceService(db).matrix(project.id)
    print(f"nodes={len(matrix['nodes'])} links={len(matrix['links'])}")
    print(f"coverage=%: {matrix['coverage'].get('percent')}")
    for gap in matrix["gap_report"][:6]:
        print(f"  gap: {gap}")

    artifacts = db.scalars(select(Artifact).where(Artifact.project_id == project.id)).all()
    chunks = db.scalar(select(func.count(KnowledgeChunk.id))) or 0
    print(f"\nartifacts={len(artifacts)}  knowledge_chunks={chunks}")
    print(f"workspace: {workspace.project_dir(project.id)}")
    db.close()

    ok = run.status == WorkflowStatus.COMPLETED.value
    print("\nWORKFLOW RESULT:", "COMPLETED" if ok else f"INCOMPLETE ({run.status})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
