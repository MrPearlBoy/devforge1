import { useOutletContext, useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi, formatTime, statusLabel, statusTone } from "../hooks/useApi";
import type { Approval, WorkflowOverview } from "../types/api";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { Card, Chip, EmptyState, ErrorNote, Loading } from "../components/ui";

interface Context {
  overview: WorkflowOverview;
  reloadOverview: () => Promise<void>;
}

/**
 * The human control plane: every gate, its artefact, the decision buttons and the full
 * history of who approved what and when.
 */
export function ApprovalsPage() {
  const { projectId = "" } = useParams();
  const { reloadOverview } = useOutletContext<Context>();
  const approvals = useApi(() => api.approvals(projectId), [projectId], { pollMs: 5000 });

  const pending = approvals.data?.filter((item) => item.status === "PENDING") ?? [];
  const decided = approvals.data?.filter((item) => item.status !== "PENDING") ?? [];

  async function refresh() {
    await approvals.reload();
    await reloadOverview();
  }

  return (
    <div className="space-y-4">
      <ErrorNote message={approvals.error} />

      <Card
        title="Open gates"
        subtitle="The workflow is suspended until you decide — nothing advances on its own"
        actions={
          pending.length ? (
            <span className="chip bg-amber-50 text-amber-700 ring-1 ring-amber-200">
              {pending.length} awaiting you
            </span>
          ) : (
            <span className="chip bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200">
              nothing pending
            </span>
          )
        }
      >
        {approvals.loading && !approvals.data && <Loading label="Loading approvals…" />}
        {!approvals.loading && !pending.length && (
          <EmptyState
            title="No approval is waiting"
            hint="Approve or request changes on the Workflow tab to move the pipeline forward; the next gate appears here automatically."
          />
        )}
        <div className="space-y-4">
          {pending.map((approval) => (
            <ApprovalPanel key={approval.id} approval={approval} onDecided={() => void refresh()} />
          ))}
        </div>
      </Card>

      <Card title="Decision history" subtitle="Immutable record: who decided what, when and why">
        <ul className="divide-y divide-slate-100">
          {decided.map((approval) => (
            <li key={approval.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <div className="min-w-[12rem] flex-1">
                <p className="text-sm font-medium text-slate-800">
                  {statusLabel(approval.gate)}{" "}
                  <span className="text-xs font-normal text-slate-500">· {statusLabel(approval.stage)}</span>
                </p>
                <p className="truncate text-[11px] text-slate-500">
                  {approval.artifact_title || "no artefact"} · requested by{" "}
                  {approval.requested_by_agent_key || "system"}
                </p>
                {approval.comments && (
                  <p className="mt-1 text-[11px] italic text-slate-500">“{approval.comments}”</p>
                )}
              </div>
              <div className="text-right">
                <Chip label={approval.status} tone={statusTone(approval.status)} />
                <p className="mt-1 text-[10px] text-slate-400">
                  {approval.decided_by_user_name || "system"} · {formatTime(approval.decided_at)}
                </p>
              </div>
            </li>
          ))}
          {!decided.length && (
            <li className="py-6 text-center text-xs text-slate-500">No decisions recorded yet.</li>
          )}
        </ul>
      </Card>

      <Card title="How decisions behave" subtitle="Rule set implemented by the workflow engine">
        <ul className="space-y-1.5 text-xs text-slate-600">
          <li>
            <strong>Approve</strong> — the stage is marked complete, the artefact becomes
            APPROVED, and an approved code change set is written to the workspace.
          </li>
          <li>
            <strong>Request changes</strong> — the responsible agent re-runs with your comments and
            instructions as the highest-priority context (bounded by{" "}
            {approvals.data ? "the configured revision budget" : "MAX_STAGE_ITERATIONS"}).
          </li>
          <li>
            <strong>Reject</strong> — the run stops at that stage; the artefact is marked REJECTED
            and the reason is kept in the audit trail.
          </li>
          <li>
            Every decision stores the user id, stage, gate, artefact, comments, timestamp and
            optional inline edits, and immediately resumes the suspended LangGraph run.
          </li>
        </ul>
      </Card>
    </div>
  );
}

export type { Approval };
