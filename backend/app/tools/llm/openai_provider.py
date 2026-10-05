"""OpenAI-compatible chat/embeddings provider.

Works with OpenAI itself, Azure OpenAI deployments, and any gateway exposing the
`/chat/completions` + `/embeddings` contract (vLLM, LiteLLM, Together, Groq,
OpenRouter, LM Studio...).  Configure with ``LLM_BASE_URL``.
"""
from __future__ import annotations

from collections.abc import Iterator, Sequence

import httpx

from app.core.errors import LLMError
from app.core.logging import get_logger
from app.tools.llm.base import LLMProvider, LLMResult, LLMUsage

logger = get_logger("devforge.llm.openai")


class OpenAIProvider(LLMProvider):
    name = "openai"
    supports_json_mode = True

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        self.embedding_model = self.embedding_model or "text-embedding-3-small"

    # ------------------------------------------------------------------ utils
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, prompt: str, system: str, *, temperature, max_tokens, json_mode) -> dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _usage(data: dict) -> LLMUsage:
        usage = data.get("usage") or {}
        return LLMUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
        )

    # ------------------------------------------------------------------- chat
    def generate(self, prompt, *, system="", temperature=None, max_tokens=None,
                 json_mode=False) -> LLMResult:
        if not self.api_key:
            raise LLMError("No LLM_API_KEY configured for the OpenAI provider.")
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(prompt, system, temperature=temperature,
                                max_tokens=max_tokens, json_mode=json_mode)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=self._headers(), json=payload)
                if response.status_code >= 400:
                    raise LLMError(
                        "The language model provider rejected the request.",
                        detail={"status": response.status_code, "endpoint": "chat/completions"},
                    )
                data = response.json()
        except httpx.RequestError as exc:
            raise LLMError(f"Could not reach the LLM provider: {exc.__class__.__name__}") from exc

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return LLMResult(
            text=message.get("content") or "",
            model=data.get("model", self.model),
            provider=self.name,
            usage=self._usage(data),
            finish_reason=choice.get("finish_reason", ""),
        )

    def stream(self, prompt, *, system="", **kwargs) -> Iterator[str]:  # noqa: ANN003
        if not self.api_key:
            raise LLMError("No LLM_API_KEY configured for the OpenAI provider.")
        payload = self._payload(prompt, system, temperature=kwargs.get("temperature"),
                                max_tokens=kwargs.get("max_tokens"), json_mode=False)
        payload["stream"] = True
        import json

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("POST", f"{self.base_url}/chat/completions",
                                   headers=self._headers(), json=payload) as response:
                    for line in response.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            delta = json.loads(chunk)["choices"][0].get("delta", {})
                        except (ValueError, KeyError, IndexError):
                            continue
                        if delta.get("content"):
                            yield delta["content"]
        except httpx.RequestError as exc:
            raise LLMError(f"Streaming failed: {exc.__class__.__name__}") from exc

    # ------------------------------------------------------------- embeddings
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.api_key:
            raise LLMError("No LLM_API_KEY configured for embeddings.")
        if not texts:
            return []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/embeddings",
                    headers=self._headers(),
                    json={"model": self.embedding_model, "input": list(texts)},
                )
                if response.status_code >= 400:
                    raise LLMError("Embedding request failed.",
                                   detail={"status": response.status_code})
                data = response.json()
        except httpx.RequestError as exc:
            raise LLMError(f"Could not reach the embedding provider: {exc.__class__.__name__}") from exc
        return [item.get("embedding", []) for item in data.get("data", [])]
