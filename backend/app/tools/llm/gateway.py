"""LLMGateway — the single entry point every agent uses to talk to a model.

Responsibilities:

* provider abstraction (no agent imports a vendor SDK)
* structured output generation with JSON extraction and one self-repair retry
* token accounting surfaced to :class:`AgentExecution` records
* clear mock/live mode signalling
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.core.errors import LLMError
from app.core.logging import get_logger
from app.tools.llm.base import LLMProvider, LLMResult, LLMUsage

logger = get_logger("devforge.llm")

TModel = TypeVar("TModel", bound=BaseModel)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@dataclass
class StructuredResult:
    value: BaseModel
    raw_text: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    model: str = ""
    repaired: bool = False


def extract_json(text: str) -> dict | list | None:
    """Best-effort extraction of a JSON object/array from model output."""
    if not text:
        return None
    candidates: list[str] = []
    for match in _JSON_FENCE.findall(text):
        candidates.append(match.strip())
    candidates.append(text.strip())
    # balanced-brace scan for the outermost object
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start:index + 1])
                    break
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None


class LLMGateway:
    """Provider-agnostic model gateway."""

    def __init__(self, provider: LLMProvider, *, mode: str = "live") -> None:
        self.provider = provider
        self.mode = mode
        self.usage_total = LLMUsage()

    # ------------------------------------------------------------------ basics
    @property
    def is_mock(self) -> bool:
        return self.mode == "mock"

    @property
    def model(self) -> str:
        return getattr(self.provider, "model", "")

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", "unknown")

    @property
    def embedding_model(self) -> str:
        return getattr(self.provider, "embedding_model", "")

    def info(self) -> dict:
        return {
            "provider": self.provider_name,
            "model": self.model,
            "embedding_model": self.embedding_model,
            "mode": self.mode,
        }

    # -------------------------------------------------------------- generation
    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
        task: str = "",
    ) -> LLMResult:
        logger.debug("LLM generate task=%s provider=%s mode=%s", task, self.provider_name, self.mode)
        try:
            result = self.provider.generate(
                prompt, system=system, temperature=temperature,
                max_tokens=max_tokens, json_mode=json_mode,
            )
        except LLMError:
            raise
        except Exception as exc:  # provider SDK/transport surprises
            raise LLMError(f"LLM request failed: {exc.__class__.__name__}") from exc
        self.usage_total = self.usage_total.merge(result.usage)
        return result

    def generate_structured(
        self,
        prompt: str,
        schema: type[TModel],
        *,
        system: str = "",
        max_tokens: int | None = None,
        task: str = "",
        repair_attempts: int = 1,
    ) -> StructuredResult:
        """Ask for JSON matching ``schema``, validate it, repair once if needed."""
        schema_json = json.dumps(schema.model_json_schema(), indent=2)[:6000]
        instruction = (
            f"{prompt}\n\n"
            "## Output format (mandatory)\n"
            "Respond with a single JSON object and nothing else — no prose, no code fences.\n"
            "It must validate against this JSON Schema:\n"
            f"```json\n{schema_json}\n```"
        )
        result = self.generate(
            instruction, system=system, max_tokens=max_tokens, json_mode=True, task=task
        )
        parsed = extract_json(result.text)
        usage = result.usage
        raw_text = result.text

        for attempt in range(repair_attempts + 1):
            if parsed is not None:
                try:
                    return StructuredResult(
                        value=schema.model_validate(parsed),
                        raw_text=raw_text,
                        usage=usage,
                        model=result.model,
                        repaired=attempt > 0,
                    )
                except ValidationError as exc:
                    problem = exc.errors()[:5]
                    logger.warning("Structured output failed validation (attempt %s): %s",
                                   attempt, problem)
            else:
                problem = "response was not valid JSON"

            if attempt >= repair_attempts:
                break
            repair_prompt = (
                f"{instruction}\n\n## Correction\nYour previous answer was rejected: {problem}\n"
                "Return ONLY the corrected JSON object."
            )
            try:
                retry = self.generate(repair_prompt, system=system, json_mode=True,
                                      task=f"{task}:repair")
            except LLMError:
                break
            usage = usage.merge(retry.usage)
            raw_text = retry.text
            parsed = extract_json(retry.text)

        raise LLMError(
            "The model did not return valid structured output for this task.",
            detail={"task": task, "schema": schema.__name__},
        )

    def stream(self, prompt: str, *, system: str = "", **kwargs) -> Iterator[str]:  # noqa: ANN003
        for chunk in self.provider.stream(prompt, system=system, **kwargs):
            yield chunk

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            return self.provider.embed(list(texts))
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"Embedding request failed: {exc.__class__.__name__}") from exc
