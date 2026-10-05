"""Structured output contract of the Security Agent (LLM review part)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SecurityObservation(BaseModel):
    severity: str = Field(default="MEDIUM", description="CRITICAL | HIGH | MEDIUM | LOW | INFO")
    category: str = ""
    title: str
    description: str
    file_path: str = ""
    line: int | None = None
    evidence: str = ""
    recommendation: str = ""


class SecurityReview(BaseModel):
    """Qualitative review that complements the deterministic rule scan."""

    summary: str = ""
    observations: list[SecurityObservation] = Field(default_factory=list)
    controls_present: list[str] = Field(default_factory=list)
    false_positive_candidates: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
