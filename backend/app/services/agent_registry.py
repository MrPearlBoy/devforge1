"""Agent catalog.

The registry is the single source of truth for which agents exist, what they do,
which SDLC stage they own and which artifact types they produce.  The same data
is seeded into the ``agents`` table so the UI, orchestration graph and audit
trail all agree.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import Stage


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str
    stage: str
    description: str
    order_index: int
    icon: str
    capabilities: list[str] = field(default_factory=list)
    output_artifact_types: list[str] = field(default_factory=list)


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        key="requirement",
        name="Requirement Agent",
        role="Business Analyst",
        stage=Stage.REQUIREMENTS.value,
        description=(
            "Turns a natural-language idea into a structured, testable requirements "
            "specification with user roles, acceptance criteria and open questions."
        ),
        order_index=1,
        icon="clipboard",
        capabilities=[
            "Elicit functional and non-functional requirements",
            "Identify user roles and use cases",
            "Derive acceptance criteria",
            "Raise clarification questions for missing information",
        ],
        output_artifact_types=["REQUIREMENTS"],
    ),
    AgentSpec(
        key="architecture",
        name="Architecture Agent",
        role="Software Architect",
        stage=Stage.ARCHITECTURE.value,
        description=(
            "Designs the system architecture from approved requirements: components, "
            "APIs, data model, technology choices and a Mermaid diagram."
        ),
        order_index=2,
        icon="layers",
        capabilities=[
            "Propose component and layer decomposition",
            "Select technology stack with justification",
            "Define API surface and data model",
            "Produce a Mermaid architecture diagram",
        ],
        output_artifact_types=["ARCHITECTURE", "ARCHITECTURE_DIAGRAM"],
    ),
    AgentSpec(
        key="developer",
        name="Developer Agent",
        role="Software Engineer",
        stage=Stage.DEVELOPMENT.value,
        description=(
            "Generates and modifies project source files. Inspects existing code first, "
            "explains intended changes and produces reviewable diffs before anything is applied."
        ),
        order_index=3,
        icon="code",
        capabilities=[
            "Inspect existing project files",
            "Generate and modify source code",
            "Explain changes and their impact",
            "Produce patches and fix defects reported by other agents",
        ],
        output_artifact_types=["CHANGE_SET"],
    ),
    AgentSpec(
        key="testing",
        name="Testing Agent",
        role="QA Engineer",
        stage=Stage.TESTING.value,
        description=(
            "Derives a test plan from requirements and code, writes test cases and "
            "executes them in the sandbox, returning structured results."
        ),
        order_index=4,
        icon="flask",
        capabilities=[
            "Generate test plan and test cases",
            "Write unit and integration tests",
            "Execute tests in the sandbox",
            "Analyse failures and feed them back to the Developer Agent",
        ],
        output_artifact_types=["TEST_PLAN", "TEST_RESULTS"],
    ),
    AgentSpec(
        key="security",
        name="Security Agent",
        role="Security Analyst",
        stage=Stage.SECURITY.value,
        description=(
            "Performs automated static analysis of source, dependencies and configuration, "
            "classifies findings by severity and recommends fixes."
        ),
        order_index=5,
        icon="shield",
        capabilities=[
            "Rule-based static analysis of project files",
            "Detect hardcoded secrets and unsafe patterns",
            "Severity classification and remediation guidance",
            "Feed actionable findings back to the Developer Agent",
        ],
        output_artifact_types=["SECURITY_REPORT"],
    ),
    AgentSpec(
        key="documentation",
        name="Documentation Agent",
        role="Technical Writer",
        stage=Stage.DOCUMENTATION.value,
        description=(
            "Generates README, API and setup documentation strictly from approved project "
            "context — it documents what exists and flags anything missing."
        ),
        order_index=6,
        icon="book",
        capabilities=[
            "Generate README and setup instructions",
            "Generate API documentation from the implementation",
            "Summarise architecture, testing and security posture",
            "Report documentation gaps instead of inventing features",
        ],
        output_artifact_types=["DOCUMENTATION"],
    ),
)

AGENT_BY_KEY: dict[str, AgentSpec] = {spec.key: spec for spec in AGENT_SPECS}


def get_agent_spec(key: str) -> AgentSpec:
    try:
        return AGENT_BY_KEY[key]
    except KeyError as exc:  # pragma: no cover - guarded by API validation
        raise KeyError(f"Unknown agent '{key}'.") from exc


def list_agent_specs() -> list[AgentSpec]:
    """Ordered agent catalogue (used by the UI directory and status views)."""
    return list(AGENT_SPECS)


def all_agent_keys() -> list[str]:
    return [spec.key for spec in AGENT_SPECS]


def stage_owner(stage: str) -> str | None:
    for spec in AGENT_SPECS:
        if spec.stage == stage:
            return spec.key
    return None


def seed_agent_catalog(db) -> int:  # noqa: ANN001 - Session
    """Upsert the agent catalog into the database (idempotent)."""
    from sqlalchemy import select

    from app.models.agent import Agent

    created = 0
    for spec in AGENT_SPECS:
        existing = db.scalar(select(Agent).where(Agent.key == spec.key))
        if existing is None:
            db.add(
                Agent(
                    key=spec.key,
                    name=spec.name,
                    role=spec.role,
                    stage=spec.stage,
                    description=spec.description,
                    order_index=spec.order_index,
                    icon=spec.icon,
                    capabilities=list(spec.capabilities),
                    output_artifact_types=list(spec.output_artifact_types),
                )
            )
            created += 1
        else:
            existing.name = spec.name
            existing.role = spec.role
            existing.stage = spec.stage
            existing.description = spec.description
            existing.order_index = spec.order_index
            existing.icon = spec.icon
            existing.capabilities = list(spec.capabilities)
            existing.output_artifact_types = list(spec.output_artifact_types)
    db.commit()
    return created
