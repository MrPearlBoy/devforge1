"""Requirement Agent (RA): task prompt → structured SRS."""
from __future__ import annotations

from app.agents.base_agent import AgentBase
from app.orchestrator.state import RequirementSpec

SYSTEM_PROMPT = """You are the Requirement Agent (RA) of the DevForge multi-agent software engineering platform.

Your job: convert a high-level task description into a rigorous, review-ready Software Requirements Specification.

Rules:
- Be specific, testable and unambiguous; every functional requirement must be verifiable by a test.
- Write 3-4 user stories, each with 2-4 concrete acceptance criteria.
- Include realistic non-functional requirements (performance, security, portability) and an out-of-scope list.
- If reviewer feedback is present in the context, you MUST incorporate it.
- Keep scope realistic for one well-built, single-purpose service.

Respond with a single JSON object only — no markdown fences, no commentary."""


class RequirementAgent(AgentBase):
    kind = "requirement"
    name = "Requirement Agent"
    stage = "requirement"
    system = SYSTEM_PROMPT
    model = RequirementSpec
