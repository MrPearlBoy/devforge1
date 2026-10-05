import { useState } from "react";
import { AlertTriangle, Check, GitPullRequest, Loader2, MessageSquareWarning, X } from "lucide-react";

const GATE_INFO: Record<string, { title: string; description: string; hint: string }> = {
  requirement: {
    title: "Gate 1 — Requirement Approved?",
    description: "The Requirement Agent produced a structured SRS from your task. Review functional requirements and acceptance criteria.",
    hint: "Rejecting or requesting changes re-runs the Requirement Agent with your feedback.",
  },
  architecture: {
    title: "Gate 2 — Architecture Approved?",
    description: "The Architecture Agent proposed the tech stack, API schema, directory structure and module design.",
    hint: "Your feedback is routed back to the Architecture Agent for revision.",
  },
  code: {
    title: "Gate 3 — Code Approved?",
    description: "The Coding Agent wrote the full codebase into the project workspace. Inspect the files in the Code tab.",
    hint: "Instructions for the Coding Agent are applied in its next revision.",
  },
  docs: {
    title: "Gate 6 — Docs Approved?",
    description: "The Documentation Agent generated README, API reference and architecture summary from the actual code.",
    hint: "Requesting changes re-runs the Documentation Agent.",
  },
};

interface Props {
  gate: string;
  summary: string;
  busy?: boolean;
  onDecide: (gate: string, decision: "approved" | "rejected" | "changes_requested", comment: string) => void;
}

export default function ApprovalModal({ gate, summary, busy, onDecide }: Props) {
  const [decision, setDecision] = useState<"approved" | "rejected" | "changes_requested" | null>(null);
  const [comment, setComment] = useState("");
  const info = GATE_INFO[gate] ?? {
    title: `Gate — ${gate}`,
    description: "A human approval gate is pending.",
    hint: "",
  };

  const needsComment = decision === "rejected" || decision === "changes_requested";
  const canSubmit = decision !== null && (!needsComment || comment.trim().length > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-lg border-amber-400/30 p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-400/15 text-amber-300">
            <GitPullRequest size={20} />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-50">{info.title}</h2>
            <p className="mt-1 text-sm text-slate-400">{info.description}</p>
            {summary && (
              <div className="mt-2 rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-indigo-200">
                {summary}
              </div>
            )}
          </div>
          <button
            className="ml-auto rounded-md p-1 text-slate-500 hover:bg-ink-800 hover:text-slate-300"
            onClick={() => {
              setDecision(null);
              setComment("");
            }}
            title="minimize (workflow keeps waiting)"
          >
            <X size={16} />
          </button>
        </div>

        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
          placeholder={
            decision === "approved"
              ? "Optional comment for the audit trail…"
              : "Describe the changes you expect (required)…"
          }
          className="mt-4 w-full resize-none rounded-lg border border-ink-700 bg-ink-950 p-3 text-sm text-slate-200 placeholder:text-slate-600 focus:border-indigo-500 focus:outline-none"
        />

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            className={`btn ${
              decision === "approved"
                ? "bg-emerald-500 text-ink-950 hover:bg-emerald-400"
                : "bg-emerald-600 text-white hover:bg-emerald-500"
            }`}
            disabled={busy}
            onClick={() => setDecision("approved")}
          >
            <Check size={15} /> Approve
          </button>
          <button
            className={`btn ${
              decision === "changes_requested"
                ? "bg-amber-500 text-ink-950 hover:bg-amber-400"
                : "border border-amber-500/50 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
            }`}
            disabled={busy}
            onClick={() => setDecision("changes_requested")}
          >
            <MessageSquareWarning size={15} /> Request Changes
          </button>
          <button
            className={`btn ${
              decision === "rejected"
                ? "bg-rose-600 text-white hover:bg-rose-500"
                : "border border-rose-500/50 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
            }`}
            disabled={busy}
            onClick={() => setDecision("rejected")}
          >
            <X size={15} /> Reject
          </button>

          <div className="ml-auto">
            <button
              className="btn-primary"
              disabled={!canSubmit || busy}
              onClick={() => {
                if (decision) onDecide(gate, decision, comment.trim());
              }}
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
              Submit {decision === "approved" ? "Approval" : decision === "rejected" ? "Rejection" : "Changes"}
            </button>
          </div>
        </div>

        {needsComment && comment.trim().length === 0 && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-rose-400">
            <AlertTriangle size={13} /> A comment is required — it is injected into the agent's next prompt.
          </p>
        )}
        {info.hint && <p className="mt-3 text-[11px] text-slate-500">{info.hint}</p>}
      </div>
    </div>
  );
}
