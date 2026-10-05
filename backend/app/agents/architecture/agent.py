"""Architecture Agent.

Input : approved requirements artifact (+ full project context).
Output: ``architecture/architecture.md``, ``architecture/architecture.mmd`` and an
        ArchitectureSpec payload with explicit REQ -> ARCH trace links.
"""
from __future__ import annotations

from app.agents.architecture.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.agents.architecture.schemas import ArchitectureSpec
from app.agents.base import AgentOutcome, ArtifactDraft, BaseAgent
from app.agents.common.domain_inference import (
    DomainModel,
    crud_endpoints,
    infer_domain,
    infer_tech_stack,
    project_layout,
)
from app.models.enums import ArtifactType, Stage, TraceNodeType
from app.services.agent_registry import get_agent_spec
from app.services.project_context import AgentContext


class ArchitectureAgent(BaseAgent):
    spec = get_agent_spec("architecture")
    prompt_version = PROMPT_VERSION
    output_schema = ArchitectureSpec

    # ------------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        return build_user_prompt(context.to_prompt_block(), task)

    # --------------------------------------------------------------- mock mode
    def mock_payload(self, context: AgentContext, task: str = "") -> dict:
        requirements = self._requirements_payload(context)
        source_text = " ".join(
            [
                context.project.get("requirement_input", ""),
                " ".join(item.get("title", "") + " " + item.get("description", "")
                         for item in requirements.get("functional_requirements", [])),
            ]
        )
        domain = infer_domain(
            source_text,
            requirements.get("functional_requirements"),
            roles=[role.get("name", "") for role in requirements.get("user_roles", [])],
        )
        stack = infer_tech_stack(source_text)
        all_reqs = [item["id"] for item in requirements.get("functional_requirements", [])]
        all_nfrs = [item["id"] for item in requirements.get("non_functional_requirements", [])]

        components = self._components(domain, stack, all_reqs, all_nfrs)
        data_model = self._data_model(domain)
        endpoints = self._endpoints(domain, components)
        modules = project_layout(domain)
        diagram = self._mermaid(domain, components)

        security_refs = [nfr for nfr in all_nfrs if nfr.startswith("NFR")] or all_reqs[:1]
        return {
            "overview": (
                f"A {domain.application_type} built as a layered modular monolith. The React frontend "
                f"talks to a FastAPI application that owns validation, authorisation and domain rules; "
                f"a data access layer isolates PostgreSQL/SQLite. The primary domain entity is "
                f"**{domain.primary.name}** with {len(domain.primary.fields)} fields, supported by "
                f"{len(domain.entities) - 1} additional entity(ies). This keeps the system deployable as "
                f"a single container pair while remaining modular enough to split later."
            ),
            "architecture_style": "Layered modular monolith (presentation / application / domain / data)",
            "tech_stack": stack,
            "components": components,
            "data_model": data_model,
            "api_endpoints": endpoints,
            "integrations": self._integrations(source_text, domain),
            "security_requirements": [
                "All non-public endpoints require a valid JWT; authorisation is checked per resource owner.",
                "Passwords are stored as salted hashes (never reversible, never logged).",
                "All database access uses parameterised queries through the ORM — no string-built SQL.",
                "Secrets are supplied through environment variables; nothing sensitive is committed.",
                "Request payloads are validated by Pydantic schemas before reaching domain logic.",
                "Errors return stable machine readable codes without stack traces or internal identifiers.",
                "CI runs the test suite and the DevForge security scan before merge.",
            ],
            "deployment": [
                f"{stack['deployment']}: one container for the API, one for the web client, one for PostgreSQL.",
                "Configuration is injected through environment variables (.env for local development).",
                "Database schema changes are applied with versioned migrations before the API starts.",
                "Health endpoint /health exposes liveness and readiness for the platform.",
                "DevForge's restricted sandbox is the only place generated code is executed.",
            ],
            "modules": modules,
            "decisions": self._decisions(domain, stack),
            "diagram_mermaid": diagram,
            "risks": [
                "Authentication and role requirements are still open questions in the requirements stage; "
                "the design assumes JWT + role claims and must be revisited if that changes.",
                "The list endpoints will need pagination and indexes once data volumes grow beyond the "
                "assumed scale.",
                "Real-time behaviour (if later required) would need a streaming channel such as SSE.",
            ],
            "open_questions": [
                "Confirm the hosting target (single VM, container platform, or on-premise lab machine).",
                "Confirm backup and data-retention expectations for user records.",
            ],
        }

    # ------------------------------------------------------------- mock helpers
    @staticmethod
    def _requirements_payload(context: AgentContext) -> dict:
        for artifact in context.artifacts.values():
            if artifact.get("type") == ArtifactType.REQUIREMENTS.value:
                return artifact.get("data") or {}
        return {}

    @staticmethod
    def _components(domain: DomainModel, stack: dict[str, str], reqs: list[str],
                    nfrs: list[str]) -> list[dict]:
        components: list[dict] = [
            {
                "id": "ARCH-001",
                "name": "Web Client",
                "layer": "presentation",
                "responsibility": (
                    f"User interface for the {domain.primary.table} workflow: create, list, edit, "
                    "filter and delete records, with client-side validation."
                ),
                "technology": stack["frontend"],
                "interfaces": ["Consumes the REST API over HTTPS", "Renders forms and tables"],
                "requirement_refs": reqs[:4] or ["REQ-001"],
            },
            {
                "id": "ARCH-002",
                "name": "API Application",
                "layer": "application",
                "responsibility": "HTTP surface, request validation, authentication enforcement, "
                                  "error translation and OpenAPI documentation.",
                "technology": stack["backend"],
                "interfaces": ["REST over HTTPS", "/openapi.json", "/health"],
                "requirement_refs": reqs[:6] or ["REQ-001"],
            },
            {
                "id": "ARCH-003",
                "name": f"{domain.primary.name} Service",
                "layer": "domain",
                "responsibility": f"Domain rules for {domain.primary.table}: validation, state "
                                  "transitions and ownership checks.",
                "technology": "Pure Python service module",
                "interfaces": ["Called by the API layer", "Calls the data access layer"],
                "requirement_refs": [ref for entity in domain.entities for ref in entity.requirement_refs][:8]
                or reqs[:4],
            },
            {
                "id": "ARCH-004",
                "name": "Data Access Layer",
                "layer": "data",
                "responsibility": "ORM models, sessions and repository functions; the only component "
                                  "that talks to the database.",
                "technology": stack["orm"],
                "interfaces": ["Session per request", "Parameterised queries only"],
                "requirement_refs": reqs[:3] or ["REQ-001"],
            },
            {
                "id": "ARCH-005",
                "name": "Database",
                "layer": "data",
                "responsibility": f"Persistent storage for {', '.join(e.table for e in domain.entities)} "
                                  "with migrations applied at deploy time.",
                "technology": stack["database"],
                "interfaces": ["SQL over a private network", "Migration tooling"],
                "requirement_refs": nfrs[:2] or reqs[:2],
            },
            {
                "id": "ARCH-006",
                "name": "Identity and Access",
                "layer": "platform",
                "responsibility": "Registration, sign-in, password hashing, JWT issuing/validation and "
                                  "role checks.",
                "technology": stack["authentication"],
                "interfaces": ["/api/auth/*", "Bearer token validation dependency"],
                "requirement_refs": [ref for ref in reqs if "login" in ref.lower()] or nfrs[:1] or reqs[:1],
            },
        ]
        if "notifications" in domain.capabilities:
            components.append(
                {
                    "id": "ARCH-007",
                    "name": "Notification Worker",
                    "layer": "platform",
                    "responsibility": "Sends reminders for records approaching their due date.",
                    "technology": "APScheduler background job inside the API container (MVP)",
                    "interfaces": ["Reads due records", "Sends email/webhook"],
                    "requirement_refs": reqs[-2:] or reqs[:1],
                }
            )
        if "reporting" in domain.capabilities:
            components.append(
                {
                    "id": "ARCH-008",
                    "name": "Reporting Module",
                    "layer": "application",
                    "responsibility": "Aggregate queries exposed as report endpoints for dashboards.",
                    "technology": "SQL aggregates served by the API layer",
                    "interfaces": ["/api/reports/*"],
                    "requirement_refs": reqs[-3:] or reqs[:1],
                }
            )
        return components

    @staticmethod
    def _data_model(domain: DomainModel) -> list[dict]:
        relationship_note = {
            "User": "Referenced by other entities through an owner_id foreign key.",
        }
        return [
            {
                "name": entity.name,
                "table": entity.table,
                "fields": [
                    {
                        "name": field.name,
                        "type": field.python_type,
                        "required": field.required,
                        "description": field.description,
                    }
                    for field in entity.fields
                ]
                + [
                    {"name": "id", "type": "uuid", "required": True, "description": "Primary key"},
                    {"name": "created_at", "type": "datetime", "required": True,
                     "description": "Creation timestamp (UTC)"},
                    {"name": "updated_at", "type": "datetime", "required": True,
                     "description": "Last modification timestamp (UTC)"},
                ],
                "relationships": [
                    relationship_note.get(entity.name, "Owned by a User through owner_id."),
                    f"One-to-many with User: one account owns many {entity.table}.",
                ] if entity.name != "User" else [
                    "One-to-many with every owned record through owner_id.",
                    "Single administrator may manage all accounts.",
                ],
                "requirement_refs": entity.requirement_refs,
            }
            for entity in domain.entities
        ]

    @staticmethod
    def _endpoints(domain: DomainModel, components: list[dict]) -> list[dict]:
        component_by_layer = {component["layer"]: component["id"] for component in components}
        endpoints: list[dict] = []
        for entity in domain.entities:
            if entity.name == "User":
                continue
            for endpoint in crud_endpoints(entity, requires_auth=domain.requires_auth):
                endpoints.append(
                    {
                        **endpoint,
                        "request": "JSON body matching the entity schema" if endpoint["method"] in
                                   {"POST", "PUT", "PATCH"} else "query parameters (page, size, filter)",
                        "component_ref": component_by_layer.get("application", "ARCH-002"),
                        "requirement_refs": entity.requirement_refs[:2],
                    }
                )
        if domain.requires_auth:
            endpoints += [
                {"method": "POST", "path": "/api/auth/register", "purpose": "Create an account",
                 "auth": "Public", "request": "email, password, full_name", "response": "user + token",
                 "component_ref": "ARCH-006", "requirement_refs": entity_refs(domain, "User")},
                {"method": "POST", "path": "/api/auth/login", "purpose": "Obtain a JWT",
                 "auth": "Public", "request": "email, password", "response": "access_token, expires_in",
                 "component_ref": "ARCH-006", "requirement_refs": entity_refs(domain, "User")},
                {"method": "GET", "path": "/api/auth/me", "purpose": "Read the authenticated profile",
                 "auth": "Bearer JWT required", "request": "—", "response": "user",
                 "component_ref": "ARCH-006", "requirement_refs": entity_refs(domain, "User")},
            ]
        return endpoints

    @staticmethod
    def _integrations(source_text: str, domain: DomainModel) -> list[str]:
        lowered = source_text.lower()
        integrations = ["OpenAPI/Swagger documentation exposed by the API (built-in)"]
        if "email" in lowered or "notif" in lowered:
            integrations.append("SMTP email provider for notifications (configured by environment)")
        if "payment" in lowered or "checkout" in lowered:
            integrations.append("Hosted payment gateway with webhook confirmation (no card data stored)")
        if "github" in lowered or "git" in lowered:
            integrations.append("GitHub REST API for repository synchronisation")
        if "sms" in lowered:
            integrations.append("SMS gateway for one-time codes")
        integrations.append("DevForge itself: workspace files, approvals and GitHub delivery")
        return integrations

    @staticmethod
    def _decisions(domain: DomainModel, stack: dict[str, str]) -> list[dict]:
        return [
            {
                "id": "ARCH-ADR-1",
                "decision": "Layered modular monolith rather than microservices",
                "rationale": "The scope and expected load fit a single deployable unit; microservices "
                             "would add operational cost with no benefit at this stage.",
                "alternatives": ["Microservices per bounded context", "Serverless functions"],
                "consequences": "One deploy pipeline to maintain; extract services later behind the same "
                                "API contracts if load demands it.",
            },
            {
                "id": "ARCH-ADR-2",
                "decision": f"Use {stack['database'].split('(')[0].strip()} as the system of record",
                "rationale": "Relational data with clear ownership and reporting needs; SQL aggregates "
                             "cover the reporting requirements.",
                "alternatives": ["Document store (MongoDB)", "Embedded database only"],
                "consequences": "Schema migrations are required; SQLite keeps local tests fast.",
            },
            {
                "id": "ARCH-ADR-3",
                "decision": f"Authenticate with {stack['authentication'].split('with')[0].strip()}",
                "rationale": "Stateless tokens suit an SPA + API split and keep the deployment simple.",
                "alternatives": ["Server sessions with cookies", "OAuth delegation to a third party"],
                "consequences": "Token lifetime and revocation policy must be defined; refresh tokens "
                                "are a follow-up if sessions must be long-lived.",
            },
            {
                "id": "ARCH-ADR-4",
                "decision": "Validate every request with Pydantic schemas at the API boundary",
                "rationale": "Stops malformed or hostile input before it reaches domain logic and keeps "
                             "error responses consistent.",
                "alternatives": ["Manual validation in each handler"],
                "consequences": "Schema changes must be versioned alongside API changes.",
            },
        ]

    @staticmethod
    def _mermaid(domain: DomainModel, components: list[dict]) -> str:
        lines = [
            "flowchart TD",
            "    CLIENT[Human User]",
            "    UI[Web Client UI]",
            "    API[API Application]",
            "    AUTH[Identity and Access]",
            "    SVC[Domain Service]",
            "    DAL[Data Access Layer]",
            "    DB[(Database)]",
            "    TEST[Test Suite]",
            "    SANDBOX[DevForge Sandbox]",
            "",
            "    CLIENT --> UI",
            "    UI -->|REST over HTTPS| API",
            "    API -->|verifies token| AUTH",
            "    API --> SVC",
            "    SVC --> DAL",
            "    DAL --> DB",
            "    TEST -->|runs against| API",
            "    SANDBOX -->|executes tests| TEST",
        ]
        if "notifications" in domain.capabilities:
            lines += ["    WORKER[Notification Worker]", "    WORKER --> DAL", "    WORKER -->|email| CLIENT"]
        if "reporting" in domain.capabilities:
            lines += ["    REPORTS[Reporting Module]", "    API --> REPORTS", "    REPORTS --> DAL"]
        lines += [
            "",
            "    classDef platform fill:#eef2ff,stroke:#6366f1",
            "    classDef data fill:#ecfdf5,stroke:#10b981",
            "    classDef client fill:#fef3c7,stroke:#f59e0b",
            "    class UI,API,SVC,AUTH client",
            "    class DAL,DB data",
            "    class TEST,SANDBOX platform",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------- render
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        components = payload.get("components", [])
        endpoints = payload.get("api_endpoints", [])
        decisions = payload.get("decisions", [])
        entities = payload.get("data_model", [])
        diagram = payload.get("diagram_mermaid", "")

        markdown = self._to_markdown(payload, context)
        trace_pairs: list[dict] = []
        for component in components:
            for requirement_ref in component.get("requirement_refs", []):
                trace_pairs.append(
                    {
                        "source_type": TraceNodeType.REQUIREMENT.value,
                        "source_ref": requirement_ref,
                        "source_label": f"Requirement {requirement_ref}",
                        "target_type": TraceNodeType.ARCHITECTURE.value,
                        "target_ref": component["id"],
                        "target_label": component["name"],
                        "relation": "realised_by",
                    }
                )
        for entity in entities:
            for requirement_ref in entity.get("requirement_refs", []):
                trace_pairs.append(
                    {
                        "source_type": TraceNodeType.REQUIREMENT.value,
                        "source_ref": requirement_ref,
                        "source_label": f"Requirement {requirement_ref}",
                        "target_type": TraceNodeType.ARCHITECTURE.value,
                        "target_ref": f"DATA-{entity['table']}",
                        "target_label": f"{entity['name']} table",
                        "relation": "persisted_as",
                    }
                )

        return AgentOutcome(
            agent_key=self.key,
            stage=self.stage,
            content=markdown,
            summary=(
                f"Designed {len(components)} components, {len(entities)} data entities and "
                f"{len(endpoints)} API endpoints with {len(decisions)} architecture decisions."
            ),
            artifacts=[
                ArtifactDraft(
                    artifact_type=ArtifactType.ARCHITECTURE.value,
                    stage=Stage.ARCHITECTURE.value,
                    title=f"Architecture specification — {context.project.get('name', 'project')}",
                    content=markdown,
                    summary=f"{len(components)} components, {len(endpoints)} endpoints",
                    path="architecture/architecture.md",
                    data=payload,
                    trace_refs=[component["id"] for component in components],
                ),
                ArtifactDraft(
                    artifact_type=ArtifactType.ARCHITECTURE_DIAGRAM.value,
                    stage=Stage.ARCHITECTURE.value,
                    title="Architecture diagram (Mermaid)",
                    content=diagram,
                    summary="Component and data flow diagram",
                    path="architecture/architecture.mmd",
                    data={"format": "mermaid", "node_count": len(components)},
                    trace_refs=[component["id"] for component in components],
                ),
            ],
            structured=payload,
            trace_pairs=trace_pairs,
            suggested_tasks=[
                {
                    "title": f"Implement {component['name']}",
                    "description": component["responsibility"][:400],
                    "priority": "HIGH" if component["id"] in {"ARCH-001", "ARCH-002"} else "MEDIUM",
                    "stage": Stage.DEVELOPMENT.value,
                    "agent_key": "developer",
                    "requirement_refs": component.get("requirement_refs", [])[:3],
                }
                for component in components[:6]
            ],
            meta={"component_count": len(components), "endpoint_count": len(endpoints)},
        )

    # ---------------------------------------------------------------- rendering
    def _to_markdown(self, payload: dict, context: AgentContext) -> str:
        lines: list[str] = [
            f"# Architecture Specification — {context.project.get('name', 'Project')}",
            "",
            f"_Produced by the **Architecture Agent** ({self.prompt_version}) from the approved "
            "requirements — status: awaiting human approval._",
            "",
            "## 1. Overview",
            "",
            payload.get("overview", ""),
            "",
            f"**Architecture style:** {payload.get('architecture_style', '')}",
            "",
            "## 2. Technology stack",
            "",
            "| Concern | Choice |",
            "| --- | --- |",
        ]
        for concern, choice in (payload.get("tech_stack") or {}).items():
            lines.append(f"| {concern.replace('_', ' ').title()} | {choice} |")

        lines += ["", "## 3. Components", "",
                  "| ID | Component | Layer | Technology | Responsibility | Requirements |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for component in payload.get("components", []):
            lines.append(
                f"| {component['id']} | {component['name']} | {component.get('layer', '')} | "
                f"{component.get('technology', '')} | {component['responsibility']} | "
                f"{', '.join(component.get('requirement_refs', [])) or '—'} |"
            )

        lines += ["", "## 4. Data model", ""]
        for entity in payload.get("data_model", []):
            lines += [
                f"### {entity['name']} (`{entity['table']}`)",
                "",
                f"{entity.get('relationships', '')}",
                "",
                "| Field | Type | Required | Notes |",
                "| --- | --- | --- | --- |",
            ]
            for field in entity.get("fields", []):
                lines.append(
                    f"| {field['name']} | {field.get('type', '')} | "
                    f"{'yes' if field.get('required') else 'no'} | {field.get('description', '')} |"
                )
            if entity.get("requirement_refs"):
                lines += ["", f"_Requirement refs: {', '.join(entity['requirement_refs'])}_"]
            lines.append("")

        lines += ["## 5. API surface", "",
                  "| Method | Path | Purpose | Auth | Request | Response | Requirements |",
                  "| --- | --- | --- | --- | --- | --- | --- |"]
        for endpoint in payload.get("api_endpoints", []):
            lines.append(
                f"| `{endpoint['method']}` | `{endpoint['path']}` | {endpoint['purpose']} | "
                f"{endpoint.get('auth', '')} | {endpoint.get('request', '')} | "
                f"{endpoint.get('response', '')} | "
                f"{', '.join(endpoint.get('requirement_refs', [])) or '—'} |"
            )

        for title, key, numbered in (
            ("Integrations", "integrations", False),
            ("Security requirements", "security_requirements", False),
            ("Deployment approach", "deployment", True),
            ("Risks", "risks", False),
            ("Open questions", "open_questions", False),
        ):
            lines += ["", f"## {title if title != 'Deployment approach' else '6. Deployment'}".replace(
                "## 6. Deployment", "## 6. Deployment"), ""]
            items = payload.get(key, [])
            lines += [f"{i}. {item}" if numbered else f"- {item}" for i, item in enumerate(items, 1)]
            if not items:
                lines.append("- None recorded")

        lines += ["", "## 7. Architecture decision records", ""]
        for decision in payload.get("decisions", []):
            lines += [
                f"### {decision['id']} — {decision['decision']}",
                "",
                f"- **Rationale:** {decision.get('rationale', '')}",
                f"- **Alternatives considered:** {', '.join(decision.get('alternatives', [])) or '—'}",
                f"- **Consequences:** {decision.get('consequences', '')}",
                "",
            ]

        lines += ["## 8. Diagram source", "", "```mermaid", payload.get("diagram_mermaid", ""), "```", ""]
        lines += ["## 9. Planned module layout", "",
                  "| Path | Purpose | Component |", "| --- | --- | --- |"]
        for module in payload.get("modules", []):
            lines.append(f"| `{module['path']}` | {module['purpose']} | {module.get('component_ref', '—')} |")

        lines += [
            "",
            "---",
            "",
            "## Traceability",
            "",
            "Every component, table and endpoint above carries the requirement ids it satisfies; those "
            "links are stored in DevForge and shown on the traceability page.",
            "",
            "_Human approval is required before the Developer Agent generates code._",
        ]
        return "\n".join(lines)


def entity_refs(domain: DomainModel, entity_name: str) -> list[str]:
    for entity in domain.entities:
        if entity.name == entity_name:
            return entity.requirement_refs[:3]
    return []
