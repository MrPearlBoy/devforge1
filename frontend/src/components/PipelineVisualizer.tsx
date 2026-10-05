import {
  BookOpen,
  Check,
  ClipboardList,
  Code2,
  FlaskConical,
  Network,
  Rocket,
  ShieldCheck,
  X,
  type LucideIcon,
} from "lucide-react";

export const STAGE_ORDER = [
  "requirement",
  "architecture",
  "coding",
  "testing",
  "security",
  "documentation",
  "delivery",
] as const;

export type StageKey = (typeof STAGE_ORDER)[number];

const STAGE_META: Record<StageKey, { label: string; icon: LucideIcon; gate?: string }> = {
  requirement: { label: "Requirement", icon: ClipboardList, gate: "requirement" },
  architecture: { label: "Architecture", icon: Network, gate: "architecture" },
  coding: { label: "Coding", icon: Code2, gate: "code" },
  testing: { label: "Testing", icon: FlaskConical },
  security: { label: "Security", icon: ShieldCheck },
  documentation: { label: "Documentation", icon: BookOpen, gate: "docs" },
  delivery: { label: "Delivery", icon: Rocket },
};

interface Props {
  stage: string;
  status: string;
  awaitingGate: string | null;
  iterations?: Record<string, number>;
}

type NodeState = "pending" | "active" | "waiting" | "done" | "failed";

export default function PipelineVisualizer({ stage, status, awaitingGate, iterations = {} }: Props) {
  const failed = stage === "failed" || status === "failed";
  const completed = stage === "completed";
  const currentIndex = STAGE_ORDER.indexOf(stage as StageKey);

  const stateOf = (key: StageKey, idx: number): NodeState => {
    if (failed) {
      if (idx < currentIndex) return "done";
      if (idx === currentIndex) return "failed";
      return "pending";
    }
    if (completed) return "done";
    if (stage === "created") return "pending";
    if (idx < currentIndex) return "done";
    if (idx === currentIndex) return status === "waiting_approval" ? "waiting" : "active";
    return "pending";
  };

  const ringFor = (s: NodeState) =>
    s === "done"
      ? "border-emerald-500/70 bg-emerald-500/10 text-emerald-300"
      : s === "failed"
      ? "border-rose-500/80 bg-rose-500/10 text-rose-300"
      : s === "waiting"
      ? "border-amber-400/90 bg-amber-400/10 text-amber-300"
      : s === "active"
      ? "border-indigo-400 bg-indigo-500/20 text-indigo-200"
      : "border-ink-700 bg-ink-850 text-slate-500";

  return (
    <div className="panel px-4 py-4 sm:px-6">
      <div className="flex items-start overflow-x-auto pb-1">
        {STAGE_ORDER.map((key, idx) => {
          const meta = STAGE_META[key];
          const s = stateOf(key, idx);
          const Icon = meta.icon;
          const iter = iterations[key] ?? iterations[key === "coding" ? "code" : key] ?? 0;
          const isWaitingHere = s === "waiting" && awaitingGate === meta.gate;
          return (
            <div key={key} className="flex items-start">
              <div className="flex w-[86px] flex-col items-center gap-1.5 sm:w-[96px]">
                <div
                  className={`relative flex h-11 w-11 items-center justify-center rounded-full border-2 transition-all ${ringFor(
                    s
                  )} ${s === "active" ? "scale-110 shadow-lg shadow-indigo-500/30" : ""} ${
                    s === "waiting" ? "animate-pulse-slow shadow-lg shadow-amber-500/20" : ""
                  }`}
                >
                  <Icon size={19} />
                  {s === "done" && (
                    <span className="absolute -right-1 -top-1 flex h-4.5 w-4.5 items-center justify-center rounded-full bg-emerald-500 p-0.5">
                      <Check size={11} className="text-ink-950" strokeWidth={3.5} />
                    </span>
                  )}
                  {s === "failed" && (
                    <span className="absolute -right-1 -top-1 flex h-4.5 w-4.5 items-center justify-center rounded-full bg-rose-500 p-0.5">
                      <X size={11} className="text-white" strokeWidth={3.5} />
                    </span>
                  )}
                </div>
                <div className="text-center">
                  <div className={`text-[11px] font-medium leading-tight ${s === "pending" ? "text-slate-500" : "text-slate-200"}`}>
                    {meta.label}
                  </div>
                  {iter > 0 && (
                    <div className="text-[10px] text-amber-400/90">×{iter + 1} iter</div>
                  )}
                  {isWaitingHere && (
                    <div className="mt-0.5 inline-block rounded-full bg-amber-400/15 px-1.5 text-[9.5px] font-semibold uppercase tracking-wide text-amber-300">
                      approval
                    </div>
                  )}
                </div>
              </div>
              {idx < STAGE_ORDER.length - 1 && (
                <div
                  className={`mt-[21px] h-0.5 w-4 shrink-0 rounded sm:w-7 ${
                    stateOf(STAGE_ORDER[idx + 1], idx + 1) === "pending" || (stateOf(key, idx) === "pending")
                      ? "bg-ink-700"
                      : "bg-indigo-400/70"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
