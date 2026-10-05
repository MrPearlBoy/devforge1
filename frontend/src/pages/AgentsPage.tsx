import { useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi, formatDuration, formatTime, relativeTime, statusLabel, statusTone } from "../hooks/useApi";
import { Card, Chip, ErrorNote, Loading, Stat } from "../components/ui";

/** Agent catalogue, live status and the full execution log. */
export function AgentsPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const specs = useApi(() => api.agents(), []);
  const statuses = useApi(() => api.agentStatus(projectId), [projectId], { pollMs: 6000 });
  const executions = useApi(() => api.executions(projectId, 60), [projectId], { pollMs: 8000 });

  const running = statuses.data?.filter((item) => item.status === "RUNNING").length ?? 0;
  const succeeded = statuses.data?.filter((item) => item.status === "SUCCEEDED").length ?? 0;
  const tokens = executions.data?.reduce((total, item) => total + item.duration_ms, 0) ?? 0;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Agents" value={specs.data?.length ?? 6} hint="one per SDLC stage" />
        <Stat label="Currently running" value={running} hint={`${succeeded} completed in the last pass`} />
        <Stat label="Executions recorded" value={executions.data?.length ?? 0} />
        <Stat label="Agent time" value={formatDuration(tokens)} hint="sum of execution durations" />
      </div>

      <ErrorNote message={statuses.error || executions.error} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {specs.data?.map((spec) => {
          const status = statuses.data?.find((item) => item.agent_key === spec.key);
          return (
            <Card
              key={spec.key}
              title={spec.name}
              subtitle={spec.role}
              actions={<Chip label={status?.status || "IDLE"} tone={statusTone(status?.status || "IDLE")} />}
            >
              <p className="text-xs text-slate-600">{spec.description}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {spec.capabilities.slice(0, 4).map((capability) => (
                  <span key={capability} className="chip bg-slate-100 text-slate-600">
                    {capability}
                  </span>
                ))}
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
                <div>
                  <dt className="font-semibold text-slate-400">Last run</dt>
                  <dd>{status?.started_at ? relativeTime(status.started_at) : "never"}</dd>
                </div>
                <div>
                  <dt className="font-semibold text-slate-400">Duration</dt>
                  <dd>{formatDuration(status?.duration_ms || 0)}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="font-semibold text-slate-400">Output</dt>
                  <dd className="line-clamp-2">{status?.result || status?.error || "—"}</dd>
                </div>
                <div className="col-span-2">
                  <dt className="font-semibold text-slate-400">Artifacts</dt>
                  <dd>{spec.output_artifact_types.join(", ")}</dd>
                </div>
              </dl>
              <button
                className="btn-secondary mt-3 w-full"
                onClick={() => navigate(`/projects/${projectId}/chat?agent=${spec.key}`)}
              >
                Chat with this agent
              </button>
            </Card>
          );
        })}
      </div>

      <Card title="Execution log" subtitle="Telemetry for every agent invocation (workflow, chat, manual)">
        {executions.loading && !executions.data && <Loading label="Loading executions…" />}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[48rem] text-left text-xs">
            <thead className="text-[11px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="py-2">Agent</th>
                <th className="py-2">Stage</th>
                <th className="py-2">Trigger</th>
                <th className="py-2">Mode</th>
                <th className="py-2">Duration</th>
                <th className="py-2">Started</th>
                <th className="py-2">Status</th>
                <th className="py-2">Output</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {executions.data?.map((execution) => (
                <tr key={execution.id} className="align-top">
                  <td className="py-2 font-medium text-slate-800">{execution.agent_key}</td>
                  <td className="py-2 text-slate-600">{statusLabel(execution.stage)}</td>
                  <td className="py-2 text-slate-600">{statusLabel(execution.trigger)}</td>
                  <td className="py-2 text-slate-600">{execution.mode}</td>
                  <td className="py-2 text-slate-600">{formatDuration(execution.duration_ms)}</td>
                  <td className="py-2 text-slate-500">{formatTime(execution.created_at)}</td>
                  <td className="py-2">
                    <Chip label={execution.status} tone={statusTone(execution.status)} />
                  </td>
                  <td className="max-w-[16rem] py-2 text-slate-500">
                    <span className="line-clamp-2">{execution.output_summary || execution.error}</span>
                  </td>
                </tr>
              ))}
              {!executions.data?.length && (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-slate-500">
                    No executions recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
