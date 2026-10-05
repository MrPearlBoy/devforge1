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
