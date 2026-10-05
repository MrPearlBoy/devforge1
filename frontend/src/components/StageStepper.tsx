import type { StageProgress } from "../types/api";
import { statusLabel, statusTone } from "../hooks/useApi";

/**
 * The SDLC pipeline as a horizontal stepper. Each step shows the stage status, whether an
 * approval is waiting and which artefact represents it.
 */
export function StageStepper({
  stages,
  onSelect,
  activeStage,
}: {
  stages: StageProgress[];
  onSelect?: (stage: StageProgress) => void;
  activeStage?: string;
}) {
  return (
    <ol className="flex flex-wrap items-stretch gap-2">
      {stages.map((stage, index) => {
        const tone = statusTone(stage.status);
        const active = activeStage === stage.stage;
        return (
          <li key={stage.stage} className="flex-1 min-w-[9.5rem]">
            <button
              onClick={() => onSelect?.(stage)}
              className={`w-full rounded-xl border px-3 py-2.5 text-left transition-colors ${
                active ? "border-forge-400 bg-forge-50/70" : "border-slate-200 bg-white hover:border-forge-300"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                  Step {index + 1}
                </span>
                <span className={`chip ${tone}`}>{statusLabel(stage.status)}</span>
              </div>
              <p className="mt-1 text-sm font-semibold text-slate-800">{stage.label}</p>
              <p className="mt-0.5 truncate text-[11px] text-slate-500">
                {stage.artifact_title || "no artifact yet"}
              </p>
              {stage.status === "AWAITING_APPROVAL" && (
                <p className="mt-1 text-[11px] font-medium text-amber-700">
                  waiting for your decision
                </p>
              )}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
