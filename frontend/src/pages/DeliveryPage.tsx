import { useState } from "react";
import { useOutletContext, useParams } from "react-router-dom";
import { api, ApiError } from "../services/api";
import { useApi, formatTime, statusLabel, statusTone } from "../hooks/useApi";
import type { WorkflowOverview } from "../types/api";
import { Card, Chip, ConfirmDialog, ErrorNote, Loading, Stat } from "../components/ui";

interface Context {
  overview: WorkflowOverview;
  reloadOverview: () => Promise<void>;
}

/**
 * Delivery: connect a repository, review exactly what would be committed, then confirm the
 * commit / push. Every remote write needs an explicit human confirmation.
 */
export function DeliveryPage() {
  const { projectId = "" } = useParams();
  const { reloadOverview } = useOutletContext<Context>();
  const readiness = useApi(() => api.delivery(projectId), [projectId], { pollMs: 12000 });
  const status = useApi(() => api.repository(projectId), [projectId], { pollMs: 12000 });
  const operations = useApi(() => api.gitOperations(projectId), [projectId], { pollMs: 15000 });
  const plan = useApi(() => api.syncPlan(projectId), [projectId]);
  const commits = useApi(() => api.commits(projectId), [projectId], { pollMs: 20000 });

  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [createPr, setCreatePr] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<"commit" | "push" | "disconnect" | null>(null);

  const repository = status.data?.repository;

  async function reloadAll() {
    await Promise.all([status.reload(), plan.reload(), readiness.reload(), operations.reload()]);
    await reloadOverview();
  }

  async function run(action: () => Promise<unknown>, label: string) {
    setBusy(label);
    setError("");
    try {
      await action();
      await reloadAll();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The operation failed.");
    } finally {
      setBusy("");
      setConfirm(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Repository" value={repository ? `${repository.owner}/${repository.name}` : "not connected"} />
        <Stat label="Branch" value={status.data?.branch || repository?.working_branch || "—"} />
        <Stat label="Pending changes" value={status.data?.changes?.length ?? 0} hint={`${status.data?.untracked_count ?? 0} untracked`} />
        <Stat
          label="Delivery ready"
          value={readiness.data?.ready ? "Yes" : "Not yet"}
          hint={`${readiness.data?.checklist.filter((item) => item.done).length ?? 0}/${readiness.data?.checklist.length ?? 0} checks passed`}
        />
      </div>

      <ErrorNote message={error || status.error} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Repository" subtitle="Connect once per project; the token is encrypted at rest">
          {!repository ? (
            <div className="space-y-3">
              <div>
                <label className="label" htmlFor="url">
                  GitHub URL
                </label>
                <input
                  id="url"
                  className="input"
                  placeholder="https://github.com/you/student-task-management.git"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                />
              </div>
              <div>
                <label className="label" htmlFor="token">
                  Personal access token (optional, needs contents: write)
                </label>
                <input
                  id="token"
                  type="password"
                  className="input"
                  placeholder="ghp_…"
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                />
                <p className="mt-1 text-[11px] text-slate-500">
                  Stored encrypted (Fernet key derived from SECRET_KEY) and never returned by the API.
                </p>
              </div>
              <button
                className="btn-primary"
                disabled={!!busy || !url}
                onClick={() =>
                  void run(
                    () =>
                      api.connectRepository(projectId, { url, token, clone: false }).then(() =>
                        api.initRepository(projectId),
                      ),
                    "connect",
                  )
                }
              >
                {busy === "connect" ? "Connecting…" : "Connect repository"}
              </button>
            </div>
          ) : (
            <div className="space-y-2 text-xs text-slate-600">
              <p>
                <span className="font-semibold text-slate-500">URL:</span> {repository.url}
              </p>
              <p>
                <span className="font-semibold text-slate-500">Working branch:</span>{" "}
                <code className="font-mono">{repository.working_branch}</code> (from{" "}
                {repository.default_branch})
              </p>
              <p>
                <span className="font-semibold text-slate-500">Auth:</span>{" "}
                {repository.auth_configured ? `configured ${repository.token_hint}` : "not configured"}
              </p>
              <p>
                <span className="font-semibold text-slate-500">Last sync:</span>{" "}
                {formatTime(repository.last_synced_at)}
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                <button className="btn-secondary" disabled={!!busy} onClick={() => void run(() => api.initRepository(projectId), "init")}>
                  Initialise workspace repo
                </button>
                <button className="btn-secondary" disabled={!!busy} onClick={() => void reloadAll()}>
                  Refresh status
                </button>
                <button className="btn-danger" disabled={!!busy} onClick={() => setConfirm("disconnect")}>
                  Disconnect
                </button>
              </div>
              <p className="text-[11px] text-slate-500">
                Force-push, reset --hard and history rewriting are not implemented anywhere in
                DevForge.
              </p>
            </div>
          )}
        </Card>

        <Card
          title="Delivery checklist"
          subtitle="What still needs attention before you push"
          actions={
            readiness.data && (
              <Chip
                label={readiness.data.ready ? "READY" : "INCOMPLETE"}
                tone={statusTone(readiness.data.ready ? "COMPLETED" : "PENDING")}
              />
            )
          }
        >
          <ul className="space-y-1.5">
            {readiness.data?.checklist.map((item) => (
              <li key={item.item} className="flex items-start gap-2 text-xs">
                <span
                  className={`mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full text-[10px] font-bold ${
                    item.done ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {item.done ? "✓" : "!"}
                </span>
                <span className={item.done ? "text-slate-600" : "text-slate-800"}>
                  {item.item}
                  {item.detail && <span className="text-slate-400"> · {item.detail}</span>}
                </span>
              </li>
            ))}
          </ul>
          {readiness.data?.message && (
            <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
              {readiness.data.message}
            </p>
          )}
        </Card>
      </div>

      <Card
        title="Sync plan"
        subtitle="Exactly what would be committed — nothing runs until you confirm"
      >
        {plan.loading && !plan.data && <Loading label="Preparing the plan…" />}
        {plan.data && (
          <>
            <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
              <p>
                <span className="font-semibold text-slate-500">Branch:</span> {plan.data.branch}
              </p>
              <p>
                <span className="font-semibold text-slate-500">Base:</span> {plan.data.base_branch}
              </p>
              <p>
                <span className="font-semibold text-slate-500">Files:</span> {plan.data.files.length}
              </p>
            </div>
            <p className="mt-2 text-[11px] text-slate-500">{plan.data.summary}</p>

            <div className="mt-3 max-h-56 overflow-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-[11px]">
                <tbody className="divide-y divide-slate-100">
                  {plan.data.files.map((file) => (
                    <tr key={file.path}>
                      <td className="px-3 py-1.5 font-mono text-slate-700">{file.path}</td>
                      <td className="w-24 px-3 py-1.5 text-slate-500">{statusLabel(file.status)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-3 flex flex-wrap items-end gap-2">
              <div className="min-w-[16rem] flex-1">
                <label className="label" htmlFor="commit-message">
                  Commit message
                </label>
                <input
                  id="commit-message"
                  className="input"
                  placeholder={plan.data.commit_message}
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                />
              </div>
              <label className="flex items-center gap-2 text-[11px] text-slate-600">
                <input type="checkbox" checked={createPr} onChange={(event) => setCreatePr(event.target.checked)} />
                open a pull request on push
              </label>
              <button
                className="btn-secondary"
                disabled={!!busy || !repository}
                onClick={() => setConfirm("commit")}
              >
                Commit
              </button>
              <button
                className="btn-primary"
                disabled={!!busy || !repository}
                onClick={() => setConfirm("push")}
              >
                Commit &amp; push
              </button>
            </div>
          </>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Git operations" subtitle="Every remote write, who confirmed it and the result">
          <ul className="divide-y divide-slate-100">
            {operations.data?.map((operation) => (
              <li key={operation.id} className="flex items-center gap-3 py-2 text-xs">
                <Chip label={operation.operation} tone={statusTone(operation.status)} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-slate-700">{operation.message || "—"}</p>
                  <p className="text-[11px] text-slate-500">
                    {operation.branch} {operation.commit_sha ? `· ${operation.commit_sha.slice(0, 8)}` : ""} ·{" "}
                    {operation.confirmed_by_user ? "human confirmed" : "no confirmation recorded"}
                  </p>
                </div>
                <span className="text-[11px] text-slate-400">{formatTime(operation.created_at)}</span>
              </li>
            ))}
            {!operations.data?.length && (
              <li className="py-6 text-center text-xs text-slate-500">No git operations yet.</li>
            )}
          </ul>
        </Card>

        <Card title="Commits" subtitle="Local history of the generated workspace">
          <ul className="divide-y divide-slate-100">
            {commits.data?.map((commit) => (
              <li key={commit.sha} className="py-2 text-xs">
                <p className="text-slate-800">{commit.message}</p>
                <p className="text-[11px] text-slate-500">
                  <code className="font-mono">{commit.sha}</code> · {commit.author} ·{" "}
                  {formatTime(commit.date)}
                </p>
              </li>
            ))}
            {!commits.data?.length && (
              <li className="py-6 text-center text-xs text-slate-500">No commits yet.</li>
            )}
          </ul>
        </Card>
      </div>

      <ConfirmDialog
        open={confirm === "commit"}
        title="Commit the workspace?"
        confirmLabel="Commit"
        body={
          <>
            DevForge stages all pending changes on <code>{status.data?.branch || "the working branch"}</code>{" "}
            and creates one commit. Nothing is sent to GitHub.
          </>
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          void run(
            () =>
              api.commit(projectId, {
                message: message || plan.data?.commit_message || "chore(devforge): sync approved work",
                confirm: true,
              }),
            "commit",
          )
        }
      />

      <ConfirmDialog
        open={confirm === "push"}
        title="Push to GitHub?"
        danger
        confirmLabel="Commit and push"
        body={
          <>
            This writes to the remote repository{" "}
            <strong>{repository?.owner}/{repository?.name}</strong> on branch{" "}
            <code>{repository?.working_branch}</code>
            {createPr ? " and opens a pull request" : ""}. The operation is recorded with your user
            id and a timestamp.
          </>
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          void run(async () => {
            await api.commit(projectId, {
              message: message || plan.data?.commit_message || "chore(devforge): sync approved work",
              confirm: true,
            });
            await api.push(projectId, {
              confirm: true,
              create_pull_request: createPr,
              pr_title: `DevForge delivery: ${plan.data?.branch}`,
            });
          }, "push")
        }
      />

      <ConfirmDialog
        open={confirm === "disconnect"}
        title="Disconnect the repository?"
        danger
        confirmLabel="Disconnect"
        body="The generated workspace and its history stay on disk; only the repository link and the stored token are removed."
        onCancel={() => setConfirm(null)}
        onConfirm={() => void run(() => api.disconnectRepository(projectId), "disconnect")}
      />
    </div>
  );
}
