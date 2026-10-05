"""ProjectContextService — the shared memory every agent reads before answering.

Implements the context contract required by the specification:

* ``get_project_context``       — project metadata, stage, counts, stack
* ``get_current_artifacts``     — latest artifact per stage/type
* ``get_previous_agent_outputs``— recent agent execution summaries
* ``search_project_knowledge``  — semantically relevant chunks (vector search)
* ``build_context_prompt``      — ready-to-inject markdown context block
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.agent import Task
from app.models.approval import Approval
from app.models.artifact import Artifact
from app.models.conversation import AgentMessage
from app.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    FindingStatus,
    KnowledgeSource,
    MessageRole,
    Stage,
    STAGE_ORDER,
)
from app.models.execution import AgentExecution
from app.models.project import Project
from app.models.security import SecurityFinding
from app.models.testing import TestRun
from app.services.knowledge import KnowledgeService
from app.services.workspace import WorkspaceService
from app.services.vector_store import KnowledgeHit

logger = get_logger("devforge.context")

#: How much of an artifact body is embedded into an agent prompt.
ARTIFACT_EXCERPT_LIMIT = 6000
SOURCE_FILE_LIMIT = 12
WORKSPACE_PATH_RE = re.compile(r"(?<![\w.-])(?:[\w.-]+[\\/])+[\w.-]+")


@dataclass
class AgentContext:
    """Assembled context handed to an agent execution."""

    project_id: str
    project: dict = field(default_factory=dict)
    stage: str = ""
    instructions: str = ""
    artifacts: dict[str, dict] = field(default_factory=dict)
    knowledge: list[KnowledgeHit] = field(default_factory=list)
    previous_outputs: list[dict] = field(default_factory=list)
    recent_messages: list[dict] = field(default_factory=list)
    source_files: dict[str, str] = field(default_factory=dict)
    test_summary: dict = field(default_factory=dict)
    security_summary: dict = field(default_factory=dict)
    open_tasks: list[dict] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        """Render the context as a compact markdown block for the LLM."""
        lines: list[str] = ["## Project context"]
        p = self.project
        lines.append(f"- Project: **{p.get('name', '')}** (stage: `{self.stage}`)")
        if p.get("description"):
            lines.append(f"- Description: {p['description']}")
        if p.get("tech_stack"):
            lines.append(f"- Declared tech stack: {p['tech_stack']}")
        if p.get("requirement_input"):
            lines.append(f"- Original requirement input: {p['requirement_input'][:1200]}")

        if self.instructions:
            lines.append("\n## Human instructions (highest priority)")
            lines.append(self.instructions[:4000])

        if self.artifacts:
            lines.append("\n## Current artifacts")
            for key, artifact in self.artifacts.items():
                excerpt = artifact.get("content", "")[:ARTIFACT_EXCERPT_LIMIT]
                lines.append(
                    f"\n### {artifact.get('title') or key} ({artifact.get('stage')} / "
                    f"{artifact.get('status')}, v{artifact.get('version')})\n{excerpt}"
                )

        if self.source_files:
            lines.append("\n## Relevant source files")
            for path, content in self.source_files.items():
                lines.append(f"\n### {path}\n```\n{content[:4000]}\n```")

        if self.test_summary:
            lines.append(
                f"\n## Latest test run\n- status: {self.test_summary.get('status')}\n"
                f"- passed: {self.test_summary.get('passed')} / failed: {self.test_summary.get('failed')} "
                f"/ errors: {self.test_summary.get('errors')}"
            )
            failures = self.test_summary.get("failures") or []
            if failures:
                lines.append("- failing tests:")
                for item in failures[:10]:
                    lines.append(f"  - `{item.get('name')}` — {item.get('message', '')[:200]}")

        if self.security_summary:
            lines.append(
                f"\n## Latest security scan\n- open findings: {self.security_summary.get('open_total', 0)} "
                f"(crit {self.security_summary.get('critical', 0)}, high {self.security_summary.get('high', 0)})"
            )
            for finding in (self.security_summary.get("top_findings") or [])[:8]:
                lines.append(
                    f"  - [{finding.get('severity')}] {finding.get('title')} "
                    f"({finding.get('file_path')}:{finding.get('line')})"
                )

        if self.knowledge:
            lines.append("\n## Retrieved project knowledge (most relevant chunks)")
            for hit in self.knowledge:
                lines.append(f"- ({hit.source_type}:{hit.source_ref}, score {hit.score}) {hit.content[:600]}")

        if self.previous_outputs:
            lines.append("\n## Previous agent outputs")
            for output in self.previous_outputs[:8]:
                lines.append(f"- {output.get('agent_key')}: {output.get('summary', '')[:400]}")

        if self.open_tasks:
            lines.append("\n## Open tasks")
            for task in self.open_tasks[:12]:
                lines.append(f"- [{task.get('status')}] {task.get('title')}")

        return "\n".join(lines)

    def fingerprint(self) -> dict:
        return {
            "project": self.project.get("id"),
            "stage": self.stage,
            "artifacts": list(self.artifacts.keys()),
            "knowledge_chunks": len(self.knowledge),
            "source_files": list(self.source_files.keys()),
        }


class ProjectContextService:
    """Builds the context object consumed by every agent."""

    def __init__(self, db: Session, *, workspace: WorkspaceService | None = None,
                 knowledge: KnowledgeService | None = None) -> None:
        self.db = db
        self.workspace = workspace or WorkspaceService()
        self.knowledge = knowledge or KnowledgeService()

    # ------------------------------------------------------------------ pieces
    def get_project_context(self, project_id: str) -> dict:
        project = self.db.get(Project, project_id)
        if project is None:
            return {}
        artifact_count = self.db.scalar(
            select(func.count(Artifact.id)).where(Artifact.project_id == project_id)
        ) or 0
        approved = self.db.scalar(
            select(func.count(Artifact.id)).where(
                Artifact.project_id == project_id, Artifact.status == ArtifactStatus.APPROVED.value
            )
        ) or 0
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "requirement_input": project.requirement_input,
            "tech_stack": project.tech_stack,
            "current_stage": project.current_stage,
            "workflow_status": project.workflow_status,
            "stage_status": project.stage_status,
            "progress_percent": project.progress_percent,
            "artifact_count": artifact_count,
            "approved_artifact_count": approved,
            "workspace_path": project.workspace_path,
        }

    def get_current_artifacts(self, project_id: str, *, stages: list[str] | None = None,
                              artifact_types: list[str] | None = None) -> dict[str, dict]:
        """Latest artifact per (stage, type), optionally filtered."""
        stmt = select(Artifact).where(Artifact.project_id == project_id)
        if stages:
            stmt = stmt.where(Artifact.stage.in_(stages))
        if artifact_types:
            stmt = stmt.where(Artifact.type.in_(artifact_types))
        stmt = stmt.order_by(Artifact.stage, Artifact.type, desc(Artifact.version))
        out: dict[str, dict] = {}
        for artifact in self.db.scalars(stmt):
            key = f"{artifact.stage}:{artifact.type}"
            if key in out:  # already kept the highest version
                continue
            out[key] = self._artifact_dict(artifact)
        return out

    def get_approved_artifact(self, project_id: str, artifact_type: ArtifactType | str) -> dict | None:
        stmt = (
            select(Artifact)
            .where(
                Artifact.project_id == project_id,
                Artifact.type == str(artifact_type),
                Artifact.status.in_([ArtifactStatus.APPROVED.value, ArtifactStatus.DRAFT.value]),
            )
            .order_by(desc(Artifact.version))
        )
        artifact = self.db.scalars(stmt).first()
        return self._artifact_dict(artifact) if artifact else None

    def get_previous_agent_outputs(self, project_id: str, *, limit: int = 12) -> list[dict]:
        stmt = (
            select(AgentExecution)
            .where(AgentExecution.project_id == project_id)
            .order_by(desc(AgentExecution.created_at))
            .limit(limit)
        )
        return [
            {
                "agent_key": execution.agent_key,
                "stage": execution.stage,
                "status": execution.status,
                "summary": execution.output_summary,
                "created_at": execution.created_at.isoformat(),
                "trigger": execution.trigger,
            }
            for execution in self.db.scalars(stmt)
        ]

    def get_recent_messages(self, project_id: str, agent_key: str | None = None,
                            limit: int = 12) -> list[dict]:
        stmt = select(AgentMessage).where(AgentMessage.project_id == project_id)
        if agent_key:
            stmt = stmt.where(AgentMessage.agent_key == agent_key)
        stmt = stmt.order_by(desc(AgentMessage.created_at)).limit(limit)
        rows = list(self.db.scalars(stmt))
        return [
            {
                "role": message.role,
                "content": message.content,
                "agent_key": message.agent_key,
                "created_at": message.created_at.isoformat(),
            }
            for message in reversed(rows)
        ]

    def search_project_knowledge(self, project_id: str, query: str, *, limit: int = 8,
                                 source_types: list[str] | None = None) -> list[KnowledgeHit]:
        if not query.strip():
            return []
        try:
            return self.knowledge.search(self.db, project_id=project_id, query=query,
                                         limit=limit, source_types=source_types)
        except Exception as exc:  # retrieval must never break an agent run
            logger.warning("Knowledge search failed: %s", exc)
            return []

    def get_relevant_source_files(self, project_id: str, query: str, *, limit: int = SOURCE_FILE_LIMIT) -> dict[str, str]:
        """Pick source files relevant to the task, falling back to the newest files."""
        files = self.workspace.read_tree(project_id, max_files=60)
        if not files:
            return {}
        selected: dict[str, str] = {}
        requested_paths = {
            match.group().replace("\\", "/").lower()
            for match in WORKSPACE_PATH_RE.finditer(query)
        }
        for path, content in files.items():
            normalized_path = path.replace("\\", "/").lower()
            if any(
                normalized_path == requested
                or normalized_path.endswith(f"/{requested}")
                or requested.endswith(f"/{normalized_path}")
                for requested in requested_paths
            ):
                selected[path] = content
                if len(selected) >= limit:
                    return selected
        if query.strip():
            hits = self.search_project_knowledge(
                project_id, query, limit=limit * 2,
                source_types=[KnowledgeSource.SOURCE_CODE.value, KnowledgeSource.DOCUMENTATION.value],
            )
            for hit in hits:
                if hit.source_ref in files and hit.source_ref not in selected:
                    selected[hit.source_ref] = files[hit.source_ref]
                if len(selected) >= limit:
                    break
        for path, content in files.items():
            if path not in selected:
                selected[path] = content
            if len(selected) >= limit:
                break
        return selected

    def get_test_summary(self, project_id: str) -> dict:
        run = self.db.scalars(
            select(TestRun).where(TestRun.project_id == project_id).order_by(desc(TestRun.created_at))
        ).first()
        if run is None:
            return {}
        failures = [
            {"name": r.name, "message": r.message, "file_path": r.file_path}
            for r in run.results
            if r.status in {"FAILED", "ERROR"}
        ]
        return {
            "id": run.id,
            "status": run.status,
            "total": run.total,
            "passed": run.passed,
            "failed": run.failed,
            "skipped": run.skipped,
            "errors": run.errors,
            "created_at": run.created_at.isoformat(),
            "failures": failures[:12],
        }

    def get_security_summary(self, project_id: str) -> dict:
        rows = list(
            self.db.scalars(
                select(SecurityFinding).where(
                    SecurityFinding.project_id == project_id,
                    SecurityFinding.status != FindingStatus.FALSE_POSITIVE.value,
                )
            )
        )
        summary = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "open_total": 0}
        for finding in rows:
            key = finding.severity.lower()
            summary[key] = summary.get(key, 0) + 1
            if finding.status == FindingStatus.OPEN.value:
                summary["open_total"] += 1
        ranked = sorted(
            [f for f in rows if f.status == FindingStatus.OPEN.value],
            key=lambda f: ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].index(f.severity),
        )
        summary["top_findings"] = [
            {
                "severity": f.severity,
                "title": f.title,
                "file_path": f.file_path,
                "line": f.line,
                "rule_id": f.rule_id,
            }
            for f in ranked[:10]
        ]
        return summary

    def get_open_tasks(self, project_id: str, *, limit: int = 20) -> list[dict]:
        stmt = (
            select(Task)
            .where(Task.project_id == project_id, Task.status.in_(["TODO", "IN_PROGRESS", "BLOCKED"]))
            .order_by(Task.created_at)
            .limit(limit)
        )
        return [
            {"title": t.title, "status": t.status, "priority": t.priority, "stage": t.stage}
            for t in self.db.scalars(stmt)
        ]

    def get_pending_approval(self, project_id: str) -> dict | None:
        approval = self.db.scalars(
            select(Approval)
            .where(Approval.project_id == project_id, Approval.status == ApprovalStatus.PENDING.value)
            .order_by(desc(Approval.created_at))
        ).first()
        if approval is None:
            return None
        return {
            "id": approval.id,
            "stage": approval.stage,
            "gate": approval.gate,
            "artifact_id": approval.artifact_id,
            "requested_by_agent_key": approval.requested_by_agent_key,
            "created_at": approval.created_at.isoformat(),
        }

    # ---------------------------------------------------------------- assembly
    def build_agent_context(
        self,
        project_id: str,
        *,
        agent_key: str,
        stage: str,
        query: str = "",
        instructions: str = "",
        include_source: bool = True,
        include_artifacts: bool = True,
        thread_agent_key: str | None = None,
    ) -> AgentContext:
        """Assemble everything an agent needs for one invocation."""
        context = AgentContext(
            project_id=project_id,
            project=self.get_project_context(project_id),
            stage=stage,
            instructions=instructions,
        )
        if include_artifacts:
            wanted_stages = [s.value for s in STAGE_ORDER]
            # An agent never re-reads its own output as "approved input" — it reads
            # everything produced upstream plus its own previous revision for edits.
            context.artifacts = self.get_current_artifacts(
                project_id,
                stages=wanted_stages,
                artifact_types=[
                    ArtifactType.REQUIREMENTS.value,
                    ArtifactType.ARCHITECTURE.value,
                    ArtifactType.ARCHITECTURE_DIAGRAM.value,
                    ArtifactType.CHANGE_SET.value,
                    ArtifactType.TEST_PLAN.value,
                    ArtifactType.TEST_RESULTS.value,
                    ArtifactType.SECURITY_REPORT.value,
                    ArtifactType.DOCUMENTATION.value,
                ],
            )
        context.knowledge = self.search_project_knowledge(project_id, query or agent_key, limit=6)
        context.previous_outputs = self.get_previous_agent_outputs(project_id, limit=8)
        context.recent_messages = self.get_recent_messages(project_id, thread_agent_key or agent_key, limit=10)
        context.test_summary = self.get_test_summary(project_id)
        context.security_summary = self.get_security_summary(project_id)
        context.open_tasks = self.get_open_tasks(project_id)
        if include_source:
            context.source_files = self.get_relevant_source_files(project_id, query or agent_key)
        return context

    # --------------------------------------------------------------- indexing
    def refresh_index(self, project_id: str) -> dict:
        """Re-index project knowledge (artifacts, files, history)."""
        counts: dict[str, int] = {}
        artifacts = self.db.scalars(
            select(Artifact)
            .where(Artifact.project_id == project_id)
            .order_by(desc(Artifact.updated_at))
            .limit(40)
        ).all()
        for artifact in artifacts:
            if not artifact.content.strip():
                continue
            counts[f"artifact:{artifact.type}"] = self.knowledge.index_text(
                self.db,
                project_id=project_id,
                source_type=self._source_type_for(artifact),
                source_ref=f"artifact:{artifact.id}",
                text=f"# {artifact.title} ({artifact.stage})\n\n{artifact.content}",
                meta={"artifact_id": artifact.id, "type": artifact.type},
            )
        files = self.workspace.read_tree(project_id, max_files=30)
        if files:
            counts["source_files"] = self.knowledge.index_files(
                self.db, project_id=project_id, files=files
            )
        project = self.db.get(Project, project_id)
        if project is not None:
            counts["project_meta"] = self.knowledge.index_text(
                self.db,
                project_id=project_id,
                source_type=KnowledgeSource.PROJECT_META,
                source_ref="project:meta",
                text=(
                    f"# {project.name}\n\n{project.description}\n\n"
                    f"Original requirement:\n{project.requirement_input}"
                ),
                meta={"project_id": project_id},
            )
        logger.info("Refreshed knowledge index for project %s: %s", project_id, counts)
        return counts

    def index_conversation_turn(self, project_id: str, agent_key: str, user_text: str,
                                agent_text: str) -> None:
        try:
            self.knowledge.index_text(
                self.db,
                project_id=project_id,
                source_type=KnowledgeSource.CONVERSATION,
                source_ref=f"conversation:{agent_key}:{user_text[:40]}",
                text=f"Human: {user_text}\n\n{agent_key} agent: {agent_text}",
                meta={"agent_key": agent_key},
            )
        except Exception as exc:  # pragma: no cover - non critical
            logger.debug("Conversation indexing skipped: %s", exc)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _artifact_dict(artifact: Artifact) -> dict:
        return {
            "id": artifact.id,
            "type": artifact.type,
            "stage": artifact.stage,
            "title": artifact.title,
            "summary": artifact.summary,
            "content": artifact.content,
            "data": artifact.data,
            "path": artifact.path,
            "version": artifact.version,
            "status": artifact.status,
            "trace_refs": artifact.trace_refs,
            "produced_by_agent_key": artifact.produced_by_agent_key,
        }

    @staticmethod
    def source_type_for_artifact(artifact: Artifact) -> KnowledgeSource:
        """Public mapping (also used by the runtime for incremental indexing)."""
        return ProjectContextService._source_type_for(artifact)

    @staticmethod
    def _source_type_for(artifact: Artifact) -> KnowledgeSource:
        mapping = {
            ArtifactType.REQUIREMENTS.value: KnowledgeSource.REQUIREMENTS,
            ArtifactType.ARCHITECTURE.value: KnowledgeSource.ARCHITECTURE,
            ArtifactType.ARCHITECTURE_DIAGRAM.value: KnowledgeSource.ARCHITECTURE,
            ArtifactType.TEST_PLAN.value: KnowledgeSource.TEST_RESULTS,
            ArtifactType.TEST_RESULTS.value: KnowledgeSource.TEST_RESULTS,
            ArtifactType.SECURITY_REPORT.value: KnowledgeSource.SECURITY_FINDINGS,
            ArtifactType.DOCUMENTATION.value: KnowledgeSource.DOCUMENTATION,
        }
        return mapping.get(artifact.type, KnowledgeSource.PROJECT_META)
