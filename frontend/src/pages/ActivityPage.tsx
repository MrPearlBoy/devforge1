import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi, formatTime, relativeTime, statusLabel } from "../hooks/useApi";
import { Card, ErrorNote, Loading, Stat } from "../components/ui";
import { ActivityFeed } from "../components/ActivityFeed";

/** Full audit log plus the raw evidence table (useful for the written report). */
export function ActivityPage() {
  const { projectId = "" } = useParams();
  const activity = useApi(() => api.activity(projectId, 200), [projectId], { pollMs: 10000 });
  const summary = useApi(() => api.activitySummary(projectId), [projectId], { pollMs: 20000 });
  const [filter, setFilter] = useState("");
  const [showRaw, setShowRaw] = useState(false);

  const entries = (activity.data || []).map((entry) => ({
    id: entry.id,
    action: entry.action,
    label: (summary.data?.labels?.[entry.action] || entry.action.replace(/\./g, " "))
      .replace(/^./, (char) => char.toUpperCase()),
    actor_type: entry.actor_type,
    actor_label: entry.actor_label,
    stage: entry.stage,
    summary: entry.summary,
    detail: entry.detail,
    entity_type: entry.entity_type,
    entity_id: entry.entity_id,
    created_at: entry.created_at,
  }));

  const filtered = filter ? entries.filter((entry) => entry.action.startsWith(filter)) : entries;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Audit entries" value={summary.data?.total ?? entries.length} />
        <Stat label="Distinct actions" value={Object.keys(summary.data?.by_action || {}).length} />
        <Stat label="Approvals" value={summary.data?.by_action["approval.approved"] ?? 0} hint="human decisions recorded" />
        <Stat label="Code applications" value={summary.data?.by_action["code.changes_applied"] ?? 0} />
      </div>

      <ErrorNote message={activity.error} />

      <Card
        title="Activity"
        subtitle="Immutable record of every agent run, decision, execution and git operation"
        actions={
          <div className="flex items-center gap-2">
            <select className="input w-44 py-1.5 text-xs" value={filter} onChange={(event) => setFilter(event.target.value)}>
              <option value="">All actions</option>
              {Object.keys(summary.data?.by_action || {}).sort().map((action) => (
                <option key={action} value={action}>
                  {action}
                </option>
              ))}
            </select>
            <button className="btn-secondary" onClick={() => setShowRaw((value) => !value)}>
              {showRaw ? "Hide table" : "Show table"}
            </button>
          </div>
        }
      >
        {activity.loading && !activity.data && <Loading label="Loading the audit log…" />}
        <ActivityFeed entries={filtered} />
      </Card>

      {showRaw && (
        <Card title="Raw evidence" subtitle="Suitable for copy/paste into the project report">
          <div className="max-h-[28rem] overflow-auto">
            <table className="w-full min-w-[52rem] text-left text-[11px]">
              <thead className="sticky top-0 bg-white text-[10px] uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="py-2">When</th>
                  <th className="py-2">Actor</th>
                  <th className="py-2">Action</th>
                  <th className="py-2">Stage</th>
                  <th className="py-2">Entity</th>
                  <th className="py-2">Summary</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td className="py-1.5 text-slate-500" title={formatTime(entry.created_at)}>
                      {relativeTime(entry.created_at)}
                    </td>
                    <td className="py-1.5 text-slate-700">
                      {entry.actor_label}
                      <span className="ml-1 text-slate-400">({entry.actor_type})</span>
                    </td>
                    <td className="py-1.5 font-mono text-slate-700">{entry.action}</td>
                    <td className="py-1.5 text-slate-500">{statusLabel(entry.stage) || "—"}</td>
                    <td className="py-1.5 text-slate-500">
                      {entry.entity_type}
                      {entry.entity_id ? ` ${entry.entity_id.slice(0, 8)}` : ""}
                    </td>
                    <td className="py-1.5 text-slate-600">{entry.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
