"""Traceability schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TraceNode(BaseModel):
    ref: str
    type: str
    label: str = ""
    artifact_id: str | None = None


class TraceLinkRead(BaseModel):
    id: str
    source_type: str
    source_ref: str
    source_label: str
    target_type: str
    target_ref: str
    target_label: str
    relation: str
    confidence: float
    note: str


class TraceChain(BaseModel):
    """Requirement -> architecture -> code -> test -> security -> documentation."""

    root: TraceNode
    links: list[TraceLinkRead] = Field(default_factory=list)
    nodes: list[TraceNode] = Field(default_factory=list)


class TraceMatrix(BaseModel):
    nodes: list[TraceNode] = Field(default_factory=list)
    links: list[TraceLinkRead] = Field(default_factory=list)
    coverage: dict = Field(default_factory=dict)
    gap_report: list[str] = Field(default_factory=list)
