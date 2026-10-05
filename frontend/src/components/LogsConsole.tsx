import { useEffect, useRef, useState } from "react";
import { Terminal } from "lucide-react";
import type { StreamEvent } from "../lib/api";

const TYPE_STYLE: Record<string, string> = {
  system: "text-slate-400",
  stage: "text-indigo-300",
  agent: "text-sky-300",
  artifact: "text-emerald-300",
  file: "text-emerald-300/80",
  state: "text-slate-500",
  approval_requested: "text-amber-300",
  approval_recorded: "text-amber-200",
  tests: "text-fuchsia-300",
  security: "text-rose-300",
  git: "text-cyan-300",
  auto: "text-violet-300",
  warn: "text-amber-400",
  error: "text-rose-400",
  done: "text-emerald-300",
};

const FILTERS = [
  { key: "all", label: "all" },
  { key: "agent", label: "agents" },
  { key: "tests", label: "tests" },
  { key: "security", label: "security" },
  { key: "approval", label: "approvals" },
  { key: "error", label: "errors" },
] as const;

type Filter = (typeof FILTERS)[number]["key"];

function matches(e: StreamEvent, f: Filter): boolean {
  switch (f) {
    case "agent":
      return ["agent", "stage", "file", "artifact"].includes(e.type);
    case "tests":
      return ["tests"].includes(e.type);
    case "security":
      return ["security"].includes(e.type);
    case "approval":
      return ["approval_requested", "approval_recorded"].includes(e.type);
    case "error":
      return ["error", "warn"].includes(e.type);
    default:
      return true;
  }
}

export default function LogsConsole({ events }: { events: StreamEvent[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [autoScroll, setAutoScroll] = useState(true);
  const boxRef = useRef<HTMLDivElement>(null);

  const shown = events.filter((e) => matches(e, filter));

  useEffect(() => {
    if (autoScroll && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight;
    }
  }, [shown.length, autoScroll, filter]);

  const onScroll = () => {
    const el = boxRef.current;
    if (!el) return;
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-ink-700/60 bg-ink-950">
      <div className="flex items-center gap-1 border-b border-ink-700/60 px-2 py-1.5">
        <Terminal size={13} className="mx-1 text-slate-500" />
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors ${
              filter === f.key ? "bg-ink-700 text-slate-100" : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto pr-2 text-[10px] text-slate-600">{shown.length} events</span>
      </div>
      <div ref={boxRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto p-2 font-mono text-[11px] leading-[1.7]">
        {shown.length === 0 && <p className="p-2 text-slate-600">Waiting for workflow events…</p>}
        {shown.map((e, i) => (
          <div key={i} className="flex gap-2 whitespace-pre-wrap break-words px-1 hover:bg-ink-900/60">
            <span className="shrink-0 select-none text-slate-600">{ts(e.ts)}</span>
            <span className={`w-[118px] shrink-0 select-none truncate text-right ${TYPE_STYLE[e.type] ?? "text-slate-400"}`}>
              {e.type}
            </span>
            <span className="text-slate-300">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ts(raw?: string | null): string {
  if (!raw) return "";
  const d = new Date(raw);
  if (isNaN(d.getTime())) return "";
  return d.toTimeString().slice(0, 8);
}
