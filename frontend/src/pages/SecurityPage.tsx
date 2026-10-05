import { useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { useApi, formatTime, statusLabel, statusTone } from "../hooks/useApi";
import type { WorkflowOverview } from "../types/api";
import { Card, Chip, ConfirmDialog, EmptyState, ErrorNote, Loading, Stat } from "../components/ui";

interface Context {
  overview: WorkflowOverview;
  reloadOverview: () => Promise<void>;
}

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];

/** Security posture: scan summary, findings with triage, and remediation hand-off. */
export function SecurityPage() {
  const { projectId = "" } = useParams();
  const { reloadOverview } = useOutletContext<Context>();
  const summary = useApi(() => api.securitySummary(projectId), [projectId], { pollMs: 10000 });
  const findings = useApi(() => api.findings(projectId), [projectId], { pollMs: 10000 });
  const [filter, setFilter] = useState("OPEN");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [remediation, setRemediation] = useState<string | null>(null);
  const [confirmScan, setConfirmScan] = useState(false);

  const rows = (findings.data || [])
    .filter((finding) => (filter === "ALL" ? true : finding.status === filter))
    .sort(
      (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
    );

  async function scan() {
    setBusy("scan");
    setError("");
    try {
      await api.runSecurityScan(projectId);
      await summary.reload();
      await findings.reload();
      await reloadOverview();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The scan could not be completed.");
    } finally {
      setBusy("");
      setConfirmScan(false);
    }
  }

  async function triage(findingId: string, status: string) {
    setBusy(findingId);
    try {
      await api.triageFinding(findingId, { status, comment: "Triaged in the workspace UI." });
      await findings.reload();
      await summary.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Triage failed.");
    } finally {
      setBusy("");
    }
  }

  async function remediate(findingId: string) {
    setBusy(findingId);
    setError("");
    try {
      const result = await api.remediate(projectId, findingId);
      setRemediation(
        result.approval_id
          ? `The Developer Agent prepared a fix (${result.proposed_files.join(", ")}). Review it on the Approvals tab.`
          : result.summary || "The Developer Agent produced a change proposal.",
      );
      await reloadOverview();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Remediation could not be proposed.");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat label="Files scanned" value={summary.data?.files_scanned ?? 0} />
        <Stat label="Critical" value={summary.data?.critical ?? 0} />
        <Stat label="High" value={summary.data?.high ?? 0} />
        <Stat label="Medium" value={summary.data?.medium ?? 0} />
        <Stat label="Low / info" value={(summary.data?.low ?? 0) + (summary.data?.info ?? 0)} />
      </div>

      <ErrorNote message={error || summary.error} />
      {remediation && (
        <p className="rounded-lg bg-forge-50 px-3 py-2 text-xs text-forge-800 ring-1 ring-forge-200">
          {remediation}{" "}
          <Link className="font-semibold underline" to={`/projects/${projectId}/approvals`}>
            Open approvals
          </Link>
        </p>
      )}

      <Card
        title="Security review"
        subtitle={summary.data?.disclaimer || "Static analysis + model review"}
        actions={
          <div className="flex items-center gap-2">
            {summary.data?.created_at && (
              <span className="text-[11px] text-slate-500">scan {formatTime(summary.data.created_at)}</span>
            )}
            <button className="btn-primary" disabled={!!busy} onClick={() => setConfirmScan(true)}>
              {busy === "scan" ? "Scanning…" : "Run a security scan"}
            </button>
          </div>
        }
      >
        {findings.loading && !findings.data && <Loading label="Loading findings…" />}
        {!findings.loading && !findings.data?.length && (
          <EmptyState
            title="No findings recorded"
            hint="Run a scan, or wait for the Security Agent to run during the SECURITY stage of the workflow."
          />
        )}

        <div className="mb-3 flex flex-wrap gap-2">
          {["OPEN", "ACKNOWLEDGED", "FIXED", "FALSE_POSITIVE", "ALL"].map((option) => (
            <button
              key={option}
              onClick={() => setFilter(option)}
              className={`chip ${
                filter === option
                  ? "bg-forge-600 text-white"
                  : "bg-slate-100 text-slate-600 ring-1 ring-slate-200"
              }`}
            >
              {statusLabel(option)}
            </button>
          ))}
        </div>

        <ul className="space-y-3">
          {rows.map((finding) => (
            <li key={finding.id} className="rounded-lg border border-slate-200 p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-800">
                    <span className="font-mono text-[11px] text-slate-400">{finding.rule_id}</span>{" "}
                    {finding.title}
                  </p>
                  <p className="text-[11px] text-slate-500">
                    {finding.file_path}
                    {finding.line ? `:${finding.line}` : ""} · {finding.category} · detected by{" "}
                    {finding.detected_by}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Chip label={finding.severity} tone={statusTone(finding.severity)} />
                  <Chip label={finding.status} tone={statusTone(finding.status)} />
                </div>
              </div>

              <p className="mt-2 text-xs text-slate-700">{finding.description}</p>
              {finding.evidence && (
                <pre className="mt-2 overflow-auto rounded bg-slate-900 p-2 font-mono text-[11px] text-slate-100">
                  {finding.evidence}
                </pre>
              )}
              <p className="mt-2 text-xs text-slate-600">
                <strong className="text-slate-500">Recommendation:</strong> {finding.recommendation}
              </p>
              {finding.trace_refs?.length > 0 && (
                <p className="mt-1 text-[11px] text-slate-500">traces {finding.trace_refs.join(", ")}</p>
              )}

              <div className="mt-2 flex flex-wrap gap-2">
                {["ACKNOWLEDGED", "FIXED", "FALSE_POSITIVE"].map((status) => (
                  <button
                    key={status}
                    className="btn-secondary px-2.5 py-1 text-[11px]"
                    disabled={busy === finding.id || finding.status === status}
                    onClick={() => void triage(finding.id, status)}
                  >
                    Mark {statusLabel(status)}
                  </button>
                ))}
                {(finding.severity === "CRITICAL" || finding.severity === "HIGH") && (
                  <button
                    className="btn-primary px-2.5 py-1 text-[11px]"
                    disabled={busy === finding.id}
                    onClick={() => void remediate(finding.id)}
                  >
                    Ask the Developer Agent to fix it
                  </button>
                )}
              </div>
            </li>
          ))}
          {!rows.length && findings.data?.length ? (
            <li className="py-6 text-center text-xs text-slate-500">
              No findings with status {statusLabel(filter)}.
            </li>
          ) : null}
        </ul>
      </Card>

      <ConfirmDialog
        open={confirmScan}
        title="Run a security scan?"
        confirmLabel="Run scan"
        body="The Security Agent runs a deterministic static analysis over the generated workspace and adds a model review of the design. Findings are stored and traced to the code they concern."
        onCancel={() => setConfirmScan(false)}
        onConfirm={() => void scan()}
      />
    </div>
  );
}
