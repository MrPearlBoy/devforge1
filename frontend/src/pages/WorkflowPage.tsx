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

/**
 * Control room for the LangGraph run: start it, watch the current node, inspect the
 * step-by-step state history and resume a paused run.
 */
export function WorkflowPage() {
  const { projectId = "" } = useParams();
  const { overview, reloadOverview } = useOutletContext<Context>();
  const [instructions, setInstructions] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmRestart, setConfirmRestart] = useState(false);

  const run = overview.run;
  const steps = useApi(
    () => (run ? api.workflowSteps(projectId, run.id) : Promise.resolve([])),
    [run?.id ?? "", run?.total_steps ?? 0, run?.status ?? ""],
  );
  const agents = useApi(() => api.agents(), []);

  async function start(restart = false) {
    setBusy("start");
    setError("");
    try {
      await api.startWorkflow(projectId, instructions, restart);
      await reloadOverview();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The workflow could not be started.");
    } finally {
      setBusy("");
      setConfirmRestart(false);
    }
  }

  async function resume() {
    setBusy("resume");
    setError("");
    try {
      await api.resumeWorkflow(projectId);
      await reloadOverview();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The run could not be resumed.");
    } finally {
      setBusy("");
    }
  }

  const running = run?.status === "RUNNING" || run?.status === "AWAITING_APPROVAL";
  const progress = Object.entries(run?.stage_iterations || {}).filter(([, value]) => value > 0).length;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Run status" value={run ? statusLabel(run.status) : "Not started"} />
        <Stat label="Current stage" value={statusLabel(overview.current_stage)} />
        <Stat label="Steps executed" value={run?.total_steps ?? 0} />
        <Stat
          label="Revision budget"
          value={`${run?.max_stage_iterations ?? overview.iteration_budget.max_stage_iterations} per stage`}
          hint={`${progress}/6 stages have run`}
        />
      </div>

      <Card
        title="Orchestration"
        subtitle="LangGraph state machine with six agent nodes, six human gates and a bounded rework loop"
        actions={run ? <Chip label={run.status} tone={statusTone(run.status)} /> : undefined}
      >
        <div className="space-y-4">
          <ErrorNote message={error} />

          {!run && (
            <EmptyState
              title="No run yet for this project"
              hint="Starting the workflow sends the requirement to the Requirement Agent. Every stage that follows pauses for your approval."
            />
          )}

          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[18rem] flex-1">
              <label className="label" htmlFor="instructions">
                Guidance for this run (optional)
              </label>
              <input
                id="instructions"
                className="input"
                placeholder="e.g. keep the scope small, target a single-server deployment"
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
              />
            </div>
            <button className="btn-primary" disabled={!!busy || running} onClick={() => void start(false)}>
              {busy === "start" ? "Starting…" : running ? "Run in progress" : "Start workflow"}
            </button>
            <button className="btn-secondary" disabled={!!busy} onClick={() => setConfirmRestart(true)}>
              Restart from the Requirement Agent
            </button>
            {overview.can_resume && (
              <button className="btn-secondary" disabled={!!busy} onClick={() => void resume()}>
                {busy === "resume" ? "Resuming…" : "Continue paused run"}
              </button>
            )}
          </div>

          {run?.awaiting_approval && overview.pending_approval && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
              Waiting for a human decision on the{" "}
              <strong>{statusLabel(overview.pending_approval.gate)}</strong> gate.{" "}
              <Link className="font-semibold underline" to={`/projects/${projectId}/approvals`}>
                Open approvals
              </Link>
            </div>
          )}

          {run?.last_error && (
            <pre className="overflow-auto rounded-lg bg-rose-50 p-3 text-[11px] text-rose-800 ring-1 ring-rose-200">
              {run.last_error}
            </pre>
          )}

          <div>
            <p className="label">Stage iterations used</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(run?.stage_iterations || {}).map(([stage, count]) => (
                <span
                  key={stage}
                  className={`chip ${
                    count === 0 ? "bg-slate-100 text-slate-500 ring-1 ring-slate-200" : "bg-forge-50 text-forge-700 ring-1 ring-forge-200"
                  }`}
                >
                  {statusLabel(stage)}: {count}
                </span>
              ))}
            </div>
          </div>

          {run && (
            <dl className="grid gap-x-6 gap-y-1 text-xs text-slate-500 sm:grid-cols-3">
              <div>
                <dt className="font-semibold text-slate-400">Engine</dt>
                <dd>{run.engine} · thread {run.thread_id.slice(0, 26)}…</dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-400">Started</dt>
                <dd>{formatTime(run.started_at)}</dd>
              </div>
              <div>
                <dt className="font-semibold text-slate-400">Finished</dt>
                <dd>{formatTime(run.finished_at)}</dd>
              </div>
            </dl>
          )}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card title="Step history" subtitle="Every node the graph executed, in order">
          {steps.loading && <Loading label="Loading steps…" />}
          {!steps.loading && !steps.data?.length && (
            <p className="py-6 text-center text-xs text-slate-500">No steps recorded yet.</p>
          )}
          <ol className="space-y-2">
            {steps.data?.map((step) => (
              <li key={step.id} className="flex gap-3 rounded-lg border border-slate-100 px-3 py-2">
                <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
                  {step.step_index}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-slate-800">
                    {step.node} <span className="font-normal text-slate-500">· {statusLabel(step.stage)}</span>
                  </p>
                  <p className="truncate text-[11px] text-slate-500">{step.summary || "—"}</p>
                </div>
                <div className="text-right">
                  <Chip label={step.status} tone={statusTone(step.status)} />
                  <p className="mt-1 text-[10px] text-slate-400">{formatTime(step.created_at)}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Pipeline" subtitle="What will run next">
          <ol className="space-y-2 text-xs text-slate-600">
            {(agents.data || []).map((agent, index) => (
              <li key={agent.key} className="flex gap-3 rounded-lg bg-slate-50 px-3 py-2">
                <span className="font-mono text-[11px] text-slate-400">{index + 1}</span>
                <div>
                  <p className="font-semibold text-slate-800">{agent.name}</p>
                  <p className="text-[11px] text-slate-500">{agent.role}</p>
                  <p className="mt-1 text-[11px] text-slate-500">{agent.description}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmRestart}
        title="Restart the workflow?"
        danger
        confirmLabel="Restart"
        body="A new run starts from the Requirement Agent. Existing artefacts stay in the history, but every stage will pause for approval again."
        onCancel={() => setConfirmRestart(false)}
        onConfirm={() => void start(true)}
      />
    </div>
  );
}
