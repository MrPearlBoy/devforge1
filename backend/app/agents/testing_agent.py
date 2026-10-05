"""Testing Agent (TA): source + specs → comprehensive pytest suite."""
from __future__ import annotations

from app.agents.base_agent import AgentBase
from app.orchestrator.state import TestArtifact

SYSTEM_PROMPT = """You are the Testing Agent (TA) of the DevForge multi-agent software engineering platform.

Your job: write a comprehensive, deterministic pytest suite (tests/test_*.py) for
the provided source files.

HARD CONSTRAINTS:
- tests may import only pytest, the standard library and the "src" package.
- no network access, no real sleeps, no randomness without a fixed seed.
- use tmp_path fixtures for any file/database persistence tests.
- cover: happy paths, validation/edge cases, structured error paths (assert the
  exact status codes / exceptions), and a CLI smoke test when a CLI exists.
- file paths must be relative like "tests/test_core.py".

Respond with a single JSON object only — no markdown fences, no commentary."""


class TestingAgent(AgentBase):
    kind = "tests"
    name = "Testing Agent"
    stage = "testing"
    system = SYSTEM_PROMPT
    model = TestArtifact
