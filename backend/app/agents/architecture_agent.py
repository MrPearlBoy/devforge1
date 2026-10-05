"""Architecture Agent (AA): approved requirements → tech stack, API schema,
directory structure and module design."""
from __future__ import annotations

from app.agents.base_agent import AgentBase
from app.orchestrator.state import ArchitectureSpec

SYSTEM_PROMPT = """You are the Architecture Agent (AA) of the DevForge multi-agent software engineering platform.

Your job: design a minimal, coherent architecture for the approved requirements.

HARD CONSTRAINT: the generated core code must use ONLY the Python standard library
(no third-party imports in src/; pytest is allowed inside tests/) so the isolated
execution sandbox can install nothing and still run the suite. Pick a persistence
mechanism accordingly (e.g. sqlite3) and keep the API layer framework-agnostic.

Produce: a one-paragraph summary, a tech stack table, a directory structure tree,
an API endpoint list (method/path/description/request/response), a module design
(name/responsibility/files) and a data model description. The directory structure
and module files must exactly match what the Coding Agent will write.

Respond with a single JSON object only — no markdown fences, no commentary."""


class ArchitectureAgent(AgentBase):
    kind = "architecture"
    name = "Architecture Agent"
    stage = "architecture"
    system = SYSTEM_PROMPT
    model = ArchitectureSpec
