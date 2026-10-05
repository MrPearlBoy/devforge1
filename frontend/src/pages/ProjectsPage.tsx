import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { useApi, statusLabel, statusTone, relativeTime } from "../hooks/useApi";
import { Card, Chip, EmptyState, ErrorNote, Loading, ProgressBar } from "../components/ui";
import { useAuth } from "../store/auth";

const SAMPLE = {
  name: "Student Task Management System",
  description: "Coursework tracker: students manage tasks, administrators manage accounts.",
  requirement_input:
    "Build a web application where students can create tasks, update tasks, delete tasks and mark tasks as completed. Students should also be able to view their pending tasks and filter them by deadline. An administrator must be able to view all users and remove inactive accounts.",
  tags: ["demo", "education"],
};

export function ProjectsPage() {
  const { user } = useAuth();
  const projects = useApi(() => api.listProjects(), []);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", requirement_input: "", tags: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createProject({
        name: form.name,
        description: form.description,
        requirement_input: form.requirement_input,
        tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      });
      setForm({ name: "", description: "", requirement_input: "", tags: "" });
      setShowForm(false);
      await projects.reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The project could not be created.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Projects</h1>
          <p className="text-sm text-slate-500">
            Every project gets its own workspace, agent runs, artefacts and approval history.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            className="btn-secondary"
            onClick={() => {
              setForm({ ...SAMPLE, tags: SAMPLE.tags.join(", ") });
              setShowForm(true);
            }}
          >
            Fill the demo scenario
          </button>
          <button className="btn-primary" onClick={() => setShowForm((value) => !value)}>
            {showForm ? "Close" : "New project"}
          </button>
        </div>
      </header>

      {showForm && (
        <Card title="Describe what should be built" subtitle="This becomes the Requirement Agent's input.">
          <form className="grid gap-3 md:grid-cols-2" onSubmit={create}>
            <div className="md:col-span-2">
              <label className="label" htmlFor="name">
                Project name
              </label>
              <input
                id="name"
                required
                minLength={2}
                className="input"
                value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })}
                placeholder="Student Task Management System"
              />
            </div>
            <div className="md:col-span-2">
              <label className="label" htmlFor="requirement">
                Requirement (plain language)
              </label>
              <textarea
                id="requirement"
                required
                minLength={20}
                rows={5}
                className="input"
                value={form.requirement_input}
                onChange={(event) => setForm({ ...form, requirement_input: event.target.value })}
                placeholder="Students create, update, delete and complete tasks; filter by deadline; an admin manages accounts."
              />
            </div>
            <div>
              <label className="label" htmlFor="description">
                Short description
              </label>
              <input
                id="description"
                className="input"
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            </div>
            <div>
              <label className="label" htmlFor="tags">
                Tags (comma separated)
              </label>
              <input
                id="tags"
                className="input"
                value={form.tags}
                onChange={(event) => setForm({ ...form, tags: event.target.value })}
              />
            </div>
            <div className="md:col-span-2">
              <ErrorNote message={error} />
            </div>
            <div className="md:col-span-2 flex justify-end gap-2">
              <button type="button" className="btn-secondary" onClick={() => setShowForm(false)}>
                Cancel
              </button>
              <button type="submit" className="btn-primary" disabled={busy}>
                {busy ? "Creating…" : "Create project"}
              </button>
            </div>
          </form>
        </Card>
      )}

      {projects.loading && <Loading label="Loading projects…" />}
      <ErrorNote message={projects.error} />
      {!projects.loading && projects.data?.length === 0 && (
        <EmptyState
          title="No projects yet"
          hint="Create a project with the requirement you want the agents to build. You can seed a finished demo with `python scripts/seed_demo.py --run-workflow`."
          action={
            <button className="btn-primary mt-2" onClick={() => setShowForm(true)}>
              Start a project
            </button>
          }
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {projects.data?.map((project) => (
          <Link
            key={project.id}
            to={`/projects/${project.id}`}
            className="card block p-4 transition-shadow hover:shadow-md"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="truncate text-sm font-semibold text-slate-900">{project.name}</h2>
                <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">
                  {project.description || project.requirement_input.slice(0, 140)}
                </p>
              </div>
              <Chip label={project.workflow_status} tone={statusTone(project.workflow_status)} />
            </div>
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
                <span>{statusLabel(project.current_stage)} stage</span>
                <span>{project.progress_percent}%</span>
              </div>
              <ProgressBar value={project.progress_percent} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
              {project.pending_approvals > 0 && (
                <span className="chip bg-amber-50 text-amber-700 ring-1 ring-amber-200">
                  {project.pending_approvals} awaiting approval
                </span>
              )}
              {project.open_findings > 0 && (
                <span className="chip bg-rose-50 text-rose-700 ring-1 ring-rose-200">
                  {project.open_findings} open findings
                </span>
              )}
              {project.last_test_status && (
                <span className={`chip ${statusTone(project.last_test_status)}`}>
                  tests {statusLabel(project.last_test_status)}
                </span>
              )}
              {project.github_connected && (
                <span className="chip bg-slate-100 text-slate-600 ring-1 ring-slate-200">
                  GitHub connected
                </span>
              )}
              <span className="ml-auto">updated {relativeTime(project.updated_at)}</span>
            </div>
          </Link>
        ))}
      </div>

      {user && (
        <p className="text-[11px] text-slate-400">
          Signed in as {user.email} ({user.role}). Projects are private to their owner unless
          another user is added as a member.
        </p>
      )}
    </div>
  );
}
