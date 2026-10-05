import type { ActivityEntry } from "../types/api";
import { relativeTime } from "../hooks/useApi";

const STAGE_COLORS: Record<string, string> = {
  REQUIREMENTS: "bg-sky-400",
  ARCHITECTURE: "bg-violet-400",
  DEVELOPMENT: "bg-forge-500",
  TESTING: "bg-emerald-400",
  SECURITY: "bg-rose-400",
  DOCUMENTATION: "bg-amber-400",
  DELIVERY: "bg-slate-400",
};

export function ActivityFeed({ entries, limit }: { entries: ActivityEntry[]; limit?: number }) {
  const rows = limit ? entries.slice(0, limit) : entries;
  if (!rows.length) {
    return <p className="py-6 text-center text-xs text-slate-500">No activity recorded yet.</p>;
  }
  return (
    <ol className="divide-y divide-slate-100">
      {rows.map((entry) => (
        <li key={entry.id} className="flex gap-3 py-2.5">
          <span
            className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
              STAGE_COLORS[entry.stage] || "bg-slate-300"
            }`}
          />
          <div className="min-w-0 flex-1">
            <p className="text-xs text-slate-700">
              <span className="font-semibold">{entry.actor_label || entry.actor_type}</span>{" "}
              {entry.label || entry.action}
            </p>
            {entry.summary && <p className="truncate text-[11px] text-slate-500">{entry.summary}</p>}
          </div>
          <span className="shrink-0 text-[11px] text-slate-400">{relativeTime(entry.created_at)}</span>
        </li>
      ))}
    </ol>
  );
}
