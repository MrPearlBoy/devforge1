"""Artifact and workspace endpoints: the generated deliverables and the file tree."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, EditableProjectDep, ProjectDep, Workspace
from app.core.errors import NotFoundError
from app.models.artifact import Artifact
from app.schemas.artifact import (
    ArtifactRead,
    ArtifactSummary,
    ArtifactUpdateRequest,
    ArtifactVersionRead,
    WorkspaceFile,
    WorkspaceFileContent,
    WorkspaceTree,
)
from app.services.artifact_service import ArtifactService
from app.services.project_context import ProjectContextService

router = APIRouter(tags=["artifacts"])

LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".md": "markdown", ".json": "json", ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml", ".txt": "text", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".css": "css", ".html": "html",
    ".mmd": "mermaid", ".sql": "sql", ".sh": "shell", ".env": "dotenv", ".example": "dotenv",
}


def _language(path: str) -> str:
    from pathlib import Path

    suffix = Path(path).suffix.lower()
    if suffix in LANGUAGE_BY_SUFFIX:
        return LANGUAGE_BY_SUFFIX[suffix]
    if Path(path).name.startswith(".env"):
        return "dotenv"
    return "text"


@router.get("/projects/{project_id}/artifacts", response_model=list[ArtifactSummary],
            summary="Artifacts produced for a project")
def list_artifacts(project: ProjectDep, db: DbSession, stage: str | None = None,
                   artifact_type: str | None = None) -> list[ArtifactSummary]:
    rows = ArtifactService(db).list_for_project(project.id, stage=stage,
                                                artifact_type=artifact_type)
    return [ArtifactSummary.model_validate(row) for row in rows]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactRead, summary="Artifact detail")
def get_artifact(artifact_id: str, db: DbSession, user: CurrentUser) -> ArtifactRead:
    artifact = ArtifactService(db).get(artifact_id)
    if artifact is None:
        raise NotFoundError("Artifact not found.")
    from app.services.project_service import ProjectService

    project = ProjectService(db).get(artifact.project_id)
    ProjectService(db).ensure_access(project, user)
    return ArtifactRead.model_validate(artifact)


@router.put("/artifacts/{artifact_id}", response_model=ArtifactRead,
            summary="Edit an artifact (creates a new version)")
def update_artifact(artifact_id: str, payload: ArtifactUpdateRequest, db: DbSession,
                    user: CurrentUser) -> ArtifactRead:
    service = ArtifactService(db)
    artifact = service.get(artifact_id)
    if artifact is None:
        raise NotFoundError("Artifact not found.")
    from app.services.project_service import ProjectService

    project = ProjectService(db).get(artifact.project_id)
    ProjectService(db).ensure_access(project, user, write=True)

    if payload.content is not None:
        artifact = service.apply_human_edit(artifact, payload.content, user=user,
                                            change_reason=payload.change_reason)
    if payload.title:
        artifact.title = payload.title
    if payload.summary is not None:
        artifact.summary = payload.summary
    db.commit()
    db.refresh(artifact)
    return ArtifactRead.model_validate(artifact)


@router.get("/artifacts/{artifact_id}/versions", response_model=list[ArtifactVersionRead],
            summary="Version history of an artifact")
def artifact_versions(artifact_id: str, db: DbSession, user: CurrentUser) -> list[ArtifactVersionRead]:
    service = ArtifactService(db)
    artifact = service.get(artifact_id)
    if artifact is None:
        raise NotFoundError("Artifact not found.")
    return [ArtifactVersionRead.model_validate(row) for row in service.versions(artifact_id)]


# --------------------------------------------------------------------------- #
# workspace
# --------------------------------------------------------------------------- #
@router.get("/projects/{project_id}/workspace", response_model=WorkspaceTree,
            summary="Generated file tree")
def workspace_tree(project: ProjectDep, db: DbSession, workspace: Workspace) -> WorkspaceTree:
    artifact_rows = db.scalars(
        select(Artifact).where(Artifact.project_id == project.id, Artifact.path != "")
    ).all()
    artifact_by_path = {row.path: row.id for row in artifact_rows}

    groups = workspace.group_tree(project.id)
    payload: dict[str, list[WorkspaceFile]] = {}
    for group, files in groups.items():
        payload[group] = [
            WorkspaceFile(
                path=info.path,
                size=info.size,
                language=info.language or _language(info.path),
                modified_at=info.modified_at,
                artifact_id=artifact_by_path.get(info.path),
            )
            for info in files
        ]
    total = sum(len(files) for files in payload.values())
    return WorkspaceTree(root=str(workspace.project_dir(project.id)), groups=payload,
                         total_files=total)


@router.get("/projects/{project_id}/workspace/file", response_model=WorkspaceFileContent,
            summary="Read a generated file")
def workspace_file(project: ProjectDep, path: str, workspace: Workspace) -> WorkspaceFileContent:
    content, truncated = workspace.read_text(project.id, path)
    info = workspace.stat(project.id, path)
    return WorkspaceFileContent(
        path=info.path,
        content=content,
        size=info.size,
        language=_language(info.path),
        truncated=truncated,
    )


@router.get("/projects/{project_id}/context", summary="Agent context preview (memory + retrieval)")
def project_context(project: ProjectDep, db: DbSession, query: str = "",
                    agent_key: str = "developer", stage: str = "") -> dict:
    """What the agents actually see: project memory, artifacts, retrieved knowledge.

    Useful for explaining retrieval and for debugging live-mode behaviour.
    """
    context = ProjectContextService(db).build_agent_context(
        project.id,
        agent_key=agent_key,
        stage=stage or project.current_stage,
        query=query,
        include_source=False,
    )
    return {
        "project": context.project,
        "stage": context.stage,
        "instructions": context.instructions,
        "artifacts": {
            key: {"id": value.get("id"), "title": value.get("title"),
                  "type": value.get("type"), "summary": value.get("summary", "")[:400]}
            for key, value in context.artifacts.items()
        },
        "memory": {
            "previous_outputs": context.previous_outputs[:5],
            "recent_messages": context.recent_messages[:6],
            "open_tasks": context.open_tasks[:8],
            "test_summary": context.test_summary,
            "security_summary": context.security_summary,
        },
        "retrieval": [
            {
                "source_type": hit.source_type,
                "source_ref": hit.source_ref,
                "chunk_index": hit.chunk_index,
                "score": round(hit.score, 4),
                "text": (hit.content or "")[:500],
            }
            for hit in context.knowledge
        ],
        "prompt_block_preview": context.to_prompt_block()[:4000],
        "fingerprint": context.fingerprint(),
    }
