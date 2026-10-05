"""Ollama provider for fully local inference (no API key required)."""
from __future__ import annotations

from collections.abc import Iterator, Sequence

import httpx

from app.core.errors import LLMError
from app.tools.llm.base import LLMProvider, LLMResult, LLMUsage


class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_json_mode = True

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        kwargs.setdefault("model", "llama3.1")
        super().__init__(**kwargs)
        self.base_url = (self.base_url or "http://localhost:11434").rstrip("/")
        self.embedding_model = self.embedding_model or "nomic-embed-text"

    def generate(self, prompt, *, system="", temperature=None, max_tokens=None,
                 json_mode=False) -> LLMResult:
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": max_tokens or self.max_tokens,
            },
        }
        if system:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.base_url}/api/generate", json=payload)
                if response.status_code >= 400:
                    raise LLMError("Ollama rejected the request.",
                                   detail={"status": response.status_code})
                data = response.json()
        except httpx.RequestError as exc:
            raise LLMError(
                "Could not reach the local Ollama server — is it running?",
                detail={"base_url": self.base_url},
            ) from exc
        return LLMResult(
            text=data.get("response", ""),
            model=data.get("model", self.model),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
                completion_tokens=int(data.get("eval_count", 0) or 0),
                total_tokens=int(data.get("prompt_eval_count", 0) or 0)
                + int(data.get("eval_count", 0) or 0),
            ),
            finish_reason=data.get("done_reason", ""),
        )

    def stream(self, prompt, *, system="", **kwargs) -> Iterator[str]:  # noqa: ANN003
        yield self.generate(prompt, system=system, **kwargs).text

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        try:
            with httpx.Client(timeout=self.timeout) as client:
                for text in texts:
                    response = client.post(
                        f"{self.base_url}/api/embeddings",
                        json={"model": self.embedding_model, "prompt": text},
                    )
                    response.raise_for_status()
                    vectors.append(response.json().get("embedding", []))
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError("Ollama embedding request failed.") from exc
        return vectors
