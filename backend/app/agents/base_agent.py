"""Agent base class: prompt assembly, LLM call, lenient JSON parsing,
schema validation with one corrective re-prompt on failure."""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import AgentOutputError
from app.llm.client import LLMClient, parse_json_lenient

M = TypeVar("M", bound=BaseModel)

#: emit(event_type, message, payload) — provided by the workflow engine
EmitFn = Callable[..., Awaitable[None]]


class AgentBase:
    """Deterministic, schema-bound agent.

    Subclasses set ``kind`` (mock-provider hook), ``system`` (prompt
    template) and ``model`` (Pydantic output schema).
    """

    kind: str = "generic"
    name: str = "Agent"
    stage: str = ""
    system: str = ""
    model: Optional[Type[BaseModel]] = None

    def build_user_prompt(self, ctx: dict[str, Any]) -> str:
        schema = json.dumps(self.model.model_json_schema(), indent=2) if self.model else "{}"
        context_line = json.dumps(ctx, ensure_ascii=False, sort_keys=True)
        return (
            "Produce the agent output now.\n"
            "Respond with ONLY one valid JSON object — no markdown fences, no commentary.\n"
            "The JSON object must conform exactly to this schema:\n"
            f"{schema}\n\n"
            "Input context (JSON):\n"
            "CONTEXT_JSON:\n"
            f"{context_line}\n"
        )

    def build_feedback_prompt(self, ctx: dict[str, Any], problem: str) -> str:
        context_line = json.dumps(ctx, ensure_ascii=False, sort_keys=True)
        return (
            "Your previous response was unusable. Problem: "
            f"{problem[:1500]}\n"
            "Respond again with ONLY one valid JSON object conforming to the schema.\n"
            "CONTEXT_JSON:\n"
            f"{context_line}\n"
        )

    async def run(self, ctx: dict[str, Any], emit: EmitFn, client: LLMClient) -> BaseModel:
        """Run the agent: prompt → LLM → parse → validate (1 retry) → model."""
        await emit("agent", f"{self.name} started", {"agent": self.name, "stage": self.stage, "kind": self.kind})
        if self.model is None:
            raise AgentOutputError(f"{self.name}: no output schema defined")

        prompt = self.build_user_prompt(ctx)
        raw = await client.complete(system=self.system, user=prompt, kind=self.kind)
        data, err = parse_json_lenient(raw)

        if data is None:
            await emit("warn", f"{self.name} returned unparseable output — re-prompting", {"error": str(err)[:300]})
            raw = await client.complete(system=self.system, user=self.build_feedback_prompt(ctx, str(err)), kind=self.kind)
            data, err = parse_json_lenient(raw)
            if data is None:
                raise AgentOutputError(f"{self.name}: unparseable LLM output after re-prompt: {err}")

        try:
            result = self.model.model_validate(data)
        except ValidationError as exc:
            await emit("warn", f"{self.name} output failed schema validation — re-prompting", {"errors": str(exc)[:500]})
            raw = await client.complete(system=self.system, user=self.build_feedback_prompt(ctx, str(exc)), kind=self.kind)
            data, err = parse_json_lenient(raw)
            if data is None:
                raise AgentOutputError(f"{self.name}: unparseable LLM output after re-prompt: {err}")
            result = self.model.model_validate(data)  # raises AgentOutputError? no — raise wrapped
        await emit("agent", f"{self.name} produced schema-conformant output", {"agent": self.name, "stage": self.stage})
        return result
