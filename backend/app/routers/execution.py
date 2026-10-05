"""Manual execution endpoints: re-run tests, re-run security scan,
git operations and historical log retrieval."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Project, SecurityFinding, TestResult
from app.db.session import get_db
from app.execution import git_service, runner
from app.routers.projects import _get_project_or_404
from app.utils.files import workspace_root

router = APIRouter(prefix="/api/projects/{project_id}/execution", tags=["execution"])
settings = get_settings()


@router.post("/retest")
async def retest(project_id: str, db: Session = Depends(get_db)) -> dict:
    _get_project_or_404(db, project_id)
    ws = workspace_root(project_id)
    if not (ws / "tests").is_dir():
        raise HTTPException(400, "workspace has no tests/ directory yet")
    report = await asyncio.to_thread(runner.run_pytest, ws, settings.test_timeout)
    db.add(
        TestResult(
            project_id=project_id,
            run_number=1,
            passed=report["passed"],
            total=report["total"],
            failed=report["failed_count"],
            exit_code=report["exit_code"],
            duration_s=report["duration_s"],
            summary=report["summary"],
            output=report["output"][:40000],
        )
    )
    db.commit()
    return report


@router.post("/rescan")
async def rescan(project_id: str, db: Session = Depends(get_db)) -> dict:
    _get_project_or_404(db, project_id)
    ws = workspace_root(project_id)
    if not (ws / "src").is_dir():
        raise HTTPException(400, "workspace has no src/ directory yet")
    report = await asyncio.to_thread(runner.run_security_scan, ws, settings.scan_timeout)
    db.query(SecurityFinding).filter_by(project_id=project_id, status="open").update({"status": "resolved"})
    for f in report["findings"]:
        db.add(
            SecurityFinding(
                project_id=project_id,
                severity=f["severity"],
                category=f["category"],
                message=f["message"],
                file=f.get("file") or None,
                line=f.get("line"),
            )
        )
    db.commit()
    return report


@router.post("/git/commit")
async def git_commit(project_id: str, db: Session = Depends(get_db)) -> dict:
    p = _get_project_or_404(db, project_id)
    ws = workspace_root(project_id)
    info = await asyncio.to_thread(git_service.deliver, ws, p.name)
    return info


@router.get("/git/info")
async def git_info(project_id: str, db: Session = Depends(get_db)) -> dict:
    _get_project_or_404(db, project_id)
    return git_service.describe(workspace_root(project_id))


@router.get("/logs")
async def get_logs(project_id: str, limit: int = Query(default=200, le=1000), db: Session = Depends(get_db)) -> list[dict]:
    from app.db.models import WorkflowEvent

    _get_project_or_404(db, project_id)
    rows = (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.project_id == project_id)
        .order_by(WorkflowEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "type": r.type,
            "stage": r.stage,
            "message": r.message,
            "payload": r.payload,
            "ts": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reversed(rows)
    ]
