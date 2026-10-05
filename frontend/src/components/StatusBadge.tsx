import { CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

const MAP: Record<string, { label: string; cls: string; icon: typeof Clock; spin?: boolean }> = {
  idle: { label: "Idle", cls: "bg-slate-500/15 text-slate-400", icon: Clock },
  running: { label: "Running", cls: "bg-indigo-500/15 text-indigo-300", icon: Loader2, spin: true },
  waiting_approval: { label: "Awaiting approval", cls: "bg-amber-400/15 text-amber-300", icon: Clock },
  completed: { label: "Completed", cls: "bg-emerald-500/15 text-emerald-300", icon: CheckCircle2 },
  failed: { label: "Failed", cls: "bg-rose-500/15 text-rose-300", icon: XCircle },
  interrupted: { label: "Interrupted", cls: "bg-amber-400/15 text-amber-300", icon: Clock },
};

export default function StatusBadge({ status }: { status: string }) {
  const m = MAP[status] ?? MAP.idle;
  const Icon = m.icon;
  return (
    <span className={`chip ${m.cls}`}>
      <Icon size={11} className={m.spin ? "animate-spin" : ""} />
      {m.label}
    </span>
  );
}
