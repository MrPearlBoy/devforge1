import { useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { useApi, formatDuration, formatTime, statusLabel, statusTone } from "../hooks/useApi";
import type { WorkflowOverview } from "../types/api";
import { Card, Chip, ConfirmDialog, EmptyState, ErrorNote, Loading, Stat } from "../components/ui";

interface Context {
  overview: WorkflowOverview;
  reloadOverview: () => Promise<void>;
}

/** Test execution view: suite results, raw output and manual re-runs in the sandbox. */
export function TestsPage() {
  const { projectId = "" } = useParams();
  const { reloadOverview } = useOutletContext<Context>();
  const latest = useApi(() => api.latestTestRun(projectId), [projectId], { pollMs: 8000 });
  const history = useApi(() => api.testRuns(projectId), [projectId], { pollMs: 15000 });
  const sandbox = useApi(() => api.sandbox(projectId), [projectId]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [selectedRun, setSelectedRun] = useState<string>("");
  const [historical, setHistorical] = useState<Awaited<ReturnType<typeof api.testRun>> | null>(null);
  const [confirmRun, setConfirmRun] = useState(false);
  const [showOutput, setShowOutput] = useState(false);

  async function reload() {
    await latest.reload();
    await history.reload();
    await reloadOverview();
  }

  async function runSuite(agentDriven: boolean) {
    setBusy(agentDriven ? "agent" : "manual");
    setError("");
    try {
      if (agentDriven) await api.runTestingAgent(projectId);
      else await api.runTests(projectId);
      await reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The suite could not be executed.");
    } finally {
      setBusy("");
      setConfirmRun(false);
    }
  }

  const totals = latest.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Status" value={totals ? statusLabel(totals.status) : "—"} hint={totals ? `${totals.provider} sandbox` : ""} />
        <Stat label="Passed" value={totals ? `${totals.passed}/${totals.total}` : "—"} />
        <Stat
          label="Failures / errors"
          value={totals ? `${totals.failed + totals.errors}` : "—"}
          hint={totals ? `${totals.skipped} skipped` : ""}
        />
        <Stat label="Duration" value={formatDuration(totals?.duration_ms || 0)} hint={totals?.command} />
      </div>

      <ErrorNote message={error || latest.error} />

      <Card
        title="Test suite"
        subtitle="Executed inside the sandbox — never on the host directly"
        actions={
          <div className="flex gap-2">
            <button className="btn-secondary" disabled={!!busy} onClick={() => setConfirmRun(true)}>
              {busy === "manual" ? "Running…" : "Run suite now"}
            </button>
            <button className="btn-primary" disabled={!!busy} onClick={() => void runSuite(true)}>
              {busy === "agent" ? "Agent working…" : "Ask the Testing Agent"}
            </button>
          </div>
        }
      >
        {latest.loading && !latest.data && <Loading label="Loading test results…" />}
        {!latest.loading && !latest.data && (
          <EmptyState
            title="No test run yet"
            hint="The Testing Agent writes the test plan, generates the test suite and executes it in the sandbox during the TESTING stage."
          />
        )}

        {totals && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Chip label={totals.status} tone={statusTone(totals.status)} />
              <span className="text-[11px] text-slate-500">
                {statusLabel(totals.triggered_by)} · {formatTime(totals.created_at)}
              </span>
              <button
                className="ml-auto text-xs font-medium text-forge-700"
                onClick={() => setShowOutput((value) => !value)}
              >
                {showOutput ? "Hide raw output" : "Show raw output"}
              </button>
            </div>

            {showOutput && (
              <pre className="max-h-72 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] leading-relaxed text-slate-100">
                {(latest.data?.raw_output as string) || String(latest.data?.report?.raw_output ?? "no captured output")}
              </pre>
            )}

            <ul className="divide-y divide-slate-100">
              {latest.data?.results?.map((result) => (
                <li key={result.id} className="flex items-center gap-3 py-2">
                  <Chip label={result.status} tone={statusTone(result.status)} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-slate-800">{result.name}</p>
                    <p className="truncate text-[11px] text-slate-500">
                      {result.file_path}
                      {result.requirement_refs?.length ? ` · traces ${result.requirement_refs.join(", ")}` : ""}
                    </p>
                  </div>
                  <span className="shrink-0 text-[11px] text-slate-400">{formatDuration(result.duration_ms)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card title="Run history" subtitle="Every execution is stored with its parsed results">
          <ul className="divide-y divide-slate-100">
            {history.data?.map((item) => (
              <li key={item.id} className="flex items-center gap-3 py-2">
                <button
                  className="min-w-0 flex-1 text-left"
                  onClick={() => {
                    const next = item.id === selectedRun ? "" : item.id;
                    setSelectedRun(next);
                    if (!next) {
                      setHistorical(null);
                      return;
                    }
                    void api.testRun(next).then(setHistorical).catch(() => setHistorical(null));
                  }}
                >
                  <p className="text-xs font-medium text-slate-800">
                    {item.passed}/{item.total} passed · {item.triggered_by}
                  </p>
                  <p className="truncate text-[11px] text-slate-500">
                    {item.command || "pytest"} · {formatDuration(item.duration_ms)} ·{" "}
                    {formatTime(item.created_at)}
                  </p>
                </button>
                <Chip label={item.status} tone={statusTone(item.status)} />
              </li>
            ))}
            {!history.data?.length && (
              <li className="py-6 text-center text-xs text-slate-500">No runs recorded yet.</li>
            )}
          </ul>
          {historical && (
            <div className="mt-2 rounded-lg bg-slate-50 p-3 text-[11px] text-slate-600">
              <p className="font-semibold text-slate-700">
                Selected run {historical.id.slice(0, 8)} · {historical.passed}/{historical.total}{" "}
                passed ({statusLabel(historical.status)})
              </p>
              <p className="mt-1">
                {historical.command || "pytest"} · {formatDuration(historical.duration_ms)} ·{" "}
                {formatTime(historical.created_at)} · {historical.results?.length ?? 0} test result(s)
              </p>
            </div>
          )}
        </Card>

        <Card title="Sandbox" subtitle="Isolation used for generated code">
          {sandbox.data ? (
            <dl className="space-y-2 text-xs text-slate-600">
              <div>
                <dt className="font-semibold text-slate-500">Provider</dt>
                <dd>
                  {sandbox.data.provider} ({sandbox.data.isolation})
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-500">Limits</dt>
                <dd>
                  {sandbox.data.limits.timeout_seconds}s timeout · {sandbox.data.limits.memory_mb} MB ·{" "}
                  {sandbox.data.limits.cpu_seconds}s CPU
                </dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-500">Allowed commands</dt>
                <dd className="font-mono text-[11px]">{sandbox.data.allowed_commands.join(", ")}</dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-500">Working directory</dt>
                <dd className="truncate font-mono text-[11px]">{sandbox.data.working_directory}</dd>
              </div>
              <p className="rounded-lg bg-slate-50 p-2 text-[11px] text-slate-600">{sandbox.data.note}</p>
            </dl>
          ) : (
            <Loading label="Reading sandbox configuration…" />
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={confirmRun}
        title="Run the test suite in the sandbox?"
        confirmLabel="Run tests"
        body={
          <>
            DevForge will execute <code>pytest</code> inside <code>{sandbox.data?.working_directory}</code>{" "}
            with a {sandbox.data?.limits.timeout_seconds ?? 120}s timeout, {sandbox.data?.limits.memory_mb ?? 512} MB
            memory cap and no network access. The result is recorded in the test history.
          </>
        }
        onCancel={() => setConfirmRun(false)}
        onConfirm={() => void runSuite(false)}
      />
    </div>
  );
}
