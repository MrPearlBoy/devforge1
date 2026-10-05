"""CLI smoke test for the agent stages (mock mode, no API server needed).

Usage:
    python scripts/smoke_pipeline.py                 # requirement + architecture
    python scripts/smoke_pipeline.py --stages all    # every implemented agent stage

This drives the very same services the API and the LangGraph orchestrator use, so
a green run here means the stage logic is sound.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TMP = tempfile.mkdtemp(prefix="devforge-pipeline-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP}/pipeline.db")
os.environ.setdefault("WORKSPACE_ROOT", f"{TMP}/workspace")
os.environ.setdefault("DEVFORGE_MODE", "mock")
os.environ.setdefault("SECRET_KEY", "pipeline-smoke-secret-key-0123456789")

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.enums import ApprovalDecision, ExecutionTrigger  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent_registry import seed_agent_catalog  # noqa: E402
from app.services.agent_runtime import AgentRunRequest, AgentRuntime  # noqa: E402
from app.services.approval_service import ApprovalService  # noqa: E402
from app.services.artifact_service import ArtifactService  # noqa: E402
from app.services.change_set import ChangeSetService  # noqa: E402
from app.services.trace import TraceService  # noqa: E402
from app.services.workspace import WorkspaceService  # noqa: E402

REQUIREMENT = (
    "Build a web application where students can create tasks, update tasks, delete tasks "
    "and mark tasks as completed. Students should also be able to view their pending tasks "
    "and filter them by deadline. An administrator must be able to view all users and "
    "remove inactive accounts."
)

STAGE_SEQUENCE = [
    ("requirement", "Produce the requirement specification."),
    ("architecture", "Produce the architecture specification from the approved requirements."),
    ("developer", "Implement the approved architecture."),
    ("testing", "Write and execute the test suite."),
    ("security", "Scan the implementation for security issues."),
    ("documentation", "Generate README and supporting documentation."),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stages", default="requirement,architecture",
                        help="comma separated agent keys, or 'all'")
    args = parser.parse_args()

    requested = [key for key, _ in STAGE_SEQUENCE] if args.stages == "all" else \
        [item.strip() for item in args.stages.split(",") if item.strip()]

    init_db()
    db = SessionLocal()
    seed_agent_catalog(db)

    user = User(email="pipeline@devforge.test", full_name="Pipeline Runner",
                hashed_password=hash_password("password123"))
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = WorkspaceService()
    project = Project(
        name="Student Task Management System",
        description="Students track coursework tasks; admins manage accounts.",
        slug="student-task-management-system",
        requirement_input=REQUIREMENT,
        owner_id=user.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    workspace.ensure_project(project.id)

    runtime = AgentRuntime(db, workspace=workspace)
    change_sets = ChangeSetService(db, workspace=workspace)
    approvals = ApprovalService(db)
    artifacts = ArtifactService(db, workspace=workspace)
    trace = TraceService(db)

    print(f"workspace: {workspace.project_dir(project.id)}\n")
    for agent_key, task in STAGE_SEQUENCE:
        if agent_key not in requested:
            continue
        print(f"===== {agent_key.upper()} AGENT =====")
        outcome, execution = runtime.execute(
            AgentRunRequest(project_id=project.id, agent_key=agent_key, task=task,
                            trigger=ExecutionTrigger.WORKFLOW, user=user)
        )
        print(f"  status={execution.status} mode={execution.mode} "
              f"duration={execution.duration_ms}ms")
        print(f"  summary: {execution.output_summary}")
        for draft in outcome.artifacts:
            print(f"  artifact: {draft.artifact_type:<24} -> {draft.path or '(no file)'} "
                  f"[{len(draft.content)} chars]")
        for warning in outcome.warnings:
            print(f"  warning: {warning[:140]}")
        if outcome.trace_pairs:
            print(f"  trace links: {len(outcome.trace_pairs)}")

        # auto-approve so later stages receive approved upstream artifacts
        primary = artifacts.list_for_project(project.id, stage=outcome.stage)
        if primary:
            artifact = primary[0]
            approval = approvals.request(
                project_id=project.id, stage=outcome.stage, gate=f"{agent_key}_approval",
                artifact=artifact, agent_key=agent_key,
                summary=f"{agent_key} approval (automatic in smoke test)",
            )
            approvals.decide(approval.id, user=user, decision=ApprovalDecision.APPROVE,
                             comments="auto-approved by smoke pipeline")
            print(f"  approval: {approval.status}")
            # a code change set only reaches the workspace after approval
            if artifact.type == "CHANGE_SET":
                plan = change_sets.apply_artifact(artifact, user=user)
                print(f"  applied: {len(plan.changes)} file(s) "
                      f"(+{plan.total_additions}/-{plan.total_deletions})")
        print()

    print("===== TRACEABILITY =====")
    from app.agents.common.domain_inference import infer_domain  # noqa: F401  (sanity import)

    matrix = trace.matrix(project.id)
    coverage = matrix["coverage"]
    print(f"  nodes={len(matrix['nodes'])} links={len(matrix['links'])}")
    print(f"  coverage percent: {coverage.get('percent')}")
    if matrix["gap_report"]:
        print("  gaps:")
        for gap in matrix["gap_report"][:5]:
            print(f"    - {gap}")

    print("\n===== WORKSPACE FILES =====")
    for info in workspace.list_files(project.id):
        print(f"  {info.path:<48} {info.size:>7} bytes  {info.language}")

    print("\n===== KNOWLEDGE INDEX =====")
    from sqlalchemy import func, select

    from app.models.knowledge import KnowledgeChunk

    total = db.scalar(select(func.count(KnowledgeChunk.id))) or 0
    print(f"  indexed chunks: {total}")

    db.close()
    print(f"\nPIPELINE OK — artefacts under {TMP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
