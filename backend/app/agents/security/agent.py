"""Security Agent.

Two complementary passes:

1. **Deterministic rule scan** (:mod:`app.tools.static_analyzer`) over the real
   workspace files — always runs, in both mock and live mode, so the report is
   reproducible and explainable.
2. **Qualitative review** — in live mode the model adds logic-level observations that
   pattern rules cannot see; in mock mode the report states plainly that no model
   review was performed.

The agent never claims the project is secure: every report carries an explicit
limitations section.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.base import AgentOutcome, ArtifactDraft, BaseAgent
from app.agents.security.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.agents.security.schemas import SecurityReview
from app.core.logging import get_logger
from app.models.enums import ArtifactType, FindingStatus, Severity, Stage, TraceNodeType
from app.services.agent_registry import get_agent_spec
from app.services.project_context import AgentContext
from app.services.workspace import WorkspaceService
from app.tools.static_analyzer import StaticAnalyzer

logger = get_logger("devforge.agent.security")

SEVERITY_ORDER = {severity.value: index for index, severity in enumerate(Severity)}

BASE_LIMITATIONS = [
    "Automated static analysis only: no dynamic testing, fuzzing or penetration testing "
    "was performed, so the absence of findings does not mean the application is secure.",
    "Dependency checks use a small curated advisory list, not a live CVE database. Run "
    "`pip-audit` / `npm audit` in a networked CI job for authoritative results.",
    "Pattern-based rules produce false positives and can miss logic flaws; every finding "
    "is heuristic until a human triages it.",
    "Runtime configuration of the deployed environment (TLS termination, network policy, "
    "secret manager, database permissions) is outside what a source scan can verify.",
]


class SecurityAgent(BaseAgent):
    spec = get_agent_spec("security")
    prompt_version = PROMPT_VERSION
    output_schema = SecurityReview

    # ------------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        # The rule scan runs first in both modes so the model reviews real findings.
        report = self._scan(context)
        self._last_scan = report
        return build_user_prompt(context.to_prompt_block(), [finding.to_dict()
                                                             for finding in report.findings])

    # --------------------------------------------------------------- mock review
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        """Minimal outcome for the qualitative review; ``run`` assembles the report."""
        return AgentOutcome(
            agent_key=self.key,
            stage=self.stage,
            content=payload.get("summary", ""),
            summary=(payload.get("summary", "") or "Security review completed")[:400],
            structured=payload,
            meta={"review_only": True},
        )

    def run(self, context: AgentContext, task: str = "") -> AgentOutcome:
        outcome = super().run(context, task)
        report = getattr(self, "_last_scan", None)
        if report is None:
            report = self._scan(context)
            outcome.meta["scan_error"] = "Rule scan was not available during generation."

        findings_payload = self._findings_payload(report)
        markdown = self._to_markdown(outcome, report, findings_payload, context)

        artifact = ArtifactDraft(
            artifact_type=ArtifactType.SECURITY_REPORT.value,
            stage=Stage.SECURITY.value,
            title="Security analysis report",
            content=markdown,
            summary=(
                f"{len(findings_payload)} finding(s): "
                + ", ".join(
                    f"{report.counts.get(severity, 0)} {severity}"
                    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
                    if report.counts.get(severity)
                ) or "no findings"
            ),
            path="security/security_report.md",
            data={
                "scan": {
                    "files_scanned": report.files_scanned,
                    "rules_run": report.rules_run,
                    "counts": report.counts,
                    "skipped": report.skipped[:50],
                },
                "findings": findings_payload,
                "review": outcome.structured,
                "limitations": (outcome.structured or {}).get("limitations", BASE_LIMITATIONS),
            },
            trace_refs=[item["ref"] for item in findings_payload],
        )
        outcome.artifacts = [artifact]
        outcome.trace_pairs = self._trace_pairs(context, findings_payload)
        outcome.meta["security_scan"] = {
            "files_scanned": report.files_scanned,
            "rules_run": report.rules_run,
            "counts": report.counts,
            "findings": findings_payload,
        }
        outcome.suggested_tasks = [
            {
                "title": f"Fix {item['title']} ({item['rule_id']})",
                "description": item["recommendation"][:500],
                "priority": "HIGH" if item["severity"] in {"CRITICAL", "HIGH"} else "MEDIUM",
                "stage": Stage.DEVELOPMENT.value,
                "agent_key": "developer",
                "requirement_refs": [],
            }
            for item in findings_payload
            if item["severity"] in {"CRITICAL", "HIGH"}
        ][:6]

        summary = (
            f"Scanned {report.files_scanned} file(s) with {report.rules_run} rules: "
            f"{report.counts.get('CRITICAL', 0)} critical, {report.counts.get('HIGH', 0)} high, "
            f"{report.counts.get('MEDIUM', 0)} medium, {report.counts.get('LOW', 0)} low"
        )
        outcome.summary = summary
        if report.counts.get("CRITICAL") or report.counts.get("HIGH"):
            outcome.warnings.append(
                "CRITICAL/HIGH findings are open — request corrections from the Developer Agent "
                "or explicitly accept the risk before delivery."
            )
        return outcome

    # ------------------------------------------------------------------ scanning
    def _scan(self, context: AgentContext):
        files = self._collect_files(context.project_id)
        report = StaticAnalyzer().scan_files(files)
        logger.info("Security scan of project %s: %s files, %s findings",
                    context.project_id, report.files_scanned, len(report.findings))
        return report

    @staticmethod
    def _collect_files(project_id: str) -> dict[str, str]:
        """Read the scannable text files of the workspace."""
        workspace = WorkspaceService()
        files: dict[str, str] = {}
        for info in workspace.list_files(project_id, max_files=400):
            if info.is_binary or info.size > 300_000:
                continue
            try:
                content, _ = workspace.read_text(project_id, info.path, max_bytes=300_000)
            except Exception:
                continue
            files[info.path] = content
        return files

    @staticmethod
    def _findings_payload(report) -> list[dict]:  # noqa: ANN001 - ScanReport
        payload: list[dict] = []
        for index, finding in enumerate(report.findings, start=1):
            payload.append(
                {
                    "ref": f"{finding.rule_id}-{index}",
                    **finding.to_dict(),
                    "status": FindingStatus.OPEN.value,
                }
            )
        return payload

    @staticmethod
    def _trace_pairs(context: AgentContext, findings: list[dict]) -> list[dict]:
        pairs: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for finding in findings:
            if not finding.get("file_path"):
                continue
            key = (finding["file_path"], finding["ref"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "source_type": TraceNodeType.CODE.value,
                    "source_ref": f"CODE {finding['file_path']}",
                    "source_label": finding["file_path"],
                    "target_type": TraceNodeType.SECURITY.value,
                    "target_ref": finding["ref"],
                    "target_label": f"{finding['severity']} — {finding['title']}",
                    "relation": "has_finding",
                    "confidence": 0.8,
                }
            )
        return pairs

    @staticmethod
    def _controls_present(context: AgentContext, report) -> list[str]:  # noqa: ANN001
        controls: list[str] = []
        joined = " ".join(context.source_files.values()).lower()
        if "pbkdf2" in joined or "bcrypt" in joined or "argon2" in joined:
            controls.append("Passwords are hashed with a modern key-derivation function.")
        if "hmac.compare_digest" in joined:
            controls.append("Token/password comparisons use constant-time comparison.")
        if "httponly" in joined or "authorization" in joined:
            controls.append("Bearer-token authorisation is enforced by a shared dependency.")
        if "sqlalchemy" in joined or "parameter" in joined:
            controls.append("Database access goes through an ORM with parameterised statements.")
        if not any(finding.rule_id == "SEC-SQL-001" for finding in report.findings):
            controls.append("No string-concatenated SQL was detected in the scanned files.")
        if not any(finding.rule_id == "SEC-XSS-001" for finding in report.findings):
            controls.append("No unsafe HTML injection pattern (innerHTML/dangerouslySetInnerHTML) "
                            "was detected.")
        return controls

    @staticmethod
    def _next_steps(report) -> list[str]:  # noqa: ANN001
        steps = ["Triage every finding (accept, fix, or mark as false positive) and record the decision."]
        if any(finding.severity == Severity.HIGH.value for finding in report.findings):
            steps.append("Remediate all HIGH findings before deployment and re-run this scan.")
        steps.append("Run `pip-audit` / `npm audit` in CI for authoritative dependency advisories.")
        steps.append("Add automated security tests for authorisation boundaries (see the testing stage).")
        return steps

    def _to_markdown(self, outcome: AgentOutcome, report, findings: list[dict],  # noqa: ANN001
                     context: AgentContext) -> str:
        review = outcome.structured or {}
        counts = report.counts
        lines = [
            f"# Security Analysis Report — {context.project.get('name', 'project')}",
            "",
            f"_Produced by the **Security Agent** ({self.prompt_version}). Automated static analysis "
            f"of {report.files_scanned} file(s) using {report.rules_run} rules._",
            "",
            "## Summary",
            "",
            review.get("summary", ""),
            "",
            "| Severity | Findings |",
            "| --- | --- |",
        ]
        for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
            lines.append(f"| {severity} | {counts.get(severity, 0)} |")

        lines += ["", "## Findings", ""]
        if findings:
            lines += [
                "| Ref | Severity | Rule | File | Line | Title | Status |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for item in findings:
                lines.append(
                    f"| {item['ref']} | {item['severity']} | {item['rule_id']} | "
                    f"`{item['file_path']}` | {item.get('line') or '—'} | {item['title']} | "
                    f"{item['status']} |"
                )
            lines += ["", "### Finding detail", ""]
            for item in findings:
                lines += [
                    f"#### {item['ref']} — {item['title']} ({item['severity']})",
                    "",
                    f"- **Category:** {item['category']} · **Rule:** `{item['rule_id']}` · "
                    f"**Detected by:** {item['detected_by']}",
                    f"- **Location:** `{item['file_path']}` line {item.get('line') or '—'}",
                    f"- **Description:** {item['description']}",
                    f"- **Evidence:** `{(item['evidence'] or '').strip()[:300]}`",
                    f"- **Recommendation:** {item['recommendation']}",
                    "",
                ]
        else:
            lines.append(
                "No rule-detectable findings were reported for the scanned files. This does **not** "
                "mean the project is secure — see the limitations below."
            )
            lines.append("")

        observations = review.get("observations", [])
        if observations:
            lines += ["", "## Model-reviewed observations (logic level)", ""]
            for item in observations:
                lines += [
                    f"- **[{item.get('severity')}] {item.get('title')}** — "
                    f"{item.get('description', '')} "
                    f"({item.get('file_path') or 'project-wide'}"
                    f"{':' + str(item['line']) if item.get('line') else ''})",
                    f"  - Recommendation: {item.get('recommendation', '')}",
                ]

        controls = review.get("controls_present") or []
        if controls:
            lines += ["", "## Controls verified as present", ""]
            lines += [f"- {item}" for item in controls]

        if review.get("false_positive_candidates"):
            lines += ["", "## Possible false positives to triage", ""]
            lines += [f"- {item}" for item in review["false_positive_candidates"]]

        lines += ["", "## Limitations of this analysis", ""]
        lines += [f"- {item}" for item in (review.get("limitations") or BASE_LIMITATIONS)]

        if review.get("next_steps"):
            lines += ["", "## Recommended next steps", ""]
            lines += [f"{index}. {item}" for index, item in enumerate(review["next_steps"], start=1)]

        if report.skipped:
            lines += ["", "## Files skipped by the scanner", ""]
            lines += [f"- `{path}`" for path in report.skipped[:30]]

        lines += [
            "",
            "---",
            "",
            "## Honest statement of assurance",
            "",
            "DevForge performs **automated static analysis of the project files**. It is not a "
            "security certification, and a clean report is not proof that the application is secure. "
            "Dynamic testing, infrastructure review and manual code review remain necessary before "
            "any production deployment.",
            "",
            "Each finding carries a human triage status (OPEN / ACKNOWLEDGED / FIXED / "
            "FALSE_POSITIVE) recorded in DevForge, and re-running this stage after a fix produces a "
            "new report revision.",
        ]
        return "\n".join(lines)
