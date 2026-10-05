"""Base class shared by every DevForge agent.

Contract:

* a concrete agent declares its :class:`AgentSpec`, its output Pydantic schema
  (when it produces structured data) and implements :meth:`build_prompt` plus
  :meth:`mock_payload`;
* :meth:`run` decides between LIVE mode (LLM via the gateway) and MOCK mode
  (deterministic, context-derived payload) — agents never talk to a provider
  directly (Rule 13);
* the returned :class:`AgentOutcome` is what the runtime persists: artifacts,
  execution telemetry and events.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.core.errors import AgentExecutionError
from app.core.logging import get_logger
from app.services.agent_registry import AgentSpec
from app.services.project_context import AgentContext
from app.tools.llm.gateway import LLMGateway

logger = get_logger("devforge.agent")

TSchema = TypeVar("TSchema", bound=BaseModel)


@dataclass
class ArtifactDraft:
    """An artifact an agent wants to publish (persisted by the runtime)."""

    artifact_type: str
    stage: str
    title: str
    content: str
    summary: str = ""
    path: str = ""
    data: dict = field(default_factory=dict)
    trace_refs: list[str] = field(default_factory=list)


@dataclass
class AgentOutcome:
    """Everything one agent invocation produced."""

    agent_key: str
    stage: str
    content: str = ""                      # human readable message / chat reply
    artifacts: list[ArtifactDraft] = field(default_factory=list)
    structured: dict = field(default_factory=dict)
    trace_pairs: list[dict] = field(default_factory=list)
    suggested_tasks: list[dict] = field(default_factory=list)
    file_changes: list[dict] = field(default_factory=list)
    #: Files the agent writes directly (test sources are auxiliary to the product
    #: code, so they do not require the product change-set approval gate).
    auto_apply_files: list[dict] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class BaseAgent(ABC):
    """Common behaviour: prompt assembly, mock/live execution, JSON handling."""

    spec: AgentSpec
    #: Prompt version, recorded with each execution for reproducibility.
    prompt_version = "v1"
    output_schema: type[BaseModel] | None = None
    max_tokens: int = 4096

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    # ------------------------------------------------------------------ prompts
    @abstractmethod
    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        """Build the user prompt for this agent (system prompt is separate)."""

    @abstractmethod
    def system_prompt(self) -> str:
        """Build the system prompt for this agent."""

    @abstractmethod
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        """Turn a (validated) payload into artifacts, trace links and messages."""

    # ----------------------------------------------------------------- execution
    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def stage(self) -> str:
        return self.spec.stage

    def run(self, context: AgentContext, task: str = "") -> AgentOutcome:
        """Execute the agent and return its outcome (never raises raw LLM errors)."""
        prompt = self.build_prompt(context, task)
        system = self.system_prompt()

        if self.output_schema is None:  # narrative-only agent in live mode
            result = self.gateway.generate(
                prompt, system=system, max_tokens=self.max_tokens, task=f"{self.key}:narrative"
            )
            outcome = self.render({"markdown": result.text}, context, task)
            outcome.meta.setdefault("mode", "live")
            outcome.meta.setdefault("usage", result.usage.__dict__)
            return outcome

        structured = self.gateway.generate_structured(
            prompt, self.output_schema, system=system, max_tokens=self.max_tokens,
            task=f"{self.key}:{self.output_schema.__name__}",
        )
        outcome = self.render(structured.value.model_dump(), context, task)
        outcome.meta.setdefault("mode", "live")
        outcome.meta.setdefault("usage", structured.usage.__dict__)
        outcome.meta.setdefault("repaired", structured.repaired)
        return outcome

    def _validate_payload(self, payload: dict) -> dict:
        if self.output_schema is None:
            return payload
        try:
            return self.output_schema.model_validate(payload).model_dump()
        except Exception as exc:  # a bug must be loud
            raise AgentExecutionError(
                f"{self.spec.name} payload failed schema validation.",
                detail={"error": str(exc)[:400]},
            ) from exc

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def to_json(value: Any) -> str:
        return json.dumps(value, indent=2, default=str)

    def _truncate(self, text: str, limit: int = 20000) -> str:
        return text if len(text) <= limit else text[:limit] + "\n... [truncated]"
