"""ChangeSetService — diffs, application and traceability for code changes.

The Developer Agent proposes; the human approves; this service applies. It is the
only place allowed to write generated source into the workspace, and it always
produces a diff plus an audit entry so every code change is explainable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.artifact import Artifact
from app.models.enums import ActorType
from app.models.user import User
from app.services.artifact_service import ArtifactService
from app.services.audit import AuditService
from app.services.workspace import (
    WorkspaceService,
    content_hash,
    diff_stats,
    unified_diff,
)
from app.utils.time import utcnow

logger = get_logger("devforge.change_set")


@dataclass
class ChangeSummary:
    path: str
    operation: str
    summary: str = ""
    language: str = ""
    additions: int = 0
    deletions: int = 0
    diff: str = ""
    previous_hash: str = ""
    new_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "operation": self.operation,
            "summary": self.summary,
            "language": self.language,
            "additions": self.additions,
            "deletions": self.deletions,
            "diff": self.diff[:20000],
            "previous_hash": self.previous_hash,
            "new_hash": self.new_hash,
        }


@dataclass
class ChangeSetPlan:
    changes: list[ChangeSummary] = field(default_factory=list)

    @property
    def total_additions(self) -> int:
        return sum(change.additions for change in self.changes)

    @property
    def total_deletions(self) -> int:
        return sum(change.deletions for change in self.changes)

    def to_dict(self) -> dict:
        return {
            "changes": [change.to_dict() for change in self.changes],
            "file_count": len(self.changes),
            "additions": self.total_additions,
            "deletions": self.total_deletions,
            "operations": {
                operation: sum(1 for change in self.changes if change.operation == operation)
                for operation in ("create", "update", "delete")
            },
        }


class ChangeSetService:
    def __init__(self, db: Session, *, workspace: WorkspaceService | None = None) -> None:
        self.db = db
        self.workspace = workspace or WorkspaceService()
        self.audit = AuditService(db)

    # ------------------------------------------------------------------ planning
    def plan(self, project_id: str, files: list[dict]) -> ChangeSetPlan:
        """Compute diffs between the proposed files and the current workspace."""
        plan = ChangeSetPlan()
        for item in files:
            path = (item.get("path") or "").strip()
            if not path:
                continue
            content = item.get("content") or ""
            language = item.get("language") or ""
            operation = item.get("operation") or "update"
            exists = self.workspace.exists(project_id, path)
            previous = ""
            if exists:
                try:
                    previous, _ = self.workspace.read_text(project_id, path)
                except Exception:  # binary or unreadable
                    previous = ""
            diff = unified_diff(previous, content, path) if exists else ""
            if exists and previous == content:
                continue  # nothing to do for this file
            if not exists:
                operation = "create"
                diff = unified_diff("", content, path)
            additions, deletions = diff_stats(diff)
            plan.changes.append(
                ChangeSummary(
                    path=path,
                    operation=operation,
                    summary=item.get("summary", ""),
                    language=language,
                    additions=additions,
                    deletions=deletions,
                    diff=diff,
                    previous_hash=content_hash(previous) if previous else "",
                    new_hash=content_hash(content),
                )
            )
        return plan

    def has_pending_changes(self, project_id: str, artifact: Artifact) -> bool:
        files = (artifact.data or {}).get("changes") or []
        return bool(self.plan(project_id, files).changes)

    # ----------------------------------------------------------------- applying
    def apply(
        self,
        project_id: str,
        files: list[dict],
        *,
        user: User | None = None,
        run_id: str | None = None,
        reason: str = "Approved developer change set",
        agent_key: str = "developer",
    ) -> ChangeSetPlan:
        """Write approved changes into the workspace and record what happened."""
        plan = self.plan(project_id, files)
        applied: list[dict] = []
        for change in plan.changes:
            item = next((f for f in files if (f.get("path") or "").strip() == change.path), None)
            if item is None:
                continue
            if change.operation == "delete":
                self.workspace.delete(project_id, change.path)
            else:
                self.workspace.write_text(project_id, change.path, item.get("content") or "")
            applied.append(
                {
                    "path": change.path,
                    "operation": change.operation,
                    "additions": change.additions,
                    "deletions": change.deletions,
                    "hash": change.new_hash,
                }
            )

        if applied:
            self._reindex(project_id, applied)
            self.audit.record(
                action="code.changes_applied",
                project_id=project_id,
                user=user,
                actor_type=ActorType.USER if user else ActorType.AGENT,
                actor_label=agent_key,
                entity_type="workflow_run" if run_id else "project",
                entity_id=run_id or project_id,
                stage="DEVELOPMENT",
                summary=(
                    f"Applied {len(applied)} file change(s): +{plan.total_additions} "
                    f"-{plan.total_deletions}"
                ),
                detail={"files": applied},
            )
        logger.info("Applied %s file changes to project %s", len(applied), project_id)
        return plan

    def _reindex(self, project_id: str, applied: list[dict]) -> None:
        """Refresh project memory so downstream agents see the new code."""
        try:
            from app.models.enums import KnowledgeSource
            from app.services.knowledge import KnowledgeService

            knowledge = KnowledgeService()
            for item in applied:
                if item["operation"] == "delete":
                    knowledge.clear(self.db, project_id=project_id, source_ref=item["path"])
                    continue
                try:
                    content, _ = self.workspace.read_text(project_id, item["path"])
                except Exception:
                    continue
                knowledge.index_text(
                    self.db,
                    project_id=project_id,
                    source_type=KnowledgeSource.SOURCE_CODE,
                    source_ref=item["path"],
                    text=f"# File: {item['path']}\n\n{content}",
                    meta={"path": item["path"]},
                )
        except Exception as exc:  # indexing must never break an approval
            logger.warning("Post-apply indexing failed: %s", exc)

    # ------------------------------------------------------------------ history
    @staticmethod
    def summarise_artifact(artifact: Artifact) -> dict:
        """Human readable summary of a stored change set artifact."""
        data = artifact.data or {}
        return {
            "file_count": data.get("file_count", len(data.get("changes", []))),
            "additions": data.get("additions", 0),
            "deletions": data.get("deletions", 0),
            "operations": data.get("operations", {}),
            "files": [item.get("path") for item in data.get("changes", [])][:40],
        }

    def record_application(self, artifact: Artifact, plan: ChangeSetPlan, *,
                           user: User | None) -> Artifact:
        """Persist the applied state on the change-set artifact."""
        data = dict(artifact.data or {})
        data["applied"] = {
            "at": utcnow().isoformat(),
            # version-aware: a new proposal on the same artifact is applied again
            "version": int(artifact.version or 1),
            "by": (user.full_name or user.email) if user else "system",
            "files": [change.path for change in plan.changes],
            "additions": plan.total_additions,
            "deletions": plan.total_deletions,
        }
        artifact.data = data
        self.db.commit()
        self.db.refresh(artifact)
        return artifact

    def pending_from_artifact(self, artifact: Artifact) -> list[dict]:
        return list((artifact.data or {}).get("changes") or [])

    # ------------------------------------------------------------- entry points
    def apply_artifact(self, artifact: Artifact, *, user: User | None = None,
                       run_id: str | None = None) -> ChangeSetPlan:
        """Apply an APPROVED change-set artifact to the workspace (idempotent)."""
        from app.models.enums import ArtifactStatus, ArtifactType

        if artifact.type != ArtifactType.CHANGE_SET.value:
            raise ValueError(f"Artifact {artifact.id} is not a change set.")
        data = artifact.data or {}
        applied = data.get("applied") or {}
        if applied.get("files") and int(applied.get("version") or 0) >= int(artifact.version or 1):
            logger.info("Change set %s (v%s) already applied; skipping.", artifact.id,
                        artifact.version)
            return self.plan(artifact.project_id, [])
        if artifact.status != ArtifactStatus.APPROVED.value:
            raise ValueError("Only approved change sets can be applied.")
        files = self.pending_from_artifact(artifact)
        if not files:
            return self.plan(artifact.project_id, [])
        plan = self.apply(
            artifact.project_id, files, user=user, run_id=run_id,
            reason="Approved change set applied", agent_key="developer",
        )
        self.record_application(artifact, plan, user=user)
        return plan

    def ensure_applied(self, artifact: Artifact, *, user: User | None = None,
                       run_id: str | None = None) -> ChangeSetPlan:
        """Apply when pending, no-op when already applied (used by the workflow)."""
        from app.models.enums import ArtifactType

        if artifact.type != ArtifactType.CHANGE_SET.value:
            return self.plan(artifact.project_id, [])
        applied = (artifact.data or {}).get("applied") or {}
        if applied.get("files") and int(applied.get("version") or 0) >= int(artifact.version or 1):
            return self.plan(artifact.project_id, [])
        files = self.pending_from_artifact(artifact)
        if not files:
            return self.plan(artifact.project_id, [])
        plan = self.apply(artifact.project_id, files, user=user, run_id=run_id)
        self.record_application(artifact, plan, user=user)
        return plan


def change_set_service(db: Session, *, workspace: WorkspaceService | None = None) -> ChangeSetService:
    return ChangeSetService(db, workspace=workspace)
