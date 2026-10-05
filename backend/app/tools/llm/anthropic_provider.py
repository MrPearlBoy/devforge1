"""Anthropic Messages API provider (embeddings fall back to the mock hashing model)."""
from __future__ import annotations

from collections.abc import Iterator, Sequence

import httpx

from app.core.errors import LLMError
from app.tools.llm.base import LLMProvider, LLMResult, LLMUsage
from app.tools.llm.mock_provider import MockProvider

DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_json_mode = False

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "https://api.anthropic.com/v1").rstrip("/")
        self._fallback_embeddings = MockProvider(embedding_dim=256)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": DEFAULT_ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    def generate(self, prompt, *, system="", temperature=None, max_tokens=None,
                 json_mode=False) -> LLMResult:
        if not self.api_key:
            raise LLMError("No LLM_API_KEY configured for the Anthropic provider.")
        payload = {
            "model": self.model or "claude-3-5-sonnet-latest",
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/messages", headers=self._headers(), json=payload)
                if response.status_code >= 400:
                    raise LLMError("The language model provider rejected the request.",
                                   detail={"status": response.status_code, "provider": "anthropic"})
                data = response.json()
        except httpx.RequestError as exc:
            raise LLMError(f"Could not reach the Anthropic API: {exc.__class__.__name__}") from exc

        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            model=data.get("model", self.model),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(usage.get("input_tokens", 0) or 0),
                completion_tokens=int(usage.get("output_tokens", 0) or 0),
                total_tokens=int(usage.get("input_tokens", 0) or 0)
                + int(usage.get("output_tokens", 0) or 0),
            ),
            finish_reason=data.get("stop_reason", ""),
        )

    def stream(self, prompt, *, system="", **kwargs) -> Iterator[str]:  # noqa: ANN003
        yield self.generate(prompt, system=system, **kwargs).text

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Anthropic has no public embeddings endpoint — use deterministic fallback."""
        return self._fallback_embeddings.embed(texts)
