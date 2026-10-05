"""Graph nodes: agent executions and human approval gates.

Each node is intentionally thin: it opens a short-lived database session, delegates
to the service layer (never duplicating business logic) and returns a partial state
update.  Approval nodes call LangGraph's ``interrupt`` so the graph genuinely
suspends until a human decision is recorded — the workflow cannot advance on its own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from langgraph.types import interrupt

from app.core.events import bus
from app.core.logging import get_logger
from app.models.enums import (
    ApprovalStatus,
    ApprovalDecision,
    ApprovalStatus,
    ArtifactType,
    ExecutionTrigger,
    FindingStatus,
    Stage,
    StageStatus,
    WorkflowStatus,
)
from app.services.agent_runtime import AgentRunRequest, AgentRuntime
from app.services.approval_service import ApprovalService
from app.services.artifact_service import ArtifactService
from app.services.audit import AuditService
from app.services.change_set import ChangeSetService
from app.services.project_service import ProjectService
from app.services.workspace import WorkspaceService
from app.utils.time import utcnow
from app.workflows.state import DevForgeState, STAGE_LABELS

logger = get_logger("devforge.workflow.nodes")

AGENT_TASKS: dict[str, str] = {
    "requirement": "Produce the requirement specification for this project.",
    "architecture": "Produce the architecture specification from the approved requirements.",
    "developer": "Implement the approved architecture as working code.",
    "testing": "Produce the test plan, write the tests and execute them in the sandbox.",
    "security": "Run the security analysis of the implementation and report findings.",
    "documentation": "Generate the project documentation from the approved artifacts.",
}

#: Which approval gate follows which agent stage.
GATE_FOR_STAGE = {
    Stage.REQUIREMENTS.value: ("requirements_approval", "Requirement specification"),
    Stage.ARCHITECTURE.value: ("architecture_approval", "Architecture specification"),
    Stage.DEVELOPMENT.value: ("code_review", "Generated code changes"),
    Stage.TESTING.value: ("test_review", "Test results"),
    Stage.SECURITY.value: ("security_review", "Security analysis"),
    Stage.DOCUMENTATION.value: ("documentation_approval", "Documentation"),
}


def _now() -> str:
    return utcnow().isoformat()


def _stage_update(state: DevForgeState, stage: str, **fields: Any) -> dict[str, Any]:
    """Return a state delta that merges ``fields`` into one stage record."""
    records = {key: dict(value) for key, value in (state.get("stage_records") or {}).items()}
    record = records.setdefault(stage, {"status": StageStatus.PENDING.value, "iterations": 0})
    record.update(fields)
    return {"stage_records": records, "current_stage": stage}


def _security_result_payload(scan: dict[str, Any]) -> dict[str, Any]:
    findings = scan.get("findings") or []
    return {
        "counts": scan.get("counts", {}),
        "findings": len(findings),
        "files_scanned": scan.get("files_scanned", 0),
        "finding_details": [
            {
                key: finding.get(key, "")
                for key in (
                    "severity", "rule_id", "title", "file_path", "line",
                    "description", "evidence", "recommendation",
                )
            }
            for finding in findings[:8]
        ],
    }


# --------------------------------------------------------------------------- #
# agent nodes
# --------------------------------------------------------------------------- #
def _agent_node(state: DevForgeState, agent_key: str, *, stage: str,
                task: str | None = None, instructions: str = "") -> dict[str, Any]:
    """Run an agent and fold its result into the workflow state."""
    from app.core.database import session_scope

    project_id = state["project_id"]
    run_id = state.get("run_id")
    resolved_task = task or AGENT_TASKS.get(agent_key, "")
    human_instructions = instructions or state.get("instructions", "")

    bus.emit(
        "workflow_updated", project_id,
        run_id=run_id, stage=stage, node=f"{agent_key}_agent",
        status=StageStatus.RUNNING.value, message=f"{STAGE_LABELS.get(stage, stage)} stage started",
    )

    with session_scope() as db:
        runtime = AgentRuntime(db)
        outcome, execution = runtime.execute(
            AgentRunRequest(
                project_id=project_id,
                agent_key=agent_key,
                task=resolved_task,
                instructions=human_instructions,
                trigger=ExecutionTrigger.WORKFLOW,
                run_id=run_id,
                # Workflow executions are attributed to the agent catalogue; the human
                # decision that authorised them is recorded on the approval row.
                user=None,
                query=human_instructions or resolved_task,
            )
        )
        artifacts = ArtifactService(db).list_for_project(project_id, stage=stage, limit=5)

    delta: dict[str, Any] = {
        "messages": state.get("messages", []) + [
            {
                "agent": agent_key,
                "stage": stage,
                "summary": outcome.summary,
                "at": _now(),
                "execution_id": execution.id,
            }
        ],
        "total_steps": state.get("total_steps", 0) + 1,
        "last_decision": {},
    }
    delta.update(_stage_update(
        state, stage,
        status=StageStatus.AWAITING_APPROVAL.value,
        artifact_id=artifacts[0].id if artifacts else None,
        artifact_title=artifacts[0].title if artifacts else "",
        summary=outcome.summary[:400],
        started_at=(state.get("stage_records", {}).get(stage, {}) or {}).get("started_at") or _now(),
        finished_at=_now(),
    ))
    iterations = dict(state.get("iterations") or {})
    iterations[stage] = iterations.get(stage, 0) + 1
    delta["iterations"] = iterations

    # The human gate is opened here rather than inside the approval node: LangGraph
    # re-executes an interrupted node when the graph resumes, so the interrupt node
    # must stay free of side effects (otherwise every resume would file a duplicate
    # approval request).
    gate, gate_label = GATE_FOR_STAGE[stage]
    artifact_id = (delta["stage_records"].get(stage) or {}).get("artifact_id")
    with session_scope() as db:
        artifact = ArtifactService(db).get(artifact_id) if artifact_id else None
        approval = ApprovalService(db).request(
            project_id=project_id,
            stage=stage,
            gate=gate,
            artifact=artifact,
            agent_key=agent_key,
            run_id=run_id,
            summary=f"{gate_label} is ready for human review",
            meta={"agent_key": agent_key, "summary": outcome.summary[:400]},
        )
        delta["stage_records"][stage] = {
            **(delta["stage_records"].get(stage) or {}),
            "approval_id": approval.id,
            "approval_status": approval.status,
        }

    payload = outcome.structured or {}
    if agent_key == "requirement":
        delta["requirements"] = payload
    elif agent_key == "architecture":
        delta["architecture"] = payload
    elif agent_key == "developer":
        delta["source_changes"] = {
            "artifact_id": artifacts[0].id if artifacts else None,
            "file_count": outcome.meta.get("file_count", 0),
            "additions": outcome.meta.get("additions", 0),
            "deletions": outcome.meta.get("deletions", 0),
            "files": [change["path"] for change in outcome.file_changes][:40],
        }
    elif agent_key == "testing":
        delta["test_results"] = outcome.meta.get("test_run", {})
    elif agent_key == "security":
        delta["security_results"] = _security_result_payload(
            outcome.meta.get("security_scan", {})
        )
    elif agent_key == "documentation":
        delta["documentation"] = {
            "files": [draft.path for draft in outcome.artifacts],
            "count": len(outcome.artifacts),
        }
    if outcome.warnings:
        delta["warnings"] = state.get("warnings", []) + outcome.warnings[:3]
    return delta


def requirement_agent_node(state: DevForgeState) -> dict[str, Any]:
    return _agent_node(state, "requirement", stage=Stage.REQUIREMENTS.value)


def architecture_agent_node(state: DevForgeState) -> dict[str, Any]:
    return _agent_node(state, "architecture", stage=Stage.ARCHITECTURE.value)


def developer_agent_node(state: DevForgeState) -> dict[str, Any]:
    instructions = state.get("instructions", "")
    task = AGENT_TASKS["developer"]
    security = state.get("security_results") or {}
    if security.get("findings"):
        details = security.get("finding_details") or []
        if details:
            finding_lines = []
            for finding in details:
                location = finding.get("file_path") or "unknown file"
                if finding.get("line"):
                    location += f":{finding['line']}"
                finding_lines.append(
                    f"- [{finding.get('severity', 'UNKNOWN')}] {finding.get('rule_id', '')} "
                    f"{finding.get('title', 'Security finding')} at {location}. "
                    f"Issue: {finding.get('description', '')[:300]} "
                    f"Evidence: {finding.get('evidence', '')[:200]} "
                    f"Recommended fix: {finding.get('recommendation', '')[:300]}"
                )
            security_feedback = (
                f"Security Agent reported {security['findings']} finding(s). Remediate these: "
                + "\n".join(finding_lines)
            )
            if security["findings"] > len(details):
                security_feedback += f"\n- {security['findings'] - len(details)} additional finding(s) omitted."
        else:
            security_feedback = (
                f"Security Agent reported {security['findings']} finding(s) "
                f"({security.get('counts', {})}); inspect the security report and remediate them."
            )
        instructions = f"{instructions}\n\n{security_feedback}".strip()

    test_results = state.get("test_results") or {}
    if (test_results.get("status") or "").upper() in {"FAILED", "ERROR"}:
        failures = [
            item for item in test_results.get("results", [])
            if (item.get("status") or "").upper() in {"FAILED", "ERROR"}
        ][:8]
        counts = (
            f"{test_results.get('failed', 0)} failed, "
            f"{test_results.get('errors', 0)} errors out of "
            f"{test_results.get('total', 0)} tests"
        )
        if failures:
            failure_lines = [
                f"- {item.get('name', 'Unnamed test')} ({item.get('status')})"
                + (f" in {item.get('file_path')}" if item.get("file_path") else "")
                + (f": {item.get('message', '')[:500]}" if item.get("message") else "")
                for item in failures
            ]
            test_feedback = (
                f"Testing Agent reported {counts}. Fix these failures before delivery:\n"
                + "\n".join(failure_lines)
            )
        else:
            diagnostics = test_results.get("notes") or []
            raw_output = test_results.get("raw_output", "")
            test_feedback = (
                f"Testing Agent could not produce a passing test run ({counts}). "
                "Diagnose and fix the test execution or collection error."
            )
            if diagnostics:
                test_feedback += " Notes: " + "; ".join(str(note)[:300] for note in diagnostics[:4])
            if raw_output:
                test_feedback += f"\nTest runner output:\n{raw_output[-1500:]}"
        task = (
            "Fix the reported failing tests in the current implementation. Inspect the failing "
            "test and relevant source files, make the smallest code change that addresses the "
            "root cause, and return a reviewable code change set. Do not respond with an "
            "explanation-only result.\n\n" + test_feedback
        )
        instructions = f"{instructions}\n\n{test_feedback}".strip()
    return _agent_node(
        state, "developer", stage=Stage.DEVELOPMENT.value,
        task=task, instructions=instructions,
    )


def testing_agent_node(state: DevForgeState) -> dict[str, Any]:
    return _agent_node(state, "testing", stage=Stage.TESTING.value)


def security_agent_node(state: DevForgeState) -> dict[str, Any]:
    return _agent_node(state, "security", stage=Stage.SECURITY.value)


def documentation_agent_node(state: DevForgeState) -> dict[str, Any]:
    return _agent_node(state, "documentation", stage=Stage.DOCUMENTATION.value)


# --------------------------------------------------------------------------- #
# approval gates (human in the loop)
# --------------------------------------------------------------------------- #
def _approval_node(state: DevForgeState, stage: str) -> dict[str, Any]:
    """Suspend the graph until a human decides, then apply that decision.

    Deliberately side-effect free: the approval row and the artifact are created by
    the preceding agent node, so a resume (which re-runs this function) cannot file a
    second request. The decision itself is recorded by the API/engine before the graph
    is resumed.
    """
    from app.core.database import session_scope

    gate, label = GATE_FOR_STAGE[stage]
    project_id = state["project_id"]
    record = (state.get("stage_records") or {}).get(stage, {}) or {}
    artifact_id = record.get("artifact_id")
    approval_id = record.get("approval_id") or ""

    if not approval_id:  # defensive: e.g. a run resumed from an older checkpoint
        with session_scope() as db:
            existing = ApprovalService(db).open_for_run(state.get("run_id", ""), gate)
            approval_id = existing.id if existing else ""

    # ---- suspend here until a human decides (LangGraph interrupt) ----
    decision = interrupt(
        {
            "approval_id": approval_id,
            "gate": gate,
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "artifact_id": artifact_id,
            "artifact_title": record.get("artifact_title", ""),
            "summary": record.get("summary", ""),
            "question": f"Approve the {label.lower()} to continue?",
            "options": [item.value for item in ApprovalDecision],
        }
    )

    decision_value = (decision or {}).get("decision", ApprovalDecision.REQUEST_CHANGES.value)
    comments = (decision or {}).get("comments", "")
    instructions = (decision or {}).get("instructions", "")

    delta: dict[str, Any] = {
        "approval": {
            "approval_id": approval_id,
            "stage": stage,
            "gate": gate,
            "decision": decision_value,
            "comments": comments,
            "instructions": instructions,
        },
        "approval_status": decision_value,
        "pending_approval_id": "",
        "last_decision": decision or {},
        "messages": state.get("messages", []) + [
            {
                "agent": "human",
                "stage": stage,
                "summary": f"Human decision: {decision_value}"
                           + (f" — {comments}" if comments else ""),
                "at": _now(),
            }
        ],
    }
    if decision_value == ApprovalDecision.APPROVE.value:
        if stage == Stage.REQUIREMENTS.value:
            delta["approved_requirements"] = record.get("artifact_id", "")
        elif stage == Stage.ARCHITECTURE.value:
            delta["approved_architecture"] = record.get("artifact_id", "")
        delta.update(_stage_update(state, stage, status=StageStatus.COMPLETED.value,
                                   approval_status=ApprovalStatus.APPROVED.value))
        # a code change set reaches the workspace only after this approval
        if stage == Stage.DEVELOPMENT.value and artifact_id:
            with session_scope() as db:
                artifact = ArtifactService(db).get(artifact_id)
                if artifact is not None and artifact.type == ArtifactType.CHANGE_SET.value:
                    plan = ChangeSetService(db).ensure_applied(artifact)
                    delta["applied_change_set_id"] = artifact_id
                    logger.info("Applied change set %s (%s files)", artifact_id,
                                len(plan.changes))
    else:
        delta.update(
            _stage_update(
                state, stage,
                status=StageStatus.RUNNING.value,
                approval_status=decision_value,
                summary=f"Human requested changes: {comments[:200]}",
            )
        )
        instruction_text = "\n".join(part for part in (comments, instructions) if part)
        if instruction_text:
            delta["instructions"] = instruction_text
    return delta


def requirements_approval_node(state: DevForgeState) -> dict[str, Any]:
    return _approval_node(state, Stage.REQUIREMENTS.value)


def architecture_approval_node(state: DevForgeState) -> dict[str, Any]:
    return _approval_node(state, Stage.ARCHITECTURE.value)


def code_review_node(state: DevForgeState) -> dict[str, Any]:
    return _approval_node(state, Stage.DEVELOPMENT.value)


def test_review_node(state: DevForgeState) -> dict[str, Any]:
    return _approval_node(state, Stage.TESTING.value)


def security_review_node(state: DevForgeState) -> dict[str, Any]:
    return _approval_node(state, Stage.SECURITY.value)


def documentation_approval_node(state: DevForgeState) -> dict[str, Any]:
    return _approval_node(state, Stage.DOCUMENTATION.value)


# --------------------------------------------------------------------------- #
# delivery
# --------------------------------------------------------------------------- #
def delivery_node(state: DevForgeState) -> dict[str, Any]:
    """Prepare the GitHub delivery (never pushes automatically)."""
    from app.core.database import session_scope

    from app.services.github_service import GitHubService

    project_id = state["project_id"]
    with session_scope() as db:
        service = GitHubService(db)
        status = service.status(project_id)
        branch = status.get("branch") or ""

    if not status.get("connected"):
        delivery = {
            "status": "SKIPPED",
            "reason": "No GitHub repository is connected to this project. "
                      "Connect one from the Delivery tab to publish the approved work.",
            "requires_confirmation": False,
        }
    else:
        delivery = {
            "status": "AWAITING_CONFIRMATION",
            "branch": branch,
            "changes": len(status.get("changes", [])),
            "requires_confirmation": True,
            "reason": "Committed and pushed work requires explicit human confirmation.",
        }

    delta = {
        "delivery": delivery,
        "total_steps": state.get("total_steps", 0) + 1,
        "messages": state.get("messages", []) + [
            {"agent": "system", "stage": Stage.DELIVERY.value,
             "summary": f"Delivery: {delivery['status']} — {delivery.get('reason', '')}"[:300],
             "at": _now()},
        ],
    }
    delta.update(_stage_update(
        state, Stage.DELIVERY.value,
        status=StageStatus.COMPLETED.value if delivery["status"] == "SKIPPED"
        else StageStatus.AWAITING_APPROVAL.value,
        summary=delivery.get("reason", "")[:400], finished_at=_now(),
    ))
    bus.emit("workflow_updated", project_id, run_id=state.get("run_id"), stage=Stage.DELIVERY.value,
             status=delta["stage_records"][Stage.DELIVERY.value]["status"],
             message="Delivery prepared")
    return delta


def escalate_node(state: DevForgeState) -> dict[str, Any]:
    """Circuit breaker: too many revisions — hand control back to the human."""
    project_id = state["project_id"]
    stage = state.get("current_stage", "")
    reason = (
        f"The {STAGE_LABELS.get(stage, stage).lower()} stage reached its revision limit "
        f"({state.get('max_stage_iterations')} attempts). Human intervention is required: "
        "revise the request, edit the artifact directly, or continue with the current output."
    )
    bus.emit("workflow_paused", project_id, run_id=state.get("run_id"), stage=stage,
             reason=reason)
    delta: dict[str, Any] = {
        "status": WorkflowStatus.PAUSED.value,
        "errors": state.get("errors", []) + [reason],
        "messages": state.get("messages", []) + [
            {"agent": "system", "stage": stage, "summary": reason, "at": _now()}
        ],
    }
    delta.update(_stage_update(state, stage, status=StageStatus.FAILED.value, error=reason))
    return delta


def finalize_node(state: DevForgeState) -> dict[str, Any]:
    """Mark the run complete and summarise what was produced."""
    project_id = state["project_id"]
    completed = [
        stage for stage, record in (state.get("stage_records") or {}).items()
        if record.get("status") in {StageStatus.COMPLETED.value, StageStatus.AWAITING_APPROVAL.value}
    ]
    summary = (
        f"Workflow finished. Stages completed: {', '.join(STAGE_LABELS.get(s, s) for s in completed)}. "
        f"Artifacts: {len(state.get('messages', []))} agent steps recorded."
    )
    bus.emit("workflow_completed", project_id, run_id=state.get("run_id"), summary=summary)
    delta: dict[str, Any] = {
        "status": WorkflowStatus.COMPLETED.value,
        "messages": state.get("messages", []) + [
            {"agent": "system", "stage": "DELIVERY", "summary": summary, "at": _now()}
        ],
    }
    return delta


AGENT_FOR_STAGE = {
    Stage.REQUIREMENTS.value: "requirement",
    Stage.ARCHITECTURE.value: "architecture",
    Stage.DEVELOPMENT.value: "developer",
    Stage.TESTING.value: "testing",
    Stage.SECURITY.value: "security",
    Stage.DOCUMENTATION.value: "documentation",
}


def _agent_for_stage(stage: str) -> str:
    """Which agent owns a stage (used for approval attribution)."""
    return AGENT_FOR_STAGE.get(stage, "developer")
