"""Project lifecycle: create, list, snapshot, start, SSE stream, files."""
from __future__ import annotations

import json
import shutil
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Project, TestResult, WorkflowEvent
from app.db.session import get_db
from app.orchestrator.workflow_engine import get_engine
from app.streaming.bus import get_bus
from app.utils.files import file_tree, read_file_safe, workspace_root

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    task: str = Field(min_length=10, max_length=4000, description="High-level prompt for the Requirement Agent")


def _get_project_or_404(db: Session, project_id: str) -> Project:
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _loads(raw: Optional[str]) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_snapshot(db: Session, p: Project) -> dict[str, Any]:
    """Full project view: state, trimmed artifacts, events, files, results."""
    artifacts: dict[str, Any] = {}
    iterations: dict[str, int] = {}
    if p.artifacts:
        try:
            state = json.loads(p.artifacts)
            artifacts = {k: state.get(k) for k in ("requirement", "architecture", "code", "tests", "security", "docs", "git")}
            if artifacts.get("code"):
                files = artifacts["code"].get("files", [])
                artifacts["code"]["files"] = [
                    {"path": f.get("path"), "description": f.get("description", ""), "size": len(f.get("content", ""))}
                    for f in files
                ]
            iterations = state.get("iterations", {}) or {}
        except json.JSONDecodeError:
            pass

    ws = workspace_root(p.id)
    files = file_tree(ws) if ws.exists() else []

    events = (
        db.query(WorkflowEvent)
        .filter(WorkflowEvent.project_id == p.id)
        .order_by(WorkflowEvent.id.desc())
        .limit(150)
        .all()
    )
    events = [
        {
            "type": e.type,
            "stage": e.stage,
            "message": e.message,
            "payload": _loads(e.payload),
            "ts": e.created_at.isoformat() if e.created_at else None,
        }
        for e in reversed(events)
    ]

    test_runs = (
        db.query(TestResult)
        .filter(TestResult.project_id == p.id)
        .order_by(TestResult.id.desc())
        .limit(5)
        .all()
    )
    return {
        "id": p.id,
        "name": p.name,
        "task": p.task,
        "stage": p.stage,
        "status": p.status,
        "awaiting_gate": p.awaiting_gate,
        "llm_provider": p.llm_provider,
        "error": p.error,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "iterations": iterations,
        "artifacts": artifacts,
        "files": files,
        "events": events,
        "test_runs": [
            {
                "run_number": t.run_number,
                "passed": t.passed,
                "failed": t.failed,
                "total": t.total,
                "summary": t.summary,
                "duration_s": t.duration_s,
                "ts": t.created_at.isoformat() if t.created_at else None,
            }
            for t in test_runs
        ],
    }


@router.post("", status_code=201)
async def create_project(body: ProjectCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    pid = uuid.uuid4().hex
    ws = workspace_root(pid)
    ws.mkdir(parents=True, exist_ok=True)
    p = Project(id=pid, name=body.name.strip(), task=body.task.strip())
    db.add(p)
    db.commit()
    db.refresh(p)
    return build_snapshot(db, p)


@router.get("")
async def list_projects(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    projects = db.query(Project).order_by(Project.created_at.desc()).all()
    return [build_snapshot(db, p) for p in projects]


@router.get("/{project_id}")
async def get_project(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return build_snapshot(db, _get_project_or_404(db, project_id))


@router.post("/{project_id}/start")
async def start_project(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _get_project_or_404(db, project_id)
    if p.status == "completed":
        raise HTTPException(409, "workflow already completed")
    if p.status in ("running", "waiting_approval", "interrupted", "failed"):
        # stale/crashed state from a previous backend run — allow a clean (re)start
        p.status = "idle"
        p.error = None
        db.commit()
    engine = get_engine(project_id)
    if p.status in ("running", "waiting_approval") and engine._task and not engine._task.done():
        raise HTTPException(409, "workflow already running")
    started = await engine.start()
    return {"started": started, "stage": engine.state.stage, "status": engine.state.status}


@router.get("/{project_id}/events")
async def project_events(project_id: str, db: Session = Depends(get_db)):
    """Server-Sent Events stream of live workflow events."""
    _get_project_or_404(db, project_id)
    bus = get_bus()
    return StreamingResponse(
        bus.stream(project_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/{project_id}/files")
async def list_files(project_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _get_project_or_404(db, project_id)
    return file_tree(workspace_root(project_id))


@router.get("/{project_id}/files/content")
async def file_content(project_id: str, path: str = Query(min_length=1), db: Session = Depends(get_db)) -> dict[str, Any]:
    _get_project_or_404(db, project_id)
    try:
        content = read_file_safe(workspace_root(project_id), path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"path": path, "content": content}


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: Session = Depends(get_db)) -> None:
    p = _get_project_or_404(db, project_id)
    for model in (WorkflowEvent, TestResult):
        db.query(model).filter_by(project_id=project_id).delete()
    from app.db.models import Approval, SecurityFinding

    db.query(Approval).filter_by(project_id=project_id).delete()
    db.query(SecurityFinding).filter_by(project_id=project_id).delete()
    db.delete(p)
    db.commit()
    shutil.rmtree(workspace_root(project_id), ignore_errors=True)
