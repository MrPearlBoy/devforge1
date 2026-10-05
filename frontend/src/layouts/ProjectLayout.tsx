import { Link, NavLink, Outlet, useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi, statusLabel, statusTone } from "../hooks/useApi";
import { Chip, ErrorNote, Loading, ProgressBar } from "../components/ui";

const TABS = [
  { to: "overview", label: "Overview" },
  { to: "workflow", label: "Workflow" },
  { to: "approvals", label: "Approvals" },
  { to: "agents", label: "Agents" },
  { to: "chat", label: "Chat" },
  { to: "code", label: "Code" },
  { to: "tests", label: "Tests" },
  { to: "security", label: "Security" },
  { to: "trace", label: "Traceability" },
  { to: "delivery", label: "Delivery" },
  { to: "activity", label: "Activity" },
];

/** Project shell: identity, live workflow status and the tab navigation. */
export function ProjectLayout() {
  const { projectId = "" } = useParams();
  const overview = useApi(() => api.workflowOverview(projectId), [projectId], { pollMs: 3000 });

  if (overview.loading && !overview.data) return <Loading label="Loading project…" />;
  if (!overview.data) return <ErrorNote message={overview.error || "Project not found."} />;

  const { run, pending_approval: pending } = overview.data;
  const project = overview.data;

  return (
    <div className="space-y-4">
      <header className="card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Link to="/projects" className="text-[11px] font-medium text-forge-700">
                ← Projects
              </Link>
            </div>
            <h1 className="mt-1 truncate text-lg font-semibold text-slate-900">
              <ProjectName projectId={projectId} />
            </h1>
            <p className="text-xs text-slate-500">
              stage {statusLabel(project.current_stage)} · run {run ? `#${run.run_number}` : "not started"}
              {run ? ` · ${run.total_steps} step(s)` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Chip label={project.project_status} tone={statusTone(project.project_status)} />
            {pending && (
              <Link
                to={`/projects/${projectId}/approvals`}
                className="chip bg-amber-100 text-amber-800 ring-1 ring-amber-300"
              >
                {statusLabel(pending.stage)} awaiting approval
              </Link>
            )}
          </div>
        </div>
        <div className="mt-3">
          <ProgressBar value={project.stages.filter((s) => s.status === "COMPLETED").length * 100 / 7} />
        </div>
      </header>

      <nav className="flex flex-wrap gap-1 border-b border-slate-200 pb-1">
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            className={({ isActive }) =>
              `rounded-t-md px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "border-b-2 border-forge-600 text-forge-700"
                  : "text-slate-500 hover:text-slate-800"
              }`
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>

      <Outlet context={{ overview: overview.data, reloadOverview: overview.reload }} />
    </div>
  );
}

function ProjectName({ projectId }: { projectId: string }) {
  const project = useApi(() => api.getProject(projectId), [projectId]);
  return <>{project.data?.name ?? "Project"}</>;
}
