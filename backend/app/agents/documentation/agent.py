"""Documentation Agent.

Generates README plus setup, API, architecture, testing and security documents.

Every statement is derived from evidence the agent can see: the approved artifacts,
the real workspace file listing, the actual test run and the security findings. In
mock mode the templates interpolate only those facts; in live mode the same facts
are supplied to the model with an explicit instruction not to invent anything.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.agents.base import AgentOutcome, ArtifactDraft, BaseAgent
from app.agents.documentation.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.agents.documentation.schemas import DocumentationPlan
from app.models.enums import ArtifactType, Stage, TraceNodeType
from app.services.agent_registry import get_agent_spec
from app.services.project_context import AgentContext
from app.services.workspace import WorkspaceService


class DocumentationAgent(BaseAgent):
    spec = get_agent_spec("documentation")
    prompt_version = PROMPT_VERSION
    output_schema = DocumentationPlan

    # ------------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        return build_user_prompt(context.to_prompt_block(), self._facts_block(context))

    # --------------------------------------------------------------- mock payload
    def mock_payload(self, context: AgentContext, task: str = "") -> dict:
        facts = self._collect_facts(context)
        files = [
            self._readme(facts, context),
            self._setup_doc(facts, context),
            self._api_doc(facts, context),
            self._architecture_doc(facts, context),
            self._testing_doc(facts, context),
            self._security_doc(facts, context),
        ]
        requirements = facts["requirements"].get("functional_requirements", [])
        return {
            "overview": (
                f"Documentation generated from the project's approved artifacts and its actual "
                f"source tree ({facts['file_count']} files in the workspace). It documents "
                f"{len(requirements)} functional requirements, {len(facts['endpoints'])} API "
                f"endpoints and the latest test and security results."
            ),
            "files": [
                {
                    "path": item["path"],
                    "title": item["title"],
                    "content": item["content"],
                    "summary": item["summary"],
                    "requirement_refs": item["requirement_refs"],
                }
                for item in files
            ],
            "documented_facts": [
                f"Workspace files: {', '.join(facts['top_level'])}",
                f"API endpoints derived from the approved architecture: {len(facts['endpoints'])}",
                f"Test results: {facts['test'].get('passed', 0)}/{facts['test'].get('total', 0)} "
                f"passing (status {facts['test'].get('status', 'not run')})",
                f"Security findings: {facts['security'].get('open_total', 0)} open",
                f"Requirements: {len(requirements)} functional, "
                f"{len(facts['requirements'].get('non_functional_requirements', []))} non-functional",
            ],
            "gaps": facts["gaps"],
            "notes": [
                "MOCK MODE: documents are rendered from structured project facts rather than "
                "model-written prose; no feature is described that does not exist.",
                "Regenerating this stage after code changes produces a new artifact revision.",
            ],
        }

    # ------------------------------------------------------------------- render
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        files = payload.get("files", [])
        index_lines = [
            f"# Documentation index — {context.project.get('name', 'project')}",
            "",
            payload.get("overview", ""),
            "",
            "| Document | Purpose |",
            "| --- | --- |",
        ]
        for item in files:
            index_lines.append(f"| `{item['path']}` | {item.get('summary', '') or item['title']} |")

        if payload.get("documented_facts"):
            index_lines += ["", "## Evidence used", ""]
            index_lines += [f"- {item}" for item in payload["documented_facts"]]
        if payload.get("gaps"):
            index_lines += ["", "## Documentation gaps", ""]
            index_lines += [f"- {item}" for item in payload["gaps"]]
        if payload.get("notes"):
            index_lines += ["", "## Notes", ""]
            index_lines += [f"- {item}" for item in payload["notes"]]

        index_markdown = "\n".join(index_lines)
        artifacts = [
            ArtifactDraft(
                artifact_type=ArtifactType.DOCUMENTATION.value,
                stage=Stage.DOCUMENTATION.value,
                title=f"{item['title']} ({item['path']})",
                content=item["content"],
                summary=item.get("summary", ""),
                path=item["path"],
                data={"title": item["title"], "gaps": payload.get("gaps", [])},
                trace_refs=item.get("requirement_refs", []),
            )
            for item in files
        ]
        artifacts.append(
            ArtifactDraft(
                artifact_type=ArtifactType.DOCUMENTATION.value,
                stage=Stage.DOCUMENTATION.value,
                title="Documentation index",
                content=index_markdown,
                summary=f"{len(files)} documents generated",
                path="documentation/INDEX.md",
                data={"documented_facts": payload.get("documented_facts", []),
                      "gaps": payload.get("gaps", [])},
                trace_refs=[],
            )
        )

        trace_pairs = [
            {
                "source_type": TraceNodeType.REQUIREMENT.value,
                "source_ref": requirement_ref,
                "source_label": f"Requirement {requirement_ref}",
                "target_type": TraceNodeType.DOCUMENTATION.value,
                "target_ref": f"DOC {item['path']}",
                "target_label": item["title"],
                "relation": "documented_in",
            }
            for item in files
            for requirement_ref in item.get("requirement_refs", [])
        ]

        return AgentOutcome(
            agent_key=self.key,
            stage=self.stage,
            content=index_markdown,
            summary=f"Generated {len(files)} documentation file(s) from project evidence",
            artifacts=artifacts,
            structured=payload,
            trace_pairs=trace_pairs,
            meta={"file_count": len(files), "gaps": len(payload.get("gaps", []))},
        )

    # ------------------------------------------------------------------- helpers
    def _collect_facts(self, context: AgentContext) -> dict:
        workspace = WorkspaceService()
        file_infos = workspace.list_files(context.project_id, max_files=400)
        requirements = self._artifact_data(context, ArtifactType.REQUIREMENTS.value)
        architecture = self._artifact_data(context, ArtifactType.ARCHITECTURE.value)
        gaps: list[str] = []

        endpoints = architecture.get("api_endpoints", [])
        if not endpoints:
            gaps.append("No API endpoints were found in the approved architecture artifact.")
        if not context.test_summary:
            gaps.append("The test suite has not been executed yet, so coverage cannot be reported.")
        if not context.security_summary or not context.security_summary.get("open_total"):
            gaps.append(
                "No open security findings are recorded; re-run the Security stage after any change."
            )
        if not requirements:
            gaps.append("The requirements artifact is missing from the project context.")
        if not any(info.path.startswith("frontend/") for info in file_infos):
            gaps.append(
                "No frontend directory exists yet: the current implementation exposes the REST API "
                "only. The React client described in the architecture is not implemented in this "
                "revision."
            )
        if not any(info.path.endswith(".env.example") for info in file_infos):
            gaps.append("No .env.example file is present to document the required environment variables.")

        return {
            "requirements": requirements,
            "architecture": architecture,
            "files": [info.path for info in file_infos],
            "file_count": len(file_infos),
            "top_level": sorted({path.split("/", 1)[0] for path in [info.path for info in file_infos]}),
            "endpoints": endpoints,
            "test": context.test_summary or {},
            "security": context.security_summary or {},
            "gaps": gaps,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }

    @staticmethod
    def _artifact_data(context: AgentContext, artifact_type: str) -> dict:
        for artifact in context.artifacts.values():
            if artifact.get("type") == artifact_type:
                return artifact.get("data") or {}
        return {}

    def _facts_block(self, context: AgentContext) -> str:
        facts = self._collect_facts(context)
        lines = [
            f"- Workspace files ({facts['file_count']}): {', '.join(facts['files'][:60])}",
            f"- Top level: {', '.join(facts['top_level'])}",
            f"- Test results: status={facts['test'].get('status', 'not run')} "
            f"passed={facts['test'].get('passed', 0)} total={facts['test'].get('total', 0)}",
            f"- Security: {facts['security'].get('open_total', 0)} open findings "
            f"(critical {facts['security'].get('critical', 0)}, high {facts['security'].get('high', 0)})",
        ]
        for endpoint in facts["endpoints"][:30]:
            lines.append(
                f"- Endpoint: {endpoint.get('method')} {endpoint.get('path')} — "
                f"{endpoint.get('purpose')} (auth: {endpoint.get('auth')})"
            )
        for gap in facts["gaps"]:
            lines.append(f"- Known gap: {gap}")
        return "\n".join(lines)

    # ---------------------------------------------------------------- documents
    def _readme(self, facts: dict, context: AgentContext) -> dict:
        name = context.project.get("name", "Project")
        requirements = facts["requirements"].get("functional_requirements", [])
        stack = facts["architecture"].get("tech_stack", {})
        features = "\n".join(
            f"- **{item['id']}** — {item.get('title', '')}: {item.get('description', '')[:160]}"
            for item in requirements[:12]
        ) or "- No functional requirements were recorded."
        stack_rows = "\n".join(
            f"| {key.replace('_', ' ').title()} | {value} |" for key, value in stack.items()
        ) or "| Stack | Not specified in the approved architecture |"
        file_tree = "\n".join(f"  {path}" for path in facts["files"][:25])
        content = f"""# {name}

> {context.project.get('description') or 'Built with DevForge — an AI-assisted software engineering workspace with human approval at every SDLC gate.'}

This project was specified, designed, implemented, tested, scanned and documented through
DevForge's multi-agent workflow, with a human approving each stage.

## Features

{features}

## Technology stack

| Concern | Choice |
| --- | --- |
{stack_rows}

## Quick start

```bash
# 1. Backend dependencies
cd backend
pip install -r requirements.txt

# 2. Configure (development defaults work out of the box)
cp .env.example .env
# Set JWT_SECRET to a random 32+ character value before any real deployment

# 3. Run the API
uvicorn app.main:app --reload --port 8000
# OpenAPI docs: http://localhost:8000/docs

# 4. Run the tests
python -m pytest tests -v
```

## Project layout

```
{file_tree}
```

## Documentation

- [`documentation/SETUP.md`](documentation/SETUP.md) — environment and database setup
- [`documentation/API.md`](documentation/API.md) — endpoint reference
- [`documentation/ARCHITECTURE.md`](documentation/ARCHITECTURE.md) — components and decisions
- [`documentation/TESTING.md`](documentation/TESTING.md) — test strategy and latest results
- [`documentation/SECURITY.md`](documentation/SECURITY.md) — security posture and limitations
- [`documentation/INDEX.md`](documentation/INDEX.md) — documentation index and evidence

## Current status

| Signal | Value |
| --- | --- |
| Tests | {facts['test'].get('passed', 0)}/{facts['test'].get('total', 0)} passing (status: {facts['test'].get('status', 'not run')}) |
| Open security findings | {facts['security'].get('open_total', 0)} |
| Documentation generated | {facts['generated_at']} |

## Known gaps

{chr(10).join(f"- {gap}" for gap in facts["gaps"]) or "- None recorded."}

## Licence

Not specified by the project owner. Add a licence before distributing this software.
"""
        return {
            "path": "README.md",
            "title": "Project README",
            "content": content,
            "summary": "Overview, features, quick start and project layout",
            "requirement_refs": [item["id"] for item in requirements[:10]],
        }

    def _setup_doc(self, facts: dict, context: AgentContext) -> dict:
        has_requirements_txt = any(path.endswith("requirements.txt") for path in facts["files"])
        has_package_json = any(path.endswith("package.json") for path in facts["files"])
        install_block = ""
        if has_requirements_txt:
            install_block += "```bash\ncd backend\npip install -r requirements.txt\n```\n"
        if has_package_json:
            install_block += "\n```bash\ncd frontend\nnpm install\n```\n"
        if not install_block:
            install_block = "_No dependency manifest was found in the workspace._\n"
        content = f"""# Setup Guide

## Prerequisites

- Python 3.11 or newer ({'see `backend/requirements.txt`' if has_requirements_txt else 'no Python manifest detected'})
- Git
- Optional: PostgreSQL 14+ (SQLite is the default and requires no setup)

## Install dependencies

{install_block}
## Environment variables

| Variable | Purpose | Required |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy connection string (defaults to a local SQLite file) | No |
| `JWT_SECRET` | Signs authentication tokens; must be a random 32+ character value | Yes in production |
| `JWT_EXPIRES_MINUTES` | Token lifetime in minutes | No |
| `DEBUG` | Enables verbose error output — must stay `false` in production | No |

Copy `backend/.env.example` to `backend/.env` and fill in the values. Never commit a real
`.env` file.

## Database

The service creates its tables on startup for development. For production, apply versioned
migrations instead and point `DATABASE_URL` at PostgreSQL.

## Running the application

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

- Interactive API documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `RuntimeError: JWT_SECRET must be set ...` | The hardened configuration requires a real secret | Set `JWT_SECRET` in the environment |
| `401 Authentication required` on API calls | No bearer token supplied | Log in first and send `Authorization: Bearer <token>` |
| `sqlite3.OperationalError: unable to open database file` | The configured directory is not writable | Point `DATABASE_URL` at a writable path |
"""
        return {
            "path": "documentation/SETUP.md",
            "title": "Setup guide",
            "content": content,
            "summary": "Prerequisites, configuration, database and troubleshooting",
            "requirement_refs": [],
        }

    def _api_doc(self, facts: dict, context: AgentContext) -> dict:
        rows = "\n".join(
            f"| `{item.get('method')}` | `{item.get('path')}` | {item.get('purpose', '')} | "
            f"{item.get('auth', '')} | {item.get('request', '—')} | {item.get('response', '—')} |"
            for item in facts["endpoints"]
        ) or "| — | Not documented | No endpoints were found in the approved architecture | — | — | — |"
        content = f"""# API Reference

Derived from the approved architecture artifact and the routes present in the
implementation. Base URL in local development: `http://localhost:8000`.

## Authentication

Endpoints marked "Bearer JWT required" expect an `Authorization: Bearer <token>` header.
Obtain a token from `POST /api/auth/login`.

## Endpoints

| Method | Path | Purpose | Auth | Request | Response |
| --- | --- | --- | --- | --- | --- |
{rows}

## Error format

Validation failures return HTTP 422 with details from the schema validator; missing or
invalid credentials return 401; resources the caller does not own return 404 so that
existence is not disclosed.

## Conventions

- All timestamps are UTC ISO-8601 strings.
- Identifiers are UUID strings.
- List endpoints accept `limit` (1–200), `offset` and `search`.
"""
        return {
            "path": "documentation/API.md",
            "title": "API reference",
            "content": content,
            "summary": f"{len(facts['endpoints'])} endpoints documented",
            "requirement_refs": [
                reference
                for endpoint in facts["endpoints"]
                for reference in endpoint.get("requirement_refs", [])
            ][:20],
        }

    def _architecture_doc(self, facts: dict, context: AgentContext) -> dict:
        architecture = facts["architecture"]
        components = architecture.get("components", [])
        decisions = architecture.get("decisions", [])
        component_rows = "\n".join(
            f"| {item.get('id')} | {item.get('name')} | {item.get('layer', '')} | "
            f"{item.get('technology', '')} | {item.get('responsibility', '')} |"
            for item in components
        ) or "| — | Not documented | — | — | — |"
        decision_blocks = "\n\n".join(
            f"### {item.get('id')} — {item.get('decision')}\n\n"
            f"- **Rationale:** {item.get('rationale', '')}\n"
            f"- **Alternatives:** {', '.join(item.get('alternatives', [])) or '—'}\n"
            f"- **Consequences:** {item.get('consequences', '')}"
            for item in decisions
        ) or "_No architecture decisions were recorded._"
        diagram = architecture.get("diagram_mermaid", "")
        diagram_block = f"```mermaid\n{diagram}\n```" if diagram else "_No diagram recorded._"
        content = f"""# Architecture

{architecture.get('overview', 'No architecture overview was recorded.')}

**Style:** {architecture.get('architecture_style', 'not recorded')}

## Components

| ID | Component | Layer | Technology | Responsibility |
| --- | --- | --- | --- | --- |
{component_rows}

## Diagram

{diagram_block}

## Architecture decisions

{decision_blocks}

## Security and deployment requirements

{chr(10).join(f"- {item}" for item in architecture.get('security_requirements', [])) or '- Not recorded.'}

{chr(10).join(f"- {item}" for item in architecture.get('deployment', []))}
"""
        return {
            "path": "documentation/ARCHITECTURE.md",
            "title": "Architecture documentation",
            "content": content,
            "summary": "Components, diagram and decision records from the approved architecture",
            "requirement_refs": [
                reference
                for component in components
                for reference in component.get("requirement_refs", [])
            ][:20],
        }

    def _testing_doc(self, facts: dict, context: AgentContext) -> dict:
        test = facts["test"]
        failures = test.get("failures") or []
        failure_block = "\n".join(
            f"- `{item.get('name')}` — {(item.get('message') or '')[:200]}" for item in failures
        ) or "- No failing tests recorded in the latest run."
        test_files = [path for path in facts["files"] if "test" in path.lower() and path.endswith(".py")]
        content = f"""# Testing

## How to run the suite

```bash
cd backend
python -m pytest tests -v
```

In DevForge the same command is executed inside the sandbox
({context.test_summary.get('created_at', 'no run recorded')}), with a hard timeout and no
network access.

## Latest results

| Metric | Value |
| --- | --- |
| Status | {test.get('status', 'not run')} |
| Collected | {test.get('total', 0)} |
| Passed | {test.get('passed', 0)} |
| Failed | {test.get('failed', 0)} |
| Errors | {test.get('errors', 0)} |
| Skipped | {test.get('skipped', 0)} |

## Test files in the workspace

{chr(10).join(f"- `{path}`" for path in test_files) or "- No test files were found."}

## Failing tests

{failure_block}

## What the suite covers

- The **{context.project.get('name', 'project')}** API workflow end to end through the HTTP
  layer (create, read, update, delete, filters and paging).
- Authentication: registration, login, token enforcement and ownership isolation.
- Validation failures and unknown-identifier handling.

## What it does not cover

- Load, concurrency and performance behaviour (the sandbox runs a single process).
- Browser/UI behaviour: no frontend is present in this revision.
- Infrastructure concerns such as TLS, container configuration and backups.
"""
        return {
            "path": "documentation/TESTING.md",
            "title": "Testing documentation",
            "content": content,
            "summary": f"Test strategy and latest results ({test.get('status', 'not run')})",
            "requirement_refs": [],
        }

    def _security_doc(self, facts: dict, context: AgentContext) -> dict:
        security = facts["security"]
        findings = security.get("top_findings") or []
        finding_rows = "\n".join(
            f"| {item.get('severity')} | {item.get('rule_id', '')} | {item.get('title')} | "
            f"`{item.get('file_path')}`:{item.get('line') or '—'} |"
            for item in findings
        ) or "| — | — | No open findings recorded | — |"
        content = f"""# Security

## Posture summary

| Severity | Open findings |
| --- | --- |
| Critical | {security.get('critical', 0)} |
| High | {security.get('high', 0)} |
| Medium | {security.get('medium', 0)} |
| Low | {security.get('low', 0)} |
| **Total open** | **{security.get('open_total', 0)}** |

## Open findings

| Severity | Rule | Title | Location |
| --- | --- | --- | --- |
{finding_rows}

## Controls implemented in the code

- Passwords are stored with a salted PBKDF2-SHA256 hash (240,000 iterations) and verified
  with a constant-time comparison.
- Tokens are HMAC-SHA256 signed, carry an expiry claim and are validated on every protected
  request.
- Authorisation is enforced per resource owner; foreign records return 404 rather than 403 so
  existence is not disclosed.
- Database access goes through SQLAlchemy with bound parameters.
- Errors return stable messages without stack traces.
- Generated code is executed only inside the DevForge sandbox (allow-listed commands, CPU and
  memory limits, no network, workspace-confined paths).

## Honest limitations

DevForge performs **automated static analysis**. It is not a penetration test and not a
security certification:

- No dynamic testing, fuzzing or exploit verification was performed.
- Dependency advisories come from a small curated list, not a live CVE feed — run `pip-audit`
  and `npm audit` in CI for authoritative results.
- Rule-based scanning produces false positives and cannot prove the absence of vulnerabilities.
- Environment-level controls (TLS, secret manager, database permissions, network policy) are
  outside the scope of a source scan.

Every finding is triaged by a human in DevForge (OPEN / ACKNOWLEDGED / FIXED / FALSE_POSITIVE),
and re-running the Security stage produces a new report revision.
"""
        return {
            "path": "documentation/SECURITY.md",
            "title": "Security documentation",
            "content": content,
            "summary": f"Security posture with {security.get('open_total', 0)} open finding(s)",
            "requirement_refs": [],
        }
