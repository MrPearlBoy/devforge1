"""Traceability endpoints: requirement → architecture → code → test → security → docs."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, ProjectDep
from app.core.errors import NotFoundError
from app.schemas.trace import TraceChain, TraceLinkRead, TraceMatrix, TraceNode
from app.services.trace import TraceService

router = APIRouter(tags=["traceability"])


def _link_payload(link) -> TraceLinkRead:  # noqa: ANN001 - TraceLink row or dict
    """Accept either an ORM row or the dict form produced by ``TraceService.matrix``."""
    if isinstance(link, dict):
        data = link
    else:
        data = {
            "id": link.id,
            "source_type": link.source_type,
            "source_ref": link.source_ref,
            "source_label": link.source_label,
            "target_type": link.target_type,
            "target_ref": link.target_ref,
            "target_label": link.target_label,
            "relation": link.relation,
            "confidence": link.confidence,
            "note": link.note,
        }
    return TraceLinkRead(
        id=data["id"],
        source_type=data["source_type"],
        source_ref=data["source_ref"],
        source_label=data.get("source_label", ""),
        target_type=data["target_type"],
        target_ref=data["target_ref"],
        target_label=data.get("target_label", ""),
        relation=data.get("relation", "relates_to"),
        confidence=float(data.get("confidence") or 1.0),
        note=data.get("note") or "",
    )


@router.get("/projects/{project_id}/trace", response_model=TraceMatrix,
            summary="Full traceability matrix with coverage and gaps")
def trace_matrix(project: ProjectDep, db: DbSession) -> TraceMatrix:
    data = TraceService(db).matrix(project.id)
    return TraceMatrix(
        nodes=[TraceNode(**node) for node in data["nodes"]],
        links=[_link_payload(link) for link in data["links"]],
        coverage=data["coverage"],
        gap_report=data["gap_report"],
    )


@router.get("/projects/{project_id}/trace/links", response_model=list[TraceLinkRead],
            summary="Raw trace links")
def trace_links(project: ProjectDep, db: DbSession, ref: str = "") -> list[TraceLinkRead]:
    service = TraceService(db)
    if ref:
        links = service.downstream(project.id, ref) + service.upstream(project.id, ref)
        seen: dict[str, object] = {}
        for link in links:
            seen[link.id] = link
        return [_link_payload(link) for link in seen.values()]
    rows = service.links_for_project(project.id, limit=2000)
    return [_link_payload(row) for row in rows]


@router.get("/projects/{project_id}/trace/ref/{ref:path}", response_model=TraceChain,
            summary="Everything upstream and downstream of one reference")
def trace_chain(project: ProjectDep, ref: str, db: DbSession, depth: int = Query(default=4, ge=1, le=8)) -> TraceChain:
    service = TraceService(db)
    matrix = service.matrix(project.id)
    node = next((item for item in matrix["nodes"] if item["ref"] == ref), None)
    if node is None:
        raise NotFoundError(
            f"No traced artifact found for '{ref}'. Try a reference such as REQ-001 or "
            "ARCH-001.",
        )
    links = {link.id: link for link in service.downstream(project.id, ref, depth=depth)}
    for link in service.upstream(project.id, ref, depth=depth):
        links.setdefault(link.id, link)

    reachable = {node["ref"]}
    for link in links.values():
        reachable.add(link.source_ref)
        reachable.add(link.target_ref)
    nodes = [TraceNode(**item) for item in matrix["nodes"] if item["ref"] in reachable]
    return TraceChain(
        root=TraceNode(**node),
        links=[_link_payload(link) for link in links.values()],
        nodes=nodes,
    )


@router.get("/projects/{project_id}/trace/coverage", summary="Coverage percentages only")
def trace_coverage(project: ProjectDep, db: DbSession) -> dict:
    matrix = TraceService(db).matrix(project.id)
    return {"coverage": matrix["coverage"], "gap_report": matrix["gap_report"]}
