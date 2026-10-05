"""Provider interface for the LLM Gateway.

Agents never import a vendor SDK: they only see :class:`app.tools.llm.gateway.LLMGateway`.
Adding a provider means implementing :class:`LLMProvider` and registering it in the
factory — no agent changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def merge(self, other: "LLMUsage") -> "LLMUsage":
        return LLMUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


@dataclass
class LLMResult:
    text: str
    model: str = ""
    provider: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str = ""
    raw: dict = field(default_factory=dict)


class LLMProvider(ABC):
    """Minimal chat/embedding contract every provider must satisfy."""

    name = "abstract"
    supports_json_mode = False

    def __init__(self, *, api_key: str = "", model: str = "", base_url: str = "",
                 temperature: float = 0.2, max_tokens: int = 4096, timeout: int = 120) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.embedding_model = ""

    # ------------------------------------------------------------------ chat
    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        """Single-turn completion."""

    def stream(self, prompt: str, *, system: str = "", **kwargs) -> Iterator[str]:  # noqa: ANN003
        """Streaming completion. Providers may fall back to a single chunk."""
        yield self.generate(prompt, system=system, **kwargs).text

    # ------------------------------------------------------------- embeddings
    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""

    # ------------------------------------------------------------------ health
    def health(self) -> dict:
        return {"provider": self.name, "model": self.model, "configured": bool(self.api_key)}
