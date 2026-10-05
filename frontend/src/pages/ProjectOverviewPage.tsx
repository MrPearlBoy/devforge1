import { Link, useOutletContext, useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi, formatDuration, statusLabel, statusTone, relativeTime } from "../hooks/useApi";
import type { Dashboard, WorkflowOverview } from "../types/api";
import { ActivityFeed } from "../components/ActivityFeed";
import { StageStepper } from "../components/StageStepper";
import { Card, Chip, ErrorNote, Loading, ProgressBar, Stat } from "../components/ui";

interface Context {
  overview: WorkflowOverview;
  reloadOverview: () => Promise<void>;
}

export function ProjectOverviewPage() {
  const { projectId = "" } = useParams();
  const { overview } = useOutletContext<Context>();
  const dashboard = useApi(() => api.dashboard(projectId), [projectId], { pollMs: 8000 });

  if (dashboard.loading && !dashboard.data) return <Loading label="Loading dashboard…" />;
  if (!dashboard.data) return <ErrorNote message={dashboard.error || "Dashboard unavailable."} />;

  const data: Dashboard = dashboard.data;
  const tests = data.latest_test_run;
  const security = data.security_summary as Record<string, number>;
  const completed = data.stages.filter((stage) => stage.status === "COMPLETED").length;

  return (
    <div className="space-y-4">
      <StageStepper stages={overview.stages} activeStage={overview.current_stage} />

      <ErrorNote message={dashboard.error} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Progress"
          value={`${Math.round((completed / Math.max(1, data.stages.length)) * 100)}%`}
          hint={`${completed}/${data.stages.length} stages complete`}
        />
        <Stat
          label="Latest tests"
          value={tests ? `${tests.passed}/${tests.total}` : "—"}
          hint={tests ? `${statusLabel(tests.status)} in ${formatDuration(tests.duration_ms)}` : "no run yet"}
        />
        <Stat
          label="Open findings"
          value={security?.open_total ?? 0}
          hint={security?.files_scanned ? `${security.files_scanned} files scanned` : "not scanned yet"}
        />
        <Stat
          label="Artefacts"
          value={data.artifacts.length}
          hint={`${data.approvals.filter((a) => a.status === "PENDING").length} approval(s) pending`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card
          title="Agents"
          subtitle="Latest execution per specialist, in pipeline order"
          actions={
            <Link className="text-xs font-medium text-forge-700" to={`/projects/${projectId}/agents`}>
              View runs
            </Link>
          }
        >
          <ul className="divide-y divide-slate-100">
            {data.agent_activity.map((agent) => (
              <li key={agent.agent_key} className="flex items-center gap-3 py-2.5">
                <span className="grid h-8 w-8 place-items-center rounded-lg bg-slate-100 text-[11px] font-semibold text-slate-600">
                  {agent.name.replace(" Agent", "").slice(0, 2).toUpperCase()}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-800">{agent.name}</p>
                  <p className="truncate text-[11px] text-slate-500">
                    {agent.summary || agent.error || agent.role}
                  </p>
                </div>
                <div className="text-right">
                  <Chip label={agent.status} tone={statusTone(agent.status)} />
                  <p className="mt-1 text-[10px] text-slate-400">{formatDuration(agent.duration_ms)}</p>
                </div>
              </li>
            ))}
            {!data.agent_activity.length && (
              <li className="py-6 text-center text-xs text-slate-500">No agent runs yet.</li>
            )}
          </ul>
        </Card>

        <Card title="Recent activity" subtitle="Immutable audit trail">
          <ActivityFeed entries={data.recent_activity} limit={10} />
          <Link
            className="mt-2 inline-block text-xs font-medium text-forge-700"
            to={`/projects/${projectId}/activity`}
          >
            Open the full audit log
          </Link>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Artefacts" subtitle="Every AI result is stored, versioned and traceable">
          <ul className="divide-y divide-slate-100">
            {data.artifacts.slice(0, 8).map((artifact) => (
              <li key={artifact.id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm text-slate-800">{artifact.title}</p>
                  <p className="truncate text-[11px] text-slate-500">
                    {artifact.type} · v{artifact.version} · {artifact.path || "stored in the database"}
                  </p>
                </div>
                <Chip label={artifact.status} tone={statusTone(artifact.status)} />
              </li>
            ))}
            {!data.artifacts.length && (
              <li className="py-6 text-center text-xs text-slate-500">No artefacts yet.</li>
            )}
          </ul>
        </Card>

        <Card title="Project memory" subtitle="What the agents see when they are invoked">
          <div className="space-y-3 text-xs text-slate-600">
            <div>
              <p className="font-semibold text-slate-500">AI mode</p>
              <p>
                {data.ai_config.mode} · {data.ai_config.provider} · {data.ai_config.model}
                {data.ai_config.mock_mode ? " (deterministic mock outputs)" : " (live provider)"}
              </p>
            </div>
            <div>
              <p className="font-semibold text-slate-500">Original requirement</p>
              <p className="line-clamp-4 whitespace-pre-wrap">{data.project.requirement_input}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="font-semibold text-slate-500">Iteration budget</p>
                <p>
                  {data.active_run
                    ? `${data.active_run.total_steps} steps used · max ${data.active_run.max_stage_iterations} revisions per stage`
                    : `max ${data.ai_config.max_stage_iterations} revisions per stage`}
                </p>
              </div>
              <div>
                <p className="font-semibold text-slate-500">Sandbox</p>
                <p>{data.ai_config.execution_provider} · execution enabled</p>
              </div>
            </div>
            {data.active_run && (
              <div>
                <p className="font-semibold text-slate-500">Current run</p>
                <p>
                  #{data.active_run.run_number} · {statusLabel(data.active_run.status)} · node{" "}
                  {data.active_run.current_node || "—"}
                </p>
                <div className="mt-2">
                  <ProgressBar
                    value={
                      (Object.values(data.active_run.stage_iterations || {}).filter((v) => v > 0).length /
                        6) *
                      100
                    }
                  />
                </div>
              </div>
            )}
            <div>
              <p className="font-semibold text-slate-500">Last updated</p>
              <p>{relativeTime(data.project.updated_at)}</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
