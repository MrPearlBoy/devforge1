"""Human-in-the-loop approval gates (G1, G2, G3, G6)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import Project
from app.db.session import get_db
from app.orchestrator.state import DECISIONS, GATES, GATE_TITLES
from app.orchestrator.workflow_engine import get_engine
from app.routers.projects import _get_project_or_404

router = APIRouter(prefix="/api/projects", tags=["approvals"])


class ApprovalIn(BaseModel):
    gate: str = Field(description="One of: requirement | architecture | code | docs")
    decision: str = Field(description="One of: approved | rejected | changes_requested")
    comment: Optional[str] = Field(default=None, max_length=4000)


@router.get("/{project_id}/approvals/pending")
async def pending_gate(project_id: str, db: Session = Depends(get_db)) -> dict:
    p = _get_project_or_404(db, project_id)
    gate = p.awaiting_gate
    return {
        "pending": gate is not None,
        "gate": gate,
        "title": GATE_TITLES.get(gate, "") if gate else None,
        "status": p.status,
    }


@router.post("/{project_id}/approvals")
async def submit_approval(project_id: str, body: ApprovalIn, db: Session = Depends(get_db)) -> dict:
    _get_project_or_404(db, project_id)
    if body.gate not in GATES:
        raise HTTPException(422, f"unknown gate '{body.gate}' (expected one of {list(GATES)})")
    if body.decision not in DECISIONS:
        raise HTTPException(422, f"unknown decision '{body.decision}' (expected one of {list(DECISIONS)})")
    if body.decision != "approved" and not (body.comment or "").strip():
        raise HTTPException(422, "a comment is required when rejecting or requesting changes")

    engine = get_engine(project_id)
    ok = engine.submit_approval(body.gate, body.decision, (body.comment or "").strip())
    if not ok:
        raise HTTPException(
            409,
            f"no pending approval for gate '{body.gate}' — current gate: {engine.state.awaiting_gate or 'none'} "
            f"(workflow status: {engine.state.status})",
        )
    return {"recorded": True, "gate": body.gate, "decision": body.decision, "comment": body.comment}
