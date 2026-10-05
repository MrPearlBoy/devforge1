"""Approval service — the human control plane of DevForge.

The workflow engine blocks on a LangGraph ``interrupt`` for every gate; that
interrupt is created here as a PENDING row, and only a recorded human decision
(either this service or the API) allows the graph to advance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.events import bus
from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.approval import Approval
from app.models.artifact import Artifact
from app.models.enums import ApprovalDecision, ApprovalStatus, ArtifactStatus, ActorType
from app.models.user import User
from app.services.audit import AuditService

logger = get_logger("devforge.approvals")

GATE_LABELS = {
    "requirements_approval": "Requirements approval",
    "architecture_approval": "Architecture approval",
    "code_review": "Code review",
    "test_review": "Test results review",
    "security_review": "Security findings review",
    "documentation_approval": "Documentation approval",
    "delivery_confirmation": "GitHub delivery confirmation",
    "chat_change_request": "Chat proposed changes",
}


#: Canonical audit verbs for a human decision (stable for the activity feed).
DECISION_ACTIONS = {
    ApprovalDecision.APPROVE.value: "approval.approved",
    ApprovalDecision.REJECT.value: "approval.rejected",
    ApprovalDecision.REQUEST_CHANGES.value: "approval.changes_requested",
}


class ApprovalService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ create
    def request(
        self,
        *,
        project_id: str,
        stage: str,
        gate: str,
        artifact: Artifact | None = None,
        agent_key: str | None = None,
        run_id: str | None = None,
        summary: str = "",
        meta: dict | None = None,
        mark_artifact: bool = True,
    ) -> Approval:
        """Open a PENDING approval gate (idempotent per open gate+artifact).

        ``mark_artifact=False`` is used by side gates such as chat proposals: they review
        an *additional* proposal on top of an artifact whose approved status must not be
        downgraded (that would falsely re-open an already approved workflow stage).
        """
        existing = self.db.scalars(
            select(Approval).where(
                Approval.project_id == project_id,
                Approval.stage == stage,
                Approval.gate == gate,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        ).first()
        if existing is not None and existing.artifact_id == (artifact.id if artifact else None):
            return existing

        approval = Approval(
            project_id=project_id,
            run_id=run_id,
            artifact_id=artifact.id if artifact else None,
            stage=stage,
            gate=gate,
            status=ApprovalStatus.PENDING.value,
            requested_by_agent_key=agent_key,
            requested_at=datetime.now(timezone.utc),
            decision_meta=meta or {},
        )
        self.db.add(approval)
        if artifact is not None and mark_artifact:
            artifact.status = ArtifactStatus.IN_REVIEW.value
        self.db.commit()
        self.db.refresh(approval)

        self.audit.record(
            action="approval.requested",
            project_id=project_id,
            actor_type=ActorType.AGENT,
            actor_label=agent_key or "system",
            entity_type="approval",
            entity_id=approval.id,
            stage=stage,
            summary=summary or f"{GATE_LABELS.get(gate, gate)} requested",
            detail={"gate": gate, "artifact_id": approval.artifact_id},
        )
        bus.emit(
            "approval_required",
            project_id,
            approval_id=approval.id,
            gate=gate,
            stage=stage,
            artifact_id=approval.artifact_id,
            agent_key=agent_key,
            artifact_title=artifact.title if artifact else "",
        )
        return approval

    # ------------------------------------------------------------------ decide
    def decide(
        self,
        approval_id: str,
        *,
        user: User,
        decision: ApprovalDecision,
        comments: str = "",
        instructions: str = "",
        edited_content: str | None = None,
    ) -> Approval:
        approval = self.db.get(Approval, approval_id)
        if approval is None:
            raise NotFoundError("Approval request not found.")
        if approval.status != ApprovalStatus.PENDING.value:
            raise ConflictError(
                f"This approval was already {approval.status.lower().replace('_', ' ')}.",
                detail={"status": approval.status},
            )

        # Accept either the enum or its string form (API payloads arrive as strings).
        decision = decision if isinstance(decision, ApprovalDecision) else ApprovalDecision(decision)

        artifact = self.db.get(Artifact, approval.artifact_id) if approval.artifact_id else None
        if edited_content is not None and artifact is not None:
            from app.services.artifact_service import ArtifactService

            ArtifactService(self.db).apply_human_edit(
                artifact, edited_content, user=user, reason=f"Edited before {decision.value.lower()}"
            )

        status_map = {
            ApprovalDecision.APPROVE: ApprovalStatus.APPROVED,
            ApprovalDecision.REJECT: ApprovalStatus.REJECTED,
            ApprovalDecision.REQUEST_CHANGES: ApprovalStatus.CHANGES_REQUESTED,
        }
        approval.status = status_map[decision].value
        approval.decided_by_user_id = user.id
        approval.decided_at = datetime.now(timezone.utc)
        approval.comments = comments
        approval.decision_meta = {
            **(approval.decision_meta or {}),
            "decision": decision.value,
            "instructions": instructions,
            "edited_before_decision": edited_content is not None,
        }

        if artifact is not None:
            artifact.status = {
                ApprovalDecision.APPROVE: ArtifactStatus.APPROVED.value,
                ApprovalDecision.REJECT: ArtifactStatus.REJECTED.value,
                ApprovalDecision.REQUEST_CHANGES: ArtifactStatus.DRAFT.value,
            }[decision]

        self.db.commit()
        self.db.refresh(approval)

        self.audit.record(
            action=DECISION_ACTIONS.get(decision.value, "approval.decided"),
            project_id=approval.project_id,
            user=user,
            entity_type="approval",
            entity_id=approval.id,
            stage=approval.stage,
            summary=(
                f"{user.full_name or user.email} {decision.value.replace('_', ' ').lower()} "
                f"{GATE_LABELS.get(approval.gate, approval.gate).lower()}"
            ),
            detail={"comments": comments, "instructions": instructions},
        )
        bus.emit(
            "approval_decided",
            approval.project_id,
            approval_id=approval.id,
            decision=decision.value,
            stage=approval.stage,
            gate=approval.gate,
            artifact_id=approval.artifact_id,
            by=user.full_name or user.email,
            comments=comments,
        )
        return approval

    # -------------------------------------------------------------------- read
    def get(self, approval_id: str) -> Approval:
        approval = self.db.get(Approval, approval_id)
        if approval is None:
            raise NotFoundError("Approval request not found.")
        return approval

    def pending(self, project_id: str) -> list[Approval]:
        stmt = (
            select(Approval)
            .where(Approval.project_id == project_id, Approval.status == ApprovalStatus.PENDING.value)
            .order_by(desc(Approval.created_at))
        )
        return list(self.db.scalars(stmt))

    def list_for_project(self, project_id: str, *, status: str | None = None,
                         limit: int = 100) -> list[Approval]:
        stmt = select(Approval).where(Approval.project_id == project_id)
        if status:
            stmt = stmt.where(Approval.status == status)
        stmt = stmt.order_by(desc(Approval.created_at)).limit(limit)
        return list(self.db.scalars(stmt))

    def open_for_run(self, run_id: str, gate: str = "") -> Approval | None:
        """Latest approval opened for a workflow run (pending ones first).

        Used by the graph's approval node, which must not create duplicates when
        LangGraph re-executes it after a resume.
        """
        if not run_id:
            return None
        stmt = select(Approval).where(Approval.run_id == run_id)
        if gate:
            stmt = stmt.where(Approval.gate == gate)
        rows = list(self.db.scalars(stmt.order_by(desc(Approval.created_at)).limit(10)))
        for row in rows:
            if row.status == ApprovalStatus.PENDING.value:
                return row
        return rows[0] if rows else None

    def latest_pending(self, project_id: str) -> Approval | None:
        rows = self.pending(project_id)
        return rows[0] if rows else None

    def history(self, project_id: str, *, limit: int = 50) -> list[Approval]:
        stmt = (
            select(Approval)
            .where(
                Approval.project_id == project_id,
                Approval.status != ApprovalStatus.PENDING.value,
            )
            .order_by(desc(Approval.decided_at))
            .limit(limit)
        )
        return list(self.db.scalars(stmt))
