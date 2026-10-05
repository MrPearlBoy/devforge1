"""Provider clients, lenient JSON parsing and the provider factory."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from app.core.config import get_settings
from app.llm.mock_templates import (
    mock_architecture,
    mock_code,
    mock_docs,
    mock_requirement,
    mock_tests,
)

log = logging.getLogger("devforge.llm")


# --------------------------------------------------------------------------
# Lenient JSON extraction (LLMs love to wrap JSON in prose or code fences)
# --------------------------------------------------------------------------
def parse_json_lenient(text: str) -> tuple[Optional[Any], Optional[str]]:
    """Extract the first plausible JSON object from ``text``.

    Returns ``(data, None)`` on success or ``(None, error)`` on failure.
    """
    if not text:
        return None, "empty response"
    text = text.strip()
    candidates: list[str] = []

    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())
    candidates.append(text)

    # first balanced top-level object (string-aware brace scan)
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start : i + 1])
                        break

    last_err: Optional[str] = None
    for cand in candidates:
        try:
            return json.loads(cand), None
        except json.JSONDecodeError as exc:
            last_err = str(exc)
    return None, last_err or "no valid JSON object found"


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
class LLMClient:
    """Base client. Subclasses implement :meth:`complete`."""

    name = "base"

    def __init__(self, timeout: float = 120.0) -> None:
        self.timeout = timeout

    async def complete(self, system: str, user: str, kind: str = "generic") -> str:
        raise NotImplementedError


class OpenAICompatClient(LLMClient):
    """OpenAI + any OpenAI-compatible endpoint (Groq, Together, ...)."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str, timeout: float = 120.0) -> None:
        super().__init__(timeout)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def complete(self, system: str, user: str, kind: str = "generic") -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if kind != "generic":
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str, model: str, timeout: float = 120.0) -> None:
        super().__init__(timeout)
        self.name = "anthropic"
        self.api_key = api_key
        self.model = model

    async def complete(self, system: str, user: str, kind: str = "generic") -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 8192,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            return "".join(block.get("text", "") for block in data.get("content", []))


class MockProvider(LLMClient):
    """Deterministic offline LLM.

    The agent embeds a single-line ``CONTEXT_JSON:`` block in the prompt;
    this provider parses it and returns a schema-conformant JSON document
    generated by the deterministic templates in :mod:`app.llm.mock_templates`.
    """

    name = "mock"

    _GENERATORS = {
        "requirement": mock_requirement,
        "architecture": mock_architecture,
        "code": mock_code,
        "tests": mock_tests,
        "docs": mock_docs,
    }

    async def complete(self, system: str, user: str, kind: str = "generic") -> str:
        generator = self._GENERATORS.get(kind)
        if generator is None:
            raise ValueError(f"mock provider has no deterministic generator for kind '{kind}'")
        ctx = self._parse_context(user)
        return json.dumps(generator(ctx), ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_context(user: str) -> dict[str, Any]:
        m = re.search(r"CONTEXT_JSON:\n(\{.*\})", user)
        if not m:
            return {}
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


# --------------------------------------------------------------------------
# Factory with fallback chain
# --------------------------------------------------------------------------
def create_llm() -> LLMClient:
    """Instantiate the best available provider.

    * ``LLM_PROVIDER=mock``  → always the deterministic mock.
    * ``LLM_PROVIDER=auto``  → first configured key (OpenAI → Groq → Anthropic),
      falling back to the mock when none is configured.
    * explicit provider name → that provider if a key exists, else fallback
      to the mock (the "prompt fallback" behaviour).
    """
    s = get_settings()
    pref = (s.llm_provider or "auto").lower()

    candidates: list[LLMClient] = []
    if pref in ("auto", "openai") and s.openai_api_key:
        candidates.append(
            OpenAICompatClient("openai", "https://api.openai.com/v1", s.openai_api_key, s.openai_model, s.llm_timeout)
        )
    if pref in ("auto", "groq") and s.groq_api_key:
        candidates.append(
            OpenAICompatClient("groq", "https://api.groq.com/openai/v1", s.groq_api_key, s.groq_model, s.llm_timeout)
        )
    if pref in ("auto", "anthropic") and s.anthropic_api_key:
        candidates.append(AnthropicClient(s.anthropic_api_key, s.anthropic_model, s.llm_timeout))

    if pref == "mock":
        log.info("LLM provider: mock (deterministic offline mode)")
        return MockProvider()
    if not candidates:
        log.warning(
            "no LLM API key found for provider '%s' — falling back to the deterministic mock provider "
            "(set OPENAI_API_KEY / GROQ_API_KEY / ANTHROPIC_API_KEY in backend/.env to use a real model)",
            pref,
        )
        return MockProvider()
    chosen = candidates[0]
    log.info("LLM provider: %s (model=%s)", chosen.name, getattr(chosen, "model", "?"))
    return chosen
