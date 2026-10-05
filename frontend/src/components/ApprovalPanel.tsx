import { useEffect, useState } from "react";
import { api, ApiError } from "../services/api";
import type { Approval, Artifact } from "../types/api";
import { formatTime, statusLabel, statusTone } from "../hooks/useApi";
import { Card, ErrorNote, Loading } from "./ui";

const GATE_HINTS: Record<string, string> = {
  requirements_approval: "Read the specification, then approve or ask for changes.",
  architecture_approval: "Check components, data model and API surface before approving.",
  code_review: "Review the diff. The code only reaches the workspace after you approve.",
  test_review: "Inspect the test plan and the sandbox results before approving.",
  security_review: "Triage the findings; a blocker can be sent back to the Developer Agent.",
  documentation_approval: "Confirm the documents are accurate for this project.",
  chat_change_request: "The Developer Agent proposed changes in chat — approve to apply them.",
};

/**
 * The human gate. Shows the artefact under review, the reviewer's options and the recorded
 * decision trail; every action posts to the API and resumes (or redirects) the workflow.
 */
export function ApprovalPanel({
  approval,
  onDecided,
}: {
  approval: Approval;
  onDecided?: () => void;
}) {
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [loading, setLoading] = useState(false);
  const [comments, setComments] = useState("");
  const [instructions, setInstructions] = useState("");
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");
  const [showDiff, setShowDiff] = useState(false);

  useEffect(() => {
    if (!approval.artifact_id) {
      setArtifact(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api
      .artifact(approval.artifact_id)
      .then((value) => {
        if (cancelled) return;
        setArtifact(value);
        setEditedContent(value.content);
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [approval.artifact_id]);

  const pending = approval.status === "PENDING";

  async function decide(kind: "approve" | "reject" | "changes") {
    setBusy(kind);
    setError("");
    try {
      const body = {
        comments,
        instructions,
        ...(kind === "approve" && editing && artifact
          ? { edited_content: editedContent }
          : {}),
      };
      if (kind === "approve") await api.approve(approval.id, body);
      else if (kind === "reject") await api.reject(approval.id, body);
      else await api.requestChanges(approval.id, { comments, instructions });
      setComments("");
      setInstructions("");
      setEditing(false);
      onDecided?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The decision could not be recorded.");
    } finally {
      setBusy("");
    }
  }

  const changes = (artifact?.data?.changes as { path: string; diff: string; additions: number; deletions: number }[]) || [];

  return (
    <Card
      title={`${approval.artifact_title || approval.gate} — human approval`}
      subtitle={GATE_HINTS[approval.gate] || "Review this stage before the workflow continues."}
      actions={<span className={`chip ${statusTone(approval.status)}`}>{statusLabel(approval.status)}</span>}
    >
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <div className="min-w-0">
          <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 sm:grid-cols-3">
            <div>
              <dt className="font-semibold text-slate-400">Stage</dt>
              <dd className="text-slate-700">{statusLabel(approval.stage)}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-400">Requested by</dt>
              <dd className="text-slate-700">{approval.requested_by_agent_key || "—"}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-400">Requested</dt>
              <dd className="text-slate-700">{formatTime(approval.requested_at || approval.created_at)}</dd>
            </div>
            {approval.decided_at && (
              <>
                <div>
                  <dt className="font-semibold text-slate-400">Decided</dt>
                  <dd className="text-slate-700">{formatTime(approval.decided_at)}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="font-semibold text-slate-400">Decision notes</dt>
                  <dd className="text-slate-700">{approval.comments || "—"}</dd>
                </div>
              </>
            )}
          </dl>

          {loading && <Loading label="Loading artifact…" />}

          {artifact && !loading && (
            <div className="space-y-3">
              {approval.artifact_type === "CHANGE_SET" && changes.length > 0 && (
                <div className="rounded-lg border border-slate-200">
                  <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
                    <p className="text-xs font-semibold text-slate-600">
                      Proposed file changes ({changes.length})
                    </p>
                    <button className="text-xs font-medium text-forge-700" onClick={() => setShowDiff((v) => !v)}>
                      {showDiff ? "Hide diffs" : "Show diffs"}
                    </button>
                  </div>
                  <ul className="divide-y divide-slate-100">
                    {changes.map((change) => (
                      <li key={change.path} className="px-3 py-2">
                        <div className="flex items-center justify-between gap-3">
                          <code className="truncate font-mono text-xs text-slate-800">{change.path}</code>
                          <span className="shrink-0 text-[11px] text-slate-500">
                            <span className="text-emerald-600">+{change.additions}</span>{" "}
                            <span className="text-rose-600">-{change.deletions}</span>
                          </span>
                        </div>
                        {showDiff && change.diff && (
                          <pre className="mt-2 max-h-72 overflow-auto rounded bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100">
                            {change.diff}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {editing && pending ? (
                <textarea
                  className="input font-mono text-xs"
                  rows={18}
                  value={editedContent}
                  onChange={(event) => setEditedContent(event.target.value)}
                />
              ) : (
                <pre className="max-h-96 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed whitespace-pre-wrap text-slate-800">
                  {artifact.content || approval.artifact_preview || "(no content)"}
                </pre>
              )}
            </div>
          )}

          {!artifact && !loading && (
            <p className="rounded-lg bg-slate-50 px-3 py-6 text-center text-xs text-slate-500">
              This gate has no artefact attached (for example a delivery confirmation).
            </p>
          )}
        </div>

        <div className="space-y-3">
          {pending ? (
            <>
              <div>
                <label className="label" htmlFor="comments">
                  Comments
                </label>
                <textarea
                  id="comments"
                  className="input"
                  rows={3}
                  placeholder="What did you check? What must change?"
                  value={comments}
                  onChange={(event) => setComments(event.target.value)}
                />
              </div>
              <div>
                <label className="label" htmlFor="instructions">
                  Instructions for the agent (optional)
                </label>
                <textarea
                  id="instructions"
                  className="input"
                  rows={2}
                  placeholder="e.g. add acceptance criteria for deadline filtering"
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                />
              </div>
              {artifact && (
                <label className="flex items-center gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={editing}
                    onChange={(event) => setEditing(event.target.checked)}
                  />
                  Edit the artefact content before approving
                </label>
              )}
              <ErrorNote message={error} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary" disabled={!!busy} onClick={() => void decide("approve")}>
                  {busy === "approve" ? "Approving…" : "Approve"}
                </button>
                <button className="btn-secondary" disabled={!!busy} onClick={() => void decide("changes")}>
                  {busy === "changes" ? "Sending…" : "Request changes"}
                </button>
                <button className="btn-danger" disabled={!!busy} onClick={() => void decide("reject")}>
                  {busy === "reject" ? "Rejecting…" : "Reject"}
                </button>
              </div>
              <p className="text-[11px] leading-relaxed text-slate-500">
                Your decision is stored with your user id, comments and a timestamp, and it
                resumes the orchestration run (or sends the stage back with a bounded revision
                budget).
              </p>
            </>
          ) : (
            <div className="space-y-2 text-xs text-slate-600">
              <p className="font-semibold text-slate-700">
                Decision: {statusLabel(approval.status)}
              </p>
              <p>{approval.comments || "No comments recorded."}</p>
              {approval.decided_at && <p className="text-slate-400">at {formatTime(approval.decided_at)}</p>}
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
