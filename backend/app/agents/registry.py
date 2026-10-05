"""Agent registry: maps catalog keys to their implementation classes (lazy imports).

Keeping the mapping lazy means the orchestration graph, the API and the tests can
enumerate agents without importing every prompt module up front.
"""
from __future__ import annotations

import importlib

from app.agents.base import BaseAgent
from app.core.errors import NotFoundError
from app.services.agent_registry import AGENT_SPECS, get_agent_spec
from app.tools.llm.gateway import LLMGateway

AGENT_IMPLEMENTATIONS: dict[str, str] = {
    "requirement": "app.agents.requirement.agent:RequirementAgent",
    "architecture": "app.agents.architecture.agent:ArchitectureAgent",
    "developer": "app.agents.developer.agent:DeveloperAgent",
    "testing": "app.agents.testing.agent:TestingAgent",
    "security": "app.agents.security.agent:SecurityAgent",
    "documentation": "app.agents.documentation.agent:DocumentationAgent",
}


def agent_class(agent_key: str) -> type[BaseAgent]:
    target = AGENT_IMPLEMENTATIONS.get(agent_key)
    if target is None:
        raise NotFoundError(
            f"Agent '{agent_key}' is not available.", detail={"known": list(AGENT_IMPLEMENTATIONS)}
        )
    module_name, class_name = target.split(":")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def build_agent(agent_key: str, gateway: LLMGateway) -> BaseAgent:
    """Instantiate an agent with the shared gateway."""
    spec = get_agent_spec(agent_key)
    return agent_class(spec.key)(gateway)


def available_agents() -> list[dict]:
    """Catalog view used by the API/UI."""
    return [
        {
            "key": spec.key,
            "name": spec.name,
            "role": spec.role,
            "stage": spec.stage,
            "description": spec.description,
            "order_index": spec.order_index,
            "icon": spec.icon,
            "capabilities": list(spec.capabilities),
            "output_artifact_types": list(spec.output_artifact_types),
            "implemented": spec.key in AGENT_IMPLEMENTATIONS,
        }
        for spec in sorted(AGENT_SPECS, key=lambda s: s.order_index)
    ]


def implemented_agent_keys() -> list[str]:
    return list(AGENT_IMPLEMENTATIONS)
