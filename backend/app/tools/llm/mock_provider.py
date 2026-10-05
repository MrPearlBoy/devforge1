"""Deterministic offline provider used for DEMO/MOCK MODE.

This is deliberately *not* a random text generator: it implements real, local
algorithms so the platform's behaviour is coherent without any external API:

* :meth:`MockProvider.embed` uses the hashing trick (feature hashing) to turn
  text into a normalised bag-of-words vector — genuine lexical similarity, so
  vector retrieval genuinely ranks relevant project context higher.
* :meth:`MockProvider.generate` produces a markdown digest derived from the
  actual prompt content (never invented project facts) and is only used for
  free-form chat fallbacks.  Structured agent outputs in mock mode come from
  each agent's deterministic ``mock_payload`` implementation.

Every execution records ``mode="mock"`` and the UI shows a MOCK MODE badge, so a
demo can never be mistaken for a live model response.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator, Sequence

from app.tools.llm.base import LLMProvider, LLMResult, LLMUsage

DEFAULT_DIM = 256
_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{1,}")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


class MockProvider(LLMProvider):
    name = "mock"
    supports_json_mode = True

    def __init__(self, *, embedding_dim: int = DEFAULT_DIM, **kwargs) -> None:  # noqa: ANN003
        kwargs.setdefault("model", "devforge-mock-1")
        super().__init__(**kwargs)
        self.embedding_dim = embedding_dim
        self.embedding_model = f"devforge-hashing-{embedding_dim}"

    # ------------------------------------------------------------------ chat
    def generate(self, prompt, *, system="", temperature=None, max_tokens=None,
                 json_mode=False) -> LLMResult:
        text = self._compose(prompt, system, json_mode=json_mode)
        usage = LLMUsage(
            prompt_tokens=max(1, len(_tokens(prompt)) + len(_tokens(system))),
            completion_tokens=max(1, len(_tokens(text))),
        )
        usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        return LLMResult(
            text=text,
            model=self.model,
            provider=self.name,
            usage=usage,
            finish_reason="stop",
            raw={"mock": True},
        )

    def stream(self, prompt, *, system="", **kwargs) -> Iterator[str]:  # noqa: ANN003
        text = self.generate(prompt, system=system, **kwargs).text
        for paragraph in text.split("\n"):
            yield paragraph + "\n"

    def _compose(self, prompt: str, system: str, *, json_mode: bool) -> str:
        """Build a deterministic, grounded reply from the prompt itself."""
        if json_mode:
            return "{}"  # structured payloads come from each agent's mock_payload()
        sections = self._extract_headings(prompt)
        summary = self._first_paragraph(prompt)
        lines = [
            "> **MOCK MODE** — no LLM API key is configured, so this response was produced",
            "> locally and deterministically by the DevForge mock provider.",
            "",
            "I reviewed the project context supplied with your message.",
            "",
        ]
        if sections:
            lines.append("**Context I can see:**")
            lines.extend(f"- {section}" for section in sections[:12])
            lines.append("")
        if summary:
            lines += ["**Most relevant context excerpt:**", "", f"```\n{summary[:900]}\n```", ""]
        lines += [
            "**How to answer this with a live model**",
            "1. Set `DEVFORGE_MODE=live`.",
            "2. Provide `LLM_API_KEY` (and `LLM_PROVIDER`, `LLM_MODEL`) in `.env`.",
            "3. Restart the backend — the same agent, prompt and context will be sent to your provider.",
            "",
            "_In mock mode the workflow, approvals, artifacts, tests and traceability are fully",
            "functional; only free-form model text is replaced by this deterministic digest._",
        ]
        return "\n".join(lines)

    @staticmethod
    def _extract_headings(prompt: str) -> list[str]:
        return [line.strip("# ").strip() for line in prompt.splitlines() if line.startswith("## ")][:20]

    @staticmethod
    def _first_paragraph(prompt: str) -> str:
        for block in prompt.split("\n\n"):
            cleaned = block.strip()
            if len(cleaned) > 80 and not cleaned.startswith("#"):
                return cleaned
        return prompt.strip()[:400]

    # ------------------------------------------------------------- embeddings
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._hash_embed(text) for text in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """Feature-hashed TF vector with sublinear term weighting."""
        vector = [0.0] * self.embedding_dim
        tokens = _tokens(text)
        if not tokens:
            return vector
        counts: dict[str, int] = {}
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
        # include bigrams for a little word-order sensitivity
        for first, second in zip(tokens, tokens[1:], strict=False):
            bigram = f"{first}_{second}"
            counts[bigram] = counts.get(bigram, 0) + 1
        for token, count in counts.items():
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.embedding_dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def health(self) -> dict:
        return {
            "provider": self.name,
            "model": self.model,
            "configured": True,
            "note": "Deterministic offline provider (hashing embeddings, grounded text digest).",
        }
