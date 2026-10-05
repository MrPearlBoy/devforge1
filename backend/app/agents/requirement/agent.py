"""Requirement Agent.

Live mode  : LLM produces a ``RequirementsSpec`` (structured, validated).
Mock mode  : a deterministic analyser derives the same structure from the human's
             requirement text — real parsing (sentence decomposition, role and
             action detection), never random or hard-coded project content.
Both modes produce the same artifact: ``requirements/requirements.md``.
"""
from __future__ import annotations

import re

from app.agents.base import AgentOutcome, ArtifactDraft, BaseAgent
from app.agents.requirement.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from app.agents.requirement.schemas import RequirementsSpec
from app.models.enums import ArtifactType, Stage, TraceNodeType
from app.services.agent_registry import get_agent_spec
from app.services.project_context import AgentContext

ROLE_KEYWORDS = {
    "student": "Student", "teacher": "Teacher", "faculty": "Faculty", "admin": "Administrator",
    "administrator": "Administrator", "customer": "Customer", "client": "Client",
    "user": "End User", "manager": "Manager", "employee": "Employee", "patient": "Patient",
    "doctor": "Doctor", "guest": "Guest", "hr": "HR Staff", "seller": "Seller",
    "vendor": "Vendor", "driver": "Driver", "member": "Member", "author": "Author",
    "reader": "Reader", "owner": "Owner", "moderator": "Moderator",
}

ACTION_VERBS = (
    "create", "add", "update", "edit", "delete", "remove", "view", "list", "search", "filter",
    "login", "log in", "sign in", "register", "sign up", "logout", "upload", "download",
    "submit", "approve", "reject", "assign", "track", "mark", "complete", "schedule",
    "notify", "generate", "export", "import", "comment", "rate", "review", "share", "manage",
    "cancel", "confirm", "reset", "pay", "order", "book", "check", "monitor", "report",
)

PRIORITY_HINTS = (
    ("must", "HIGH"), ("shall", "HIGH"), ("critical", "HIGH"), ("essential", "HIGH"),
    ("required", "HIGH"), ("should", "MEDIUM"), ("needs to", "MEDIUM"), ("could", "LOW"),
    ("nice to have", "LOW"), ("optional", "LOW"),
)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+|;\s*")
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "with", "for", "from", "that", "this", "there",
    "their", "they", "them", "can", "should", "will", "must", "shall", "able", "to", "be",
    "is", "are", "was", "were", "in", "on", "at", "by", "of", "it", "its", "as", "so",
    "users", "user", "system", "app", "application", "web", "website", "platform", "also",
    "have", "has", "where", "which", "when", "who", "what", "very", "each", "any", "all",
    "into", "over", "after", "before", "own", "new", "page", "screen",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9_-]*", text or "")


def _title_from(sentence: str, max_words: int = 7) -> str:
    words = _words(sentence)
    if not words:
        return "Unnamed capability"
    clipped = words[:max_words]
    return " ".join(clipped).strip().capitalize()


def _priority_for(sentence: str) -> str:
    lowered = sentence.lower()
    for hint, priority in PRIORITY_HINTS:
        if hint in lowered:
            return priority
    return "MEDIUM"


def _sentences(text: str) -> list[str]:
    return [s.strip(" -•*\t") for s in SENTENCE_SPLIT.split(text or "") if len(s.strip()) > 3]


class RequirementAgent(BaseAgent):
    spec = get_agent_spec("requirement")
    prompt_version = PROMPT_VERSION
    output_schema = RequirementsSpec

    # ------------------------------------------------------------------- prompts
    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def build_prompt(self, context: AgentContext, task: str = "") -> str:
        return build_user_prompt(context.to_prompt_block(), task)

    # ---------------------------------------------------------------- mock mode
    def _role_in(sentence: str) -> str:
        """Detect the acting role mentioned in a sentence (Student, Admin, ...)."""
        lowered = sentence.lower()
        for keyword, label in ROLE_KEYWORDS.items():
            if re.search(rf"\b{re.escape(keyword)}s?\b", lowered):
                return label
        return "End User"

    @classmethod
    def _clauses_from(cls, sentence: str) -> list[str]:
        """Split a compound capability sentence into individual verb-phrase clauses.

        "students can create tasks, update tasks, delete tasks and mark tasks as
        completed" -> ["create tasks", "update tasks", "delete tasks",
                       "mark tasks as completed"]
        """
        parts = re.split(r",|\band\b|\balso\b|\bas well as\b", sentence, flags=re.IGNORECASE)
        clauses: list[str] = []
        for part in parts:
            cleaned = " ".join(_words(part)).strip()
            if len(cleaned.split()) < 2:
                continue
            lowered = cleaned.lower()
            if not any(verb in lowered for verb in ACTION_VERBS):
                continue
            # Rebuild the clause starting at the detected action verb so modal
            # prefixes such as "students should be able to" are dropped.
            words = cleaned.split()
            start = 0
            for position, word in enumerate(words):
                if any(word.lower() == verb or word.lower() == verb.split()[0] for verb in ACTION_VERBS):
                    if word.lower() in {"be", "can", "should", "must", "shall", "to", "not"}:
                        continue
                    start = position
                    break
            clause = " ".join(words[start:]).strip(" .")
            clause = re.sub(r"^(also|then|and)\s+", "", clause, flags=re.IGNORECASE)
            clause = re.sub(r"\b(their|the|a|an)\s+$", lambda m: m.group(0).strip(), clause)
            if len(clause.split()) >= 2:
                clauses.append(clause)
        if not clauses:  # fall back to the trimmed sentence
            trimmed = " ".join(_words(sentence))
            if trimmed:
                clauses.append(trimmed[:120])
        return clauses

    @staticmethod
    def _describe(clause: str, role: str, sentence: str) -> str:
        """Human-readable requirement statement, phrased as observable behaviour."""
        return (
            f"A {role.lower()} must be able to {clause.rstrip('.')}. "
            f"(Derived from the human input: \"{sentence.strip()[:220]}\")"
        )

    @staticmethod
    def _criteria(clause: str, role: str) -> list[str]:
        clean = clause.rstrip(".").lower()
        return [
            f"Given a signed-in {role.lower()}, when they {clean}, then the action succeeds and "
            "the change is visible without a manual refresh.",
            f"Given invalid or incomplete input while attempting to {clean}, the system shows a "
            "clear validation message and makes no change.",
        ]

    @staticmethod
    def _roles(source: str) -> list[dict]:
        found: list[dict] = []
        lowered = source.lower()
        for keyword, label in ROLE_KEYWORDS.items():
            if re.search(rf"\b{re.escape(keyword)}s?\b", lowered):
                if any(role["name"] == label for role in found):
                    continue
                found.append(
                    {
                        "id": f"ROLE-{len(found) + 1:03d}",
                        "name": label,
                        "description": f"{label} interacting with the system.",
                        "capabilities": [
                            "Sign in to the application",
                            "Access the features permitted for this role",
                        ],
                    }
                )
        if not found:
            found.append(
                {
                    "id": "ROLE-001",
                    "name": "End User",
                    "description": "Primary application user.",
                    "capabilities": ["Sign in", "Perform the core workflows of the application"],
                }
            )
        if not any(role["name"] == "Administrator" for role in found):
            found.append(
                {
                    "id": f"ROLE-{len(found) + 1:03d}",
                    "name": "Administrator",
                    "description": "Oversees configuration, access and data quality.",
                    "capabilities": [
                        "Manage user accounts and roles",
                        "Review system activity and configuration",
                    ],
                }
            )
        return found

    @staticmethod
    def _use_cases(functional: list[dict], roles: list[dict]) -> list[dict]:
        actor = roles[0]["name"] if roles else "End User"
        use_cases: list[dict] = []
        for index, requirement in enumerate(functional[:10], start=1):
            use_cases.append(
                {
                    "id": f"UC-{index:03d}",
                    "name": requirement["title"],
                    "actors": [actor],
                    "preconditions": ["The user is authenticated with sufficient permissions."],
                    "main_flow": [
                        f"The {actor.lower()} opens the relevant screen.",
                        requirement["description"][:220],
                        "The system validates the input and shows the resulting state.",
                    ],
                    "alternative_flow": [
                        "If input validation fails, the system shows a clear error and keeps the data unchanged."
                    ],
                    "requirement_refs": [requirement["id"]],
                }
            )
        return use_cases

    @staticmethod
    def _non_functionals(source: str, name: str) -> list[dict]:
        lowered = source.lower()
        nfrs = [
            {
                "id": "NFR-001",
                "category": "Performance",
                "description": "Interactive operations respond quickly under normal load.",
                "target": "p95 response time under 2 seconds for core screens with up to 100 concurrent users",
            },
            {
                "id": "NFR-002",
                "category": "Security",
                "description": "Authentication is required for all non-public functionality and "
                               "passwords are stored using a modern password hash.",
                "target": "No plaintext credentials in source control; CRITICAL/HIGH findings triaged "
                          "before release",
            },
            {
                "id": "NFR-003",
                "category": "Usability",
                "description": "The primary workflow is reachable within three interactions from login.",
                "target": "Usable on viewports from 360px wide upwards",
            },
            {
                "id": "NFR-004",
                "category": "Reliability",
                "description": "User data survives application restarts with consistent behaviour on errors.",
                "target": "No data loss on restart; all write operations are transactional",
            },
            {
                "id": "NFR-005",
                "category": "Maintainability",
                "description": "The codebase is modular with automated tests covering core workflows.",
                "target": "Automated test suite runs in under 2 minutes in the sandbox",
            },
        ]
        if any(word in lowered for word in ("report", "analytics", "dashboard", "scale", "thousand")):
            nfrs.append(
                {
                    "id": "NFR-006",
                    "category": "Scalability",
                    "description": "Reporting and listing endpoints remain responsive as records grow.",
                    "target": "List/report endpoints paginate and stay under 1 second with 50,000 records",
                }
            )
        return nfrs

    @staticmethod
    def _constraints(source: str) -> list[str]:
        lowered = source.lower()
        constraints = [
            "Single-node deployment target; no distributed infrastructure in this version.",
            "Technology choices must remain conventional and well documented (see architecture stage).",
        ]
        if "offline" in lowered or "no internet" in lowered:
            constraints.append("The application must work without internet connectivity.")
        if "deadline" in lowered or "week" in lowered or "month" in lowered:
            constraints.append("Delivery is time-boxed; scope must be trimmed before deadline slippage.")
        if "gst" in lowered or "payment" in lowered or "invoice" in lowered:
            constraints.append("Financial data handling must follow the applicable compliance rules.")
        return constraints

    @staticmethod
    def _assumptions(source: str, functional: list[dict]) -> list[str]:
        assumptions = [
            "Users have a modern web browser and a stable network connection.",
            "Email or username based sign-in is acceptable as the authentication mechanism.",
            "The application is used by a single organisation in this version (no multi-tenancy).",
        ]
        if len(functional) > 8:
            assumptions.append(
                "The large number of requested capabilities means the first release may need "
                "to be split into two iterations."
            )
        return assumptions

    @staticmethod
    def _open_questions(source: str) -> list[dict]:
        lowered = source.lower()
        questions: list[dict] = []
        if not any(word in lowered for word in ("login", "sign in", "auth", "password", "sso", "oauth")):
            questions.append(
                {
                    "question": "What authentication method should be used (email + password, SSO, OAuth)?",
                    "why_it_matters": "Determines the security design, user model and session handling.",
                    "blocks_progress": True,
                }
            )
        if not any(word in lowered for word in ("admin", "role", "permission")):
            questions.append(
                {
                    "question": "Are multiple user roles with different permissions required?",
                    "why_it_matters": "Affects the data model and every authorisation check.",
                    "blocks_progress": False,
                }
            )
        if "email" not in lowered and "notification" not in lowered and "notify" not in lowered:
            questions.append(
                {
                    "question": "Should the system send email or push notifications?",
                    "why_it_matters": "Adds an integration and background processing.",
                    "blocks_progress": False,
                }
            )
        questions.append(
            {
                "question": "What are the expected data volumes and peak concurrency?",
                "why_it_matters": "Sizes the database, caching and deployment approach.",
                "blocks_progress": False,
            }
        )
        if not any(word in lowered for word in ("backup", "retention", "privacy", "gdpr", "dpdp")):
            questions.append(
                {
                    "question": "What data retention, backup and privacy obligations apply?",
                    "why_it_matters": "Drives storage, deletion workflows and documentation.",
                    "blocks_progress": False,
                }
            )
        return questions

    @staticmethod
    def _baseline_requirements(name: str) -> list[dict]:
        """Used when the human's text contains no recognisable capability statement."""
        base = [
            ("Create a record", "The user can create a new record through a form with validation."),
            ("View records", "The user can view a list of records with paging and filtering."),
            ("Update a record", "The user can edit the fields of an existing record."),
            ("Delete a record", "The user can delete a record they own after confirming the action."),
            ("Authenticate", "The user can register, sign in and sign out securely."),
        ]
        return [
            {
                "id": f"REQ-{index:03d}",
                "title": title,
                "description": f"For {name}: {description}",
                "priority": "HIGH" if index <= 3 else "MEDIUM",
                "category": "Functional",
                "acceptance_criteria": [
                    f"Given an authenticated user, when they {title.lower()}, then the system "
                    "confirms success and reflects the change immediately."
                ],
            }
            for index, (title, description) in enumerate(base, start=1)
        ]

    # ------------------------------------------------------------------- render
    def render(self, payload: dict, context: AgentContext, task: str = "") -> AgentOutcome:
        functional = payload.get("functional_requirements", [])
        use_cases = payload.get("use_cases", [])
        roles = payload.get("user_roles", [])
        nfrs = payload.get("non_functional_requirements", [])
        questions = payload.get("open_questions", [])

        markdown = self._to_markdown(payload, context)
        trace_refs = [item["id"] for item in functional]

        outcome = AgentOutcome(
            agent_key=self.key,
            stage=self.stage,
            content=markdown,
            summary=(
                f"Captured {len(functional)} functional and {len(nfrs)} non-functional requirements, "
                f"{len(roles)} user roles, {len(use_cases)} use cases and {len(questions)} open questions."
            ),
            artifacts=[
                ArtifactDraft(
                    artifact_type=ArtifactType.REQUIREMENTS.value,
                    stage=Stage.REQUIREMENTS.value,
                    title=f"Requirements specification — {context.project.get('name', 'project')}",
                    content=markdown,
                    summary=f"{len(functional)} functional requirements",
                    path="requirements/requirements.md",
                    data=payload,
                    trace_refs=trace_refs,
                )
            ],
            structured=payload,
            trace_pairs=[],
            suggested_tasks=[
                {
                    "title": f"Implement {item['title']}",
                    "description": item["description"][:500],
                    "priority": item.get("priority", "MEDIUM"),
                    "stage": Stage.DEVELOPMENT.value,
                    "agent_key": "developer",
                    "requirement_refs": [item["id"]],
                }
                for item in functional[:8]
            ],
            meta={"requirement_count": len(functional)},
        )
        if questions:
            blocking = [q for q in questions if q.get("blocks_progress")]
            if blocking:
                outcome.warnings.append(
                    f"{len(blocking)} open question(s) block architecture decisions; "
                    "answer them or accept the stated assumptions before approving."
                )
        return outcome

    # ---------------------------------------------------------------- rendering
    def _to_markdown(self, payload: dict, context: AgentContext) -> str:
        project_name = context.project.get("name", "Project")
        lines: list[str] = [
            f"# Requirements Specification — {project_name}",
            "",
            f"_Produced by the **Requirement Agent** ({self.prompt_version}) — "
            f"status: awaiting human approval._",
            "",
            "## 1. Project overview",
            "",
            payload.get("project_overview", "").strip(),
            "",
        ]
        if payload.get("scope_in") or payload.get("scope_out"):
            lines += ["## 2. Scope", "", "**In scope**", ""]
            lines += [f"- {item}" for item in payload.get("scope_in", [])]
            lines += ["", "**Out of scope (this version)**", ""]
            lines += [f"- {item}" for item in payload.get("scope_out", [])]
            lines.append("")

        lines += ["## 3. Functional requirements", ""]
        for item in payload.get("functional_requirements", []):
            lines += [
                f"### {item['id']} — {item['title']}",
                "",
                f"- **Priority:** {item.get('priority', 'MEDIUM')}",
                f"- **Description:** {item['description']}",
            ]
            criteria = item.get("acceptance_criteria") or []
            if criteria:
                lines.append("- **Acceptance criteria:**")
                lines += [f"  - {criterion}" for criterion in criteria]
            lines.append("")

        lines += ["## 4. Non-functional requirements", "",
                  "| ID | Category | Requirement | Target |", "| --- | --- | --- | --- |"]
        for item in payload.get("non_functional_requirements", []):
            target = item.get("target") or "—"
            lines.append(f"| {item['id']} | {item.get('category', '')} | {item['description']} | {target} |")
        lines.append("")

        lines += ["## 5. User roles", ""]
        for role in payload.get("user_roles", []):
            lines.append(f"- **{role['id']} {role['name']}** — {role.get('description', '')}")
            for capability in role.get("capabilities", []):
                lines.append(f"  - {capability}")
        lines.append("")

        lines += ["## 6. Use cases", ""]
        for use_case in payload.get("use_cases", []):
            lines += [
                f"### {use_case['id']} — {use_case['name']}",
                "",
                f"- **Actors:** {', '.join(use_case.get('actors', [])) or '—'}",
                f"- **Requirement refs:** {', '.join(use_case.get('requirement_refs', [])) or '—'}",
            ]
            if use_case.get("preconditions"):
                lines.append("- **Preconditions:**")
                lines += [f"  - {p}" for p in use_case["preconditions"]]
            lines.append("- **Main flow:**")
            lines += [f"  {i}. {step}" for i, step in enumerate(use_case.get("main_flow", []), start=1)]
            if use_case.get("alternative_flow"):
                lines.append("- **Alternative flow:**")
                lines += [f"  - {step}" for step in use_case["alternative_flow"]]
            lines.append("")

        lines += ["## 7. Constraints", ""]
        lines += [f"- {item}" for item in payload.get("constraints", [])] or ["- None recorded"]
        lines += ["", "## 8. Assumptions", ""]
        lines += [f"- {item}" for item in payload.get("assumptions", [])] or ["- None recorded"]
        lines += ["", "## 9. Acceptance criteria for the release", ""]
        lines += [f"- [ ] {item}" for item in payload.get("acceptance_criteria", [])]
        lines += ["", "## 10. Open questions", ""]
        questions = payload.get("open_questions", [])
        if questions:
            lines += ["| Question | Why it matters | Blocks progress |", "| --- | --- | --- |"]
            for question in questions:
                blocking = "**Yes**" if question.get("blocks_progress") else "No"
                lines.append(
                    f"| {question['question']} | {question.get('why_it_matters', '')} | {blocking} |"
                )
        else:
            lines.append("- None — the input was sufficiently specific.")
        lines += [""]

        if payload.get("out_of_scope_risks"):
            lines += ["## 11. Risks noted during analysis", ""]
            lines += [f"- {item}" for item in payload["out_of_scope_risks"]]
            lines.append("")

        lines += [
            "---",
            "",
            "## Traceability",
            "",
            "The identifiers below (REQ-nnn, NFR-nnn, UC-nnn, ROLE-nnn) are the anchors used by the "
            "Architecture, Developer, Testing, Security and Documentation agents, and are stored as "
            "trace links in DevForge.",
            "",
            f"- Functional requirement ids: {', '.join(i['id'] for i in self._payload_items(payload, 'functional_requirements')) or '—'}",
            f"- Non-functional ids: {', '.join(i['id'] for i in self._payload_items(payload, 'non_functional_requirements')) or '—'}",
            "",
            "_Human approval is required before the Architecture Agent starts._",
        ]
        return "\n".join(lines)

    @staticmethod
    def _payload_items(payload: dict, key: str) -> list[dict]:
        return payload.get(key, [])
