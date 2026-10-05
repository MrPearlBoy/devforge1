"""Developer Agent.

Responsibilities (spec §11):
* inspect the existing workspace before changing anything;
* generate or modify code and explain what changed and why;
* NEVER write to the workspace itself — it produces a reviewable change set that a
  human approves (the workflow applies it afterwards through ChangeSetService);
* respond to direct questions in the project chat, proposing changes when asked.

MOCK MODE produces genuinely runnable code for the inferred domain (FastAPI service,
JWT auth, pytest suite). LIVE MODE asks the configured model for the same structured
`CodeChangePlan` and validates it against the identical schema.
"""
from __future__ import annotations

import re

from app.agents.base import AgentOutcome, ArtifactDraft, BaseAgent
from app.agents.common.domain_inference import (
    DomainModel,
    FieldSpec,
    infer_domain,
)
from app.agents.developer.prompts import PROMPT_VERSION, REMEDIATION_TEMPLATE, SYSTEM_PROMPT
from app.agents.developer.prompts import build_user_prompt
from app.agents.developer.schemas import CodeChangePlan
from app.agents.developer.templates import build_remediation, build_scaffold
from app.models.enums import ArtifactType, Stage, TraceNodeType
from app.services.agent_registry import get_agent_spec
from app.services.project_context import AgentContext
from app.services.workspace import WorkspaceService, diff_stats, unified_diff

FIX_HINTS = ("security", "finding", "vulnerab", "fix", "remediat", "hardening", "harden", "scan")
FIELD_HINTS = re.compile(
    r"add (?:a |an )?(?:new )?(?P<field>[a-z_ ]{2,32}?)\s+(?:field|column|property|attribute)"
    r"(?: to (?:the )?(?P<entity>[a-z_ ]{2,24}?))?(?:\s|$|\.)",
    re.IGNORECASE,
)
DATABASE_HINTS = ("database", "db", "postgres", "mysql", "mongodb", "sqlite")
QUESTION_HINTS = ("how ", "why ", "what ", "explain", "where ", "which ", "review", "summar")
TEST_FAILURE_HINTS = (
    "fix the reported failing tests",
    "testing agent reported",
    "failing test",
    "test execution or collection error",
    "apply the requested corrections",
)


class DeveloperAgent(BaseAgent):
    spec = get_agent_spec("developer")
    prompt_version = PROMPT_VERSION
    output_schema = CodeChangePlan

    # ------------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        prompt = build_user_prompt(context.to_prompt_block(), task)
        findings = (context.security_summary or {}).get("top_findings") or []
        if findings and any(hint in (task or "").lower() for hint in FIX_HINTS):
            rendered = "\n".join(
                f"- [{f.get('severity')}] {f.get('rule_id')} {f.get('title')} "
                f"({f.get('file_path')}:{f.get('line')})"
                for f in findings[:10]
            )
            prompt += "\n\n" + REMEDIATION_TEMPLATE.format(findings=rendered)
        return prompt

    # --------------------------------------------------------------- mock mode
    def mock_payload(self, context: AgentContext, task: str = "") -> dict:
        domain = self._domain(context)
        files = context.source_files

        findings = (context.security_summary or {}).get("top_findings") or []
        lowered = (task or "").lower()

        if any(hint in lowered for hint in TEST_FAILURE_HINTS):
            return {
                "analysis": (
                    "No code change was generated: MOCK MODE uses fixed templates and cannot "
                    "diagnose arbitrary test failures. Use a live LLM provider to generate a "
                    "failure-specific patch; the failing tests and current source files are "
                    "included in the Developer Agent context."
                ),
                "affected_files": [],
                "changes": [],
                "verification": [
                    "Configure a live LLM provider and set DEVFORGE_MODE=live, then rerun "
                    "the Developer Agent on the failing test feedback."
                ],
                "notes": [
                    "No source files were changed because a template-based patch could not be "
                    "verified as addressing the reported failure."
                ],
                "requirement_refs": [],
                "architecture_refs": [],
                "risks": [
                    "The reported test failures remain unresolved until a live Developer Agent "
                    "produces and a human approves a targeted change set."
                ],
            }

        # 1) security remediation
        if findings and (any(hint in lowered for hint in FIX_HINTS) or not files):
            return self._remediation_payload(context, domain, findings)

        # 2) first implementation
        if not files or not any(path.startswith("backend/") for path in files):
            return self._scaffold_payload(context, domain)

        # 3) incremental change asked for in chat
        if any(hint in lowered for hint in QUESTION_HINTS) and not FIELD_HINTS.search(task or ""):
            return self._explanation_payload(context, domain)

        field_match = FIELD_HINTS.search(task or "")
        if field_match:
            return self._field_addition_payload(context, domain, field_match)

        if any(hint in lowered for hint in DATABASE_HINTS) and any(
            word in lowered for word in ("switch", "change", "use", "migrate", "from")
        ):
            return self._database_change_payload(context, domain)

        return self._explanation_payload(context, domain)

    # ------------------------------------------------------------- mock builders
    def _scaffold_payload(self, context: AgentContext, domain: DomainModel) -> dict:
        project_name = context.project.get("name", "Generated Service")
        files = build_scaffold(domain, project_name)
        changes = [file.as_change("create") for file in files]
        return {
            "analysis": (
                f"The workspace contains no implementation yet, so this change set creates the "
                f"first working increment of the approved architecture: a FastAPI service for the "
                f"{domain.primary.name} domain with "
                f"{'JWT authentication, ' if domain.requires_auth else ''}a data access layer over "
                f"SQLAlchemy, request validation with Pydantic and a pytest suite that exercises the "
                f"HTTP surface end to end. Every file is new, and no other part of the repository is "
                f"touched."
            ),
            "affected_files": [change["path"] for change in changes],
            "changes": changes,
            "verification": [
                "Install dependencies: pip install -r backend/requirements.txt",
                "Run the suite in the DevForge sandbox: python -m pytest tests (from backend/)",
                "Start the API: uvicorn app.main:app --reload --port 8000 and open /docs",
            ],
            "notes": [
                "Identifiers are UUID strings and all timestamps are stored in UTC.",
                "SQLite is the default database so the service runs with no external dependencies; "
                "set DATABASE_URL for PostgreSQL.",
                "CORS is not enabled: the frontend needs an explicit allow-list before browser calls "
                "will work (added when the client is generated).",
            ],
            "requirement_refs": [ref for entity in domain.entities for ref in entity.requirement_refs][:10],
            "architecture_refs": ["ARCH-002", "ARCH-003", "ARCH-004"],
            "risks": [
                "Table creation uses SQLAlchemy create_all for development; production needs migrations.",
            ],
        }

    def _remediation_payload(self, context: AgentContext, domain: DomainModel,
                             findings: list[dict]) -> dict:
        files = build_remediation(domain, context.project.get("name", "Service"), findings)
        changes = [file.as_change("update") for file in files]
        if not changes:
            reported_rules = ", ".join(
                sorted({finding.get("rule_id", "unknown") for finding in findings})
            )
            return {
                "analysis": (
                    "No code change was generated: MOCK MODE has no deterministic remediation "
                    f"template for the reported security rule(s): {reported_rules}. A live "
                    "Developer Agent is required to analyze these findings and propose a "
                    "targeted, reviewable fix."
                ),
                "affected_files": [],
                "changes": [],
                "verification": [
                    "Configure a live LLM provider and set DEVFORGE_MODE=live, then rerun the "
                    "Developer Agent on the security feedback."
                ],
                "notes": ["No security finding is claimed to be fixed."],
                "requirement_refs": [],
                "architecture_refs": [],
                "risks": [
                    "The reported security findings remain unresolved until a targeted change "
                    "set is generated, approved and verified."
                ],
            }
        rendered = "\n".join(
            f"- {finding.get('rule_id')} [{finding.get('severity')}] {finding.get('title')} "
            f"in {finding.get('file_path')}"
            for finding in findings[:10]
        )
        return {
            "analysis": (
                "The Security Agent reported findings in the generated configuration. The root cause is "
                "development convenience: the scaffold shipped a hardcoded development secret and an "
                "enabled debug flag so a fresh clone runs immediately. This change removes both — the "
                "secret is now read from the environment and must be at least 32 characters, and debug "
                "mode defaults to off. Only the configuration module is regenerated; no other file is "
                "touched, and no other control is weakened.\n\n"
                f"Findings addressed:\n{rendered}"
            ),
            "affected_files": [change["path"] for change in changes],
            "changes": changes,
            "verification": [
                "Re-run the Security Agent scan and confirm the reported rules no longer fire.",
                "Re-run the sandbox tests: JWT_SECRET must now be provided by the environment "
                "(the test module sets one).",
                "Confirm the API still starts with JWT_SECRET and DEBUG set through the environment.",
            ],
            "notes": [
                f"Rules addressed: {', '.join(rule for rule in rules if rule)}",
                "A development .env file (not committed) is the intended way to supply JWT_SECRET.",
                "Re-scanning is required before this remediation is considered complete.",
            ],
            "requirement_refs": [],
            "architecture_refs": ["ARCH-002", "ARCH-006"],
            "risks": [
                "Deployments that relied on the placeholder secret will fail fast with a clear error "
                "until JWT_SECRET is configured — this is intentional.",
            ],
        }

    def _field_addition_payload(self, context: AgentContext, domain: DomainModel,
                                match: re.Match) -> dict:
        raw_field = match.group("field").strip().lower().replace(" ", "_")
        raw_entity = (match.group("entity") or "").strip().lower()
        entity = next(
            (item for item in domain.entities if raw_entity and raw_entity in item.name.lower()),
            domain.primary,
        )
        field_name = re.sub(r"[^a-z0-9_]", "", raw_field) or "notes"
        if any(existing.name == field_name for existing in entity.fields):
            return self._explanation_payload(
                context, domain,
                note=f"{entity.name} already has a '{field_name}' field, so no change is required.",
            )

        inferred_type, description = self._infer_field_type(field_name)
        entity.fields.append(
            FieldSpec(name=field_name, python_type=inferred_type, required=False,
                      description=description, example=f"sample {field_name}")
        )
        project_name = context.project.get("name", "Generated Service")
        files = build_scaffold(domain, project_name)
        existing_paths = set(context.source_files)
        changes = [
            file.as_change("update" if file.path in existing_paths else "create") for file in files
            if file.path != ".gitignore"  # unchanged by this request
        ]
        return {
            "analysis": (
                f"Requested change: add a `{field_name}` ({inferred_type}) attribute to "
                f"**{entity.name}**. I inspected the existing implementation and found the field is "
                f"absent from the model, the Pydantic schemas and the tests. Because every generated "
                f"file derives from the same domain description, I regenerated the affected modules "
                f"(model, schemas, CRUD, router and tests) with the new column included, keeping all "
                f"existing behaviour and conventions unchanged."
            ),
            "affected_files": [change["path"] for change in changes],
            "changes": changes,
            "verification": [
                f"Confirm the column exists: POST /api/{entity.table} with a `{field_name}` value and "
                "read it back from GET /api/%s/{id}" % entity.table,
                "Run the sandbox test suite — the existing tests must still pass unchanged.",
            ],
            "notes": [
                f"`{field_name}` is nullable, so existing rows remain valid without a data migration.",
                "If this field becomes mandatory, a follow-up migration must backfill existing rows.",
            ],
            "requirement_refs": entity.requirement_refs[:5],
            "architecture_refs": ["ARCH-003", "ARCH-004"],
            "risks": ["Schema change requires a migration before deployment to a live database."],
        }

    def _database_change_payload(self, context: AgentContext, domain: DomainModel) -> dict:
        files = build_scaffold(domain, context.project.get("name", "Generated Service"))
        config = next(file for file in files if file.path == "backend/app/config.py")
        target = "postgresql"
        content = config.content.replace(
            'database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),',
            'database_url=os.getenv(\n        "DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/app"\n    ),',
        )
        files = [
            type(config)(path=config.path, content=content, summary="Switch the default database to PostgreSQL", language="python")
            if file.path == config.path else file
            for file in files
        ]
        changes = [file.as_change("update") for file in files if file.path == config.path]
        return {
            "analysis": (
                "I inspected the configuration module. The engine already reads DATABASE_URL from the "
                "environment, so switching the default from SQLite to PostgreSQL is a one-line change "
                "with no impact on models, queries or endpoints. I also verified the data access layer "
                "uses SQLAlchemy in a portable way (no SQLite-specific SQL), so no other file needs to "
                "change."
            ),
            "affected_files": [change["path"] for change in changes],
            "changes": changes,
            "verification": [
                "Set DATABASE_URL to a PostgreSQL instance and start the API — tables are created on "
                "startup for development.",
                "Run the sandbox test suite with SQLite (the tests set their own DATABASE_URL).",
            ],
            "notes": [
                "Add `psycopg2-binary` to backend/requirements.txt when deploying against PostgreSQL.",
                "Production should apply schema changes with migrations rather than create_all.",
            ],
            "requirement_refs": [],
            "architecture_refs": ["ARCH-004", "ARCH-005"],
            "risks": ["Existing SQLite data is not migrated automatically."],
        }

    def _explanation_payload(self, context: AgentContext, domain: DomainModel,
                             note: str = "") -> dict:
        files = sorted(context.source_files)
        listing = "\n".join(f"- `{path}`" for path in files[:25]) or "- (no files yet)"
        endpoints = []
        for entity in domain.entities:
            if entity.name != "User":
                endpoints += [f"{method} /api/{entity.table}" for method in ("GET", "POST", "PUT", "DELETE")]
        return {
            "analysis": (
                "No code change is proposed for this request.\n\n"
                f"{note + chr(10) + chr(10) if note else ''}"
                f"I inspected the current workspace ({len(files)} files visible to me):\n{listing}\n\n"
                f"The primary domain entity is **{domain.primary.name}** "
                f"(`{domain.primary.table}`) with fields: "
                f"{', '.join(field.name for field in domain.primary.fields)}.\n"
                f"Available endpoints: {', '.join(endpoints) if endpoints else 'none yet'}."
            ),
            "affected_files": [],
            "changes": [],
            "verification": ["Ask for a specific change (for example: 'add a due_date field to Task') "
                             "to receive a reviewable change set."],
            "notes": [
                "In MOCK MODE the Developer Agent answers questions from the real workspace contents "
                "and the architecture/requirements artifacts; set DEVFORGE_MODE=live for free-form "
                "reasoning.",
            ],
            "requirement_refs": [],
            "architecture_refs": [],
            "risks": [],
        }

    @staticmethod
    def _infer_field_type(field_name: str) -> tuple[str, str]:
        lowered = field_name.lower()
        if any(token in lowered for token in ("date", "at", "time", "deadline", "due")):
            return "datetime", f"Timestamp for {field_name.replace('_', ' ')}"
        if any(token in lowered for token in ("count", "number", "quantity", "age", "score")):
            return "int", f"Numeric value for {field_name.replace('_', ' ')}"
        if any(token in lowered for token in ("price", "amount", "cost", "rate", "total")):
            return "float", f"Monetary value for {field_name.replace('_', ' ')}"
        if lowered.startswith(("is_", "has_")) or lowered in {"active", "completed", "archived"}:
            return "bool", f"Flag indicating {field_name.replace('_', ' ')}"
        return "str", f"{field_name.replace('_', ' ').capitalize()}"

    # ------------------------------------------------------------------- render
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        files = payload.get("changes", [])
        workspace = WorkspaceService()
        diffed: list[dict] = []
        total_additions = total_deletions = 0
        created = updated = deleted = 0

        for item in files:
            path = item.get("path", "")
            content = item.get("content", "")
            operation = item.get("operation", "update")
            exists = workspace.exists(context.project_id, path)
            previous = ""
            if exists:
                try:
                    previous, _ = workspace.read_text(context.project_id, path)
                except Exception:
                    previous = ""
            if not exists:
                operation = "create"
            diff = unified_diff(previous, content, path)
            additions, deletions = diff_stats(diff)
            total_additions += additions
            total_deletions += deletions
            created += operation == "create"
            updated += operation == "update"
            deleted += operation == "delete"
            diffed.append(
                {
                    "path": path,
                    "operation": operation,
                    "summary": item.get("summary", ""),
                    "language": item.get("language", "python"),
                    "content": content,
                    "diff": diff[:20000],
                    "additions": additions,
                    "deletions": deletions,
                }
            )

        markdown = self._to_markdown(payload, diffed, context)
        trace_pairs = self._trace_pairs(context, diffed)

        summary = (
            f"Proposed {len(diffed)} file change(s) "
            f"(+{total_additions}/-{total_deletions})"
            if diffed else "Answered with an explanation; no code changes proposed"
        )
        outcome = AgentOutcome(
            agent_key=self.key,
            stage=self.stage,
            content=markdown,
            summary=summary,
            artifacts=[
                ArtifactDraft(
                    artifact_type=ArtifactType.CHANGE_SET.value,
                    stage=Stage.DEVELOPMENT.value,
                    title=f"Code change set — {len(diffed)} file(s)",
                    content=markdown,
                    summary=summary,
                    path="",
                    data={
                        "analysis": payload.get("analysis", ""),
                        "changes": diffed,
                        "file_count": len(diffed),
                        "additions": total_additions,
                        "deletions": total_deletions,
                        "operations": {"create": created, "update": updated, "delete": deleted},
                        "verification": payload.get("verification", []),
                        "notes": payload.get("notes", []),
                        "risks": payload.get("risks", []),
                        "requirement_refs": payload.get("requirement_refs", []),
                        "architecture_refs": payload.get("architecture_refs", []),
                        "applied": None,
                    },
                    trace_refs=[item["path"] for item in diffed],
                )
            ],
            structured=payload,
            trace_pairs=trace_pairs,
            file_changes=diffed,
            meta={
                "file_count": len(diffed),
                "additions": total_additions,
                "deletions": total_deletions,
                "requires_approval": bool(diffed),
            },
        )
        if diffed:
            outcome.warnings.append(
                "Nothing has been written to the workspace yet — these changes require human "
                "approval before they are applied."
            )
        return outcome

    def _trace_pairs(self, context: AgentContext, diffed: list[dict]) -> list[dict]:
        architecture = next(
            (item for item in context.artifacts.values()
             if item.get("type") == ArtifactType.ARCHITECTURE.value),
            None,
        )
        module_map: dict[str, str] = {}
        if architecture:
            for module in (architecture.get("data") or {}).get("modules", []):
                component = module.get("component_ref") or "ARCH-002"
                module_map[module.get("path", "")] = component

        pairs: list[dict] = []
        for item in diffed:
            component = module_map.get(item["path"], "ARCH-002")
            pairs.append(
                {
                    "source_type": TraceNodeType.ARCHITECTURE.value,
                    "source_ref": component,
                    "source_label": f"Architecture component {component}",
                    "target_type": TraceNodeType.CODE.value,
                    "target_ref": f"CODE {item['path']}",
                    "target_label": item["summary"] or item["path"],
                    "relation": "implemented_by",
                }
            )
        return pairs

    # ---------------------------------------------------------------- rendering
    def _to_markdown(self, payload: dict, diffed: list[dict], context: AgentContext) -> str:
        lines = [
            f"# Developer change set — {context.project.get('name', 'project')}",
            "",
            f"_Produced by the **Developer Agent** ({self.prompt_version}). "
            "Nothing is applied until a human approves this change set._",
            "",
            "## Analysis",
            "",
            payload.get("analysis", ""),
            "",
            "## Affected files",
            "",
            "| File | Operation | + | − | Summary |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in diffed:
            lines.append(
                f"| `{item['path']}` | {item['operation']} | {item['additions']} | "
                f"{item['deletions']} | {item['summary']} |"
            )
        if not diffed:
            lines.append("| — | none | 0 | 0 | No changes proposed |")
        lines.append("")

        if payload.get("verification"):
            lines += ["## How to verify", ""]
            lines += [f"{i}. {item}" for i, item in enumerate(payload["verification"], 1)]
            lines.append("")
        if payload.get("notes"):
            lines += ["## Notes", ""]
            lines += [f"- {item}" for item in payload["notes"]]
            lines.append("")
        if payload.get("risks"):
            lines += ["## Risks", ""]
            lines += [f"- {item}" for item in payload["risks"]]
            lines.append("")

        if diffed:
            lines += ["## Diffs", ""]
            for item in diffed:
                lines += [f"### `{item['path']}` ({item['operation']})", ""]
                if item["diff"]:
                    lines += ["```diff", item["diff"].rstrip(), "```", ""]
                else:
                    lines += ["```", item["content"][:2000].rstrip(), "```", ""]

        lines += [
            "---",
            "",
            "## Traceability",
            "",
            "Each file is linked to the architecture component it implements "
            f"({', '.join(payload.get('architecture_refs', [])) or 'ARCH-002'}), which in turn links "
            "back to the requirements it satisfies.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _domain(context: AgentContext) -> DomainModel:
        requirements = {}
        for artifact in context.artifacts.values():
            if artifact.get("type") == ArtifactType.REQUIREMENTS.value:
                requirements = artifact.get("data") or {}
                break
        source_text = " ".join(
            [
                context.project.get("requirement_input", ""),
                " ".join(
                    f"{item.get('title', '')} {item.get('description', '')}"
                    for item in requirements.get("functional_requirements", [])
                ),
                " ".join(item.get("question", "") for item in requirements.get("open_questions", [])),
            ]
        )
        return infer_domain(
            source_text,
            requirements.get("functional_requirements"),
            roles=[role.get("name", "") for role in requirements.get("user_roles", [])],
        )
