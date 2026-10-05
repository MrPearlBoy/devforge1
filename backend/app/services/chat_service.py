"""Human ↔ agent chat.

A chat turn runs the selected agent through exactly the same runtime the workflow
uses, then stores both sides of the conversation. When the agent proposes code, the
proposal is filed as a change-set artifact behind an approval gate — a chat message
can never write to the workspace on its own.
"""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationFailure
from app.core.events import bus
from app.core.logging import get_logger
from app.models.artifact import Artifact
from app.models.conversation import AgentMessage
from app.models.enums import (
    ArtifactType,
    ExecutionTrigger,
    MessageRole,
    Stage,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.agent import ChatResponse, ProposedFileChange
from app.services.agent_registry import all_agent_keys, get_agent_spec
from app.services.agent_runtime import AgentRunRequest, AgentRuntime
from app.services.approval_service import ApprovalService
from app.workflows.state import STAGE_LABELS

logger = get_logger("devforge.chat")

CHAT_GATE = "chat_change_request"
DEFAULT_AGENT = "developer"


class ChatService:
    """Conversations with a specific agent, in a specific project."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.runtime = AgentRuntime(db)

    # ------------------------------------------------------------------ sending
    def send(
        self,
        project: Project,
        *,
        user: User,
        message: str,
        agent_key: str = "",
        thread_id: str = "default",
        allow_code_proposals: bool = True,
    ) -> ChatResponse:
        message = (message or "").strip()
        if not message:
            raise ValidationFailure("Write a message before sending it.")

        key = agent_key or DEFAULT_AGENT
        if key not in all_agent_keys():
            raise ValidationFailure(
                f"Unknown agent '{key}'. Available agents: {', '.join(all_agent_keys())}.",
            )
        spec = get_agent_spec(key)

        human_turn = AgentMessage(
            project_id=project.id,
            agent_key=key,
            thread_id=thread_id,
            role=MessageRole.USER.value,
            content=message,
            user_id=user.id,
            meta={"agent_name": spec.name},
        )
        self.db.add(human_turn)
        self.db.commit()
        self.db.refresh(human_turn)
        bus.emit(
            "chat_message", project.id, agent_key=key, thread_id=thread_id,
            role="USER", message_id=human_turn.id,
            message=message[:280], user=user.full_name or user.email,
        )

        outcome, execution = self.runtime.execute(AgentRunRequest(
            project_id=project.id,
            agent_key=key,
            task=message,
            instructions=message,
            trigger=ExecutionTrigger.CHAT,
            thread_agent_key=key,
            user=user,
            query=message,
            include_source=allow_code_proposals,
            meta={"thread_id": thread_id, "trigger": "chat"},
        ))

        proposed = self._proposed_changes(outcome)
        approval_id = ""
        artifact_path = ""
        if proposed and allow_code_proposals:
            approval_id, artifact_path = self._gate_proposal(project, user, outcome, key)

        references = self._references(outcome)
        assistant_turn = AgentMessage(
            project_id=project.id,
            agent_key=key,
            thread_id=thread_id,
            role=MessageRole.AGENT.value,
            content=outcome.content or outcome.summary or "(no reply)",
            execution_id=execution.id,
            meta={
                "summary": outcome.summary,
                "proposed_changes": [item.model_dump() for item in proposed],
                "approval_id": approval_id,
                "artifact_path": artifact_path,
                "references": references,
                "warnings": outcome.warnings[:5],
                "mode": execution.mode,
                "model": execution.llm_model,
                "duration_ms": execution.duration_ms,
            },
        )
        self.db.add(assistant_turn)
        self.db.commit()
        self.db.refresh(assistant_turn)

        bus.emit(
            "chat_reply", project.id, agent_key=key, thread_id=thread_id,
            role="AGENT", message_id=assistant_turn.id,
            summary=outcome.summary[:280], execution_id=execution.id,
            approval_id=approval_id, proposed=len(proposed),
            mode=execution.mode,
        )
        return ChatResponse(
            message_id=assistant_turn.id,
            agent_key=key,
            content=assistant_turn.content,
            created_at=assistant_turn.created_at,
            execution_id=execution.id,
            mode=execution.mode,
            model=execution.llm_model,
            proposed_changes=proposed,
            approval_id=approval_id or None,
            references=references,
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _proposed_changes(outcome) -> list[ProposedFileChange]:  # noqa: ANN001
        changes: list[ProposedFileChange] = []
        for item in (outcome.file_changes or [])[:20]:
            content = item.get("content", "") or ""
            additions = item.get("additions")
            if additions is None:
                additions = sum(1 for line in content.splitlines() if line.strip())
            changes.append(ProposedFileChange(
                path=item.get("path", ""),
                op=item.get("operation", "update"),
                description=item.get("summary", ""),
                diff=item.get("diff", "")[:8000],
                content=content[:20000],
                language=item.get("language", ""),
                additions=int(additions or 0),
                deletions=int(item.get("deletions") or 0),
            ))
        return changes

    def _gate_proposal(self, project: Project, user: User, outcome, agent_key: str) -> tuple[str, str]:  # noqa: ANN001
        """File the chat proposal as a change set behind a human approval gate."""
        artifact: Artifact | None = None
        for draft in outcome.artifacts:
            if draft.artifact_type == ArtifactType.CHANGE_SET.value:
                artifact = self.runtime.artifacts.latest(
                    project.id, ArtifactType.CHANGE_SET, Stage.DEVELOPMENT
                )
                break
        if artifact is None:
            return "", ""
        approval = ApprovalService(self.db).request(
            project_id=project.id,
            stage=Stage.DEVELOPMENT.value,
            gate=CHAT_GATE,
            artifact=artifact,
            agent_key=agent_key,
            summary=f"{agent_key} proposed {len(outcome.file_changes)} file change(s) in chat",
            meta={
                "origin": "chat",
                "requested_by": user.full_name or user.email,
                "files": [item.get("path", "") for item in outcome.file_changes][:50],
            },
            # A chat proposal is a *side* gate: it must never downgrade the status of the
            # change-set artifact that the workflow already approved.
            mark_artifact=False,
        )
        return approval.id, artifact.path or ""

    @staticmethod
    def _references(outcome) -> list[str]:  # noqa: ANN001
        refs: list[str] = []
        for pair in outcome.trace_pairs or []:
            source = pair.get("source_ref") or pair.get("source")
            target = pair.get("target_ref") or pair.get("target")
            for ref in (source, target):
                if ref and ref not in refs:
                    refs.append(ref)
        for ref in outcome.structured.get("requirement_refs", []) or []:
            if ref not in refs:
                refs.append(ref)
        return refs[:25]

    # ------------------------------------------------------------------ reading
    def history(
        self,
        project_id: str,
        *,
        thread_id: str = "",
        agent_key: str = "",
        limit: int = 100,
    ) -> list[AgentMessage]:
        stmt = select(AgentMessage).where(AgentMessage.project_id == project_id)
        if thread_id:
            stmt = stmt.where(AgentMessage.thread_id == thread_id)
        if agent_key:
            stmt = stmt.where(AgentMessage.agent_key == agent_key)
        stmt = stmt.order_by(desc(AgentMessage.created_at)).limit(limit)
        rows = list(self.db.scalars(stmt))
        rows.reverse()
        return rows

    def threads(self, project_id: str) -> list[dict]:
        rows = self.db.scalars(
            select(AgentMessage)
            .where(AgentMessage.project_id == project_id)
            .order_by(desc(AgentMessage.created_at))
            .limit(300)
        )
        seen: dict[str, dict] = {}
        for row in rows:
            entry = seen.setdefault(row.thread_id, {
                "thread_id": row.thread_id,
                "agent_key": row.agent_key,
                "message_count": 0,
                "last_message_at": row.created_at,
                "last_preview": "",
            })
            entry["message_count"] += 1
            if not entry["last_preview"]:
                entry["last_preview"] = row.content[:120]
        return list(seen.values())

    def agent_directory(self) -> list[dict]:
        """Agents the user can talk to, with their stage and purpose."""
        directory = []
        for key in all_agent_keys():
            spec = get_agent_spec(key)
            directory.append({
                "key": spec.key,
                "name": spec.name,
                "role": spec.role,
                "stage": spec.stage,
                "stage_label": STAGE_LABELS.get(spec.stage, spec.stage),
                "description": spec.description,
                "icon": spec.icon,
                "capabilities": list(spec.capabilities),
            })
        return directory
