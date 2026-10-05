"""Traceability service — links requirements to the artifacts that realise them.

Reference grammar (stable, human readable, stored in ``trace_links``):

    REQU-001 / REQ-001   requirement
    ARCH-003             architecture component
    CODE app/main.py     source file
    TEST tests/test_auth.py::test_login
    SEC-AUTH-001         security check / finding
    DOC README.md        documentation section
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import TraceNodeType
from app.models.trace import TraceLink

logger = get_logger("devforge.trace")

SEVERITY_RANK = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]


class TraceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ writes
    def link(
        self,
        *,
        project_id: str,
        source_type: TraceNodeType | str,
        source_ref: str,
        target_type: TraceNodeType | str,
        target_ref: str,
        relation: str = "implements",
        source_label: str = "",
        target_label: str = "",
        artifact_id: str | None = None,
        confidence: float = 1.0,
        note: str = "",
    ) -> TraceLink | None:
        source_ref = (source_ref or "").strip()
        target_ref = (target_ref or "").strip()
        if not source_ref or not target_ref:
            return None
        existing = self.db.scalars(
            select(TraceLink).where(
                TraceLink.project_id == project_id,
                TraceLink.source_ref == source_ref,
                TraceLink.target_ref == target_ref,
                TraceLink.relation == relation,
            )
        ).first()
        if existing:
            existing.source_label = source_label or existing.source_label
            existing.target_label = target_label or existing.target_label
            self.db.commit()
            return existing
        link = TraceLink(
            project_id=project_id,
            source_type=str(source_type),
            source_ref=source_ref[:160],
            source_label=source_label[:400],
            target_type=str(target_type),
            target_ref=target_ref[:160],
            target_label=target_label[:400],
            relation=relation,
            artifact_id=artifact_id,
            confidence=confidence,
            note=note[:400],
        )
        self.db.add(link)
        self.db.commit()
        self.db.refresh(link)
        return link

    def link_many(self, project_id: str, pairs: list[dict]) -> int:
        count = 0
        for pair in pairs:
            if self.link(project_id=project_id, **pair):
                count += 1
        return count

    def clear_project(self, project_id: str) -> int:
        links = list(self.db.scalars(select(TraceLink).where(TraceLink.project_id == project_id)))
        for link in links:
            self.db.delete(link)
        self.db.commit()
        return len(links)

    # ------------------------------------------------------------------- reads
    def links_for_project(self, project_id: str, *, source_ref: str | None = None,
                          target_ref: str | None = None) -> list[TraceLink]:
        stmt = select(TraceLink).where(TraceLink.project_id == project_id)
        if source_ref:
            stmt = stmt.where(TraceLink.source_ref == source_ref)
        if target_ref:
            stmt = stmt.where(TraceLink.target_ref == target_ref)
        return list(self.db.scalars(stmt))

    def upstream(self, project_id: str, ref: str, *, depth: int = 4) -> list[TraceLink]:
        """Walk from a node back to the requirements that motivated it."""
        frontier = {ref}
        seen: set[str] = set()
        collected: list[TraceLink] = []
        for _ in range(depth):
            next_frontier: set[str] = set()
            for link in self.links_for_project(project_id):
                if link.target_ref in frontier and link.source_ref not in seen:
                    seen.add(link.source_ref)
                    collected.append(link)
                    next_frontier.add(link.source_ref)
            if not next_frontier:
                break
            frontier = next_frontier
        return collected

    def downstream(self, project_id: str, ref: str, *, depth: int = 4) -> list[TraceLink]:
        """Walk from a requirement forward to everything that realises it."""
        frontier = {ref}
        seen: set[str] = {ref}
        collected: list[TraceLink] = []
        for _ in range(depth):
            next_frontier: set[str] = set()
            for link in self.links_for_project(project_id):
                if link.source_ref in frontier and link.target_ref not in seen:
                    seen.add(link.target_ref)
                    collected.append(link)
                    next_frontier.add(link.target_ref)
            if not next_frontier:
                break
            frontier = next_frontier
        return collected

    def matrix(self, project_id: str) -> dict:
        """Full trace matrix plus a coverage/gap report for the academic demo."""
        links = self.links_for_project(project_id)
        nodes: dict[tuple[str, str], dict] = {}
        for link in links:
            nodes[(link.source_type, link.source_ref)] = {
                "ref": link.source_ref, "type": link.source_type, "label": link.source_label
            }
            nodes[(link.target_type, link.target_ref)] = {
                "ref": link.target_ref, "type": link.target_type, "label": link.target_label
            }

        forward: dict[str, set[str]] = defaultdict(set)
        for link in links:
            forward[link.source_ref].add(link.target_ref)

        def reachable(start: str, depth: int = 6) -> set[str]:
            frontier, seen = {start}, {start}
            for _ in range(depth):
                nxt = set()
                for ref in frontier:
                    for target in forward.get(ref, set()):
                        if target not in seen:
                            seen.add(target)
                            nxt.add(target)
                if not nxt:
                    break
                frontier = nxt
            return seen

        requirements = [n for (t, _), n in nodes.items() if t == TraceNodeType.REQUIREMENT.value]
        coverage = {
            "requirements": len(requirements),
            "with_architecture": 0,
            "with_code": 0,
            "with_tests": 0,
            "with_security_check": 0,
            "with_documentation": 0,
        }
        gaps: list[str] = []
        for requirement in requirements:
            reach = reachable(requirement["ref"])
            types = {nodes[(t, r)]["type"] for (t, r) in nodes if r in reach for t in [t]}
            has = {
                "arch": TraceNodeType.ARCHITECTURE.value in types,
                "code": TraceNodeType.CODE.value in types,
                "test": TraceNodeType.TEST.value in types,
                "sec": TraceNodeType.SECURITY.value in types,
                "doc": TraceNodeType.DOCUMENTATION.value in types,
            }
            coverage["with_architecture"] += int(has["arch"])
            coverage["with_code"] += int(has["code"])
            coverage["with_tests"] += int(has["test"])
            coverage["with_security_check"] += int(has["sec"])
            coverage["with_documentation"] += int(has["doc"])
            missing = [name for name, present in has.items() if not present]
            if missing:
                gaps.append(
                    f"{requirement['ref']} ({requirement['label'][:60]}) has no "
                    f"{', '.join(missing)} linkage yet."
                )

        total = max(1, len(requirements))
        coverage["percent"] = {
            key: round(100 * coverage[key] / total)
            for key in ("with_architecture", "with_code", "with_tests",
                        "with_security_check", "with_documentation")
        }
        return {
            "nodes": list(nodes.values()),
            "links": [
                {
                    "id": link.id,
                    "source_type": link.source_type, "source_ref": link.source_ref,
                    "source_label": link.source_label, "target_type": link.target_type,
                    "target_ref": link.target_ref, "target_label": link.target_label,
                    "relation": link.relation, "confidence": link.confidence, "note": link.note,
                }
                for link in links
            ],
            "coverage": coverage,
            "gap_report": gaps[:25],
        }
