import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi } from "../hooks/useApi";
import { Card, Chip, EmptyState, ErrorNote, Loading, Stat } from "../components/ui";

const TYPE_TONES: Record<string, string> = {
  REQUIREMENT: "bg-sky-50 text-sky-700 ring-1 ring-sky-200",
  ARCHITECTURE: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
  CODE: "bg-forge-50 text-forge-700 ring-1 ring-forge-200",
  TEST: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  SECURITY: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
  DOCUMENTATION: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
};

/** Traceability matrix: coverage per requirement and the full link list. */
export function TraceabilityPage() {
  const { projectId = "" } = useParams();
  const matrix = useApi(() => api.trace(projectId), [projectId], { pollMs: 20000 });
  const [selected, setSelected] = useState("REQ-001");
  const [chain, setChain] = useState<{ ref: string; links: { source_ref: string; target_ref: string; relation: string }[] } | null>(null);
  const [error, setError] = useState("");

  const requirements = (matrix.data?.nodes || []).filter((node) => node.type === "REQUIREMENT");
  const percent = (matrix.data?.coverage?.percent as Record<string, number>) || {};

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    api
      .traceChain(projectId, selected)
      .then((value) => {
        if (!cancelled) {
          setChain({ ref: value.root.ref, links: value.links });
          setError("");
        }
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "No chain."));
    return () => {
      cancelled = true;
    };
  }, [projectId, selected, matrix.data]);

  const downstream = new Set(
    (chain?.links || [])
      .filter((link) => link.source_ref === selected)
      .map((link) => link.target_ref),
  );
  const chains = (matrix.data?.links || []).filter((link) => link.source_ref === selected);

  if (matrix.loading && !matrix.data) return <Loading label="Building the traceability matrix…" />;
  if (!matrix.data) return <ErrorNote message={matrix.error || "Traceability unavailable."} />;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Requirements" value={matrix.data.nodes.filter((n) => n.type === "REQUIREMENT").length} />
        <Stat label="Nodes" value={matrix.data.nodes.length} />
        <Stat label="Links" value={matrix.data.links.length} />
        <Stat label="→ Architecture" value={`${percent.with_architecture ?? 0}%`} />
        <Stat label="→ Code" value={`${percent.with_code ?? 0}%`} />
        <Stat label="→ Tests" value={`${percent.with_tests ?? 0}%`} />
      </div>

      <Card
        title="Coverage"
        subtitle="Percentage of requirements that reach each artefact type through the trace graph"
      >
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {[
            ["Architecture", percent.with_architecture],
            ["Code", percent.with_code],
            ["Tests", percent.with_tests],
            ["Security", percent.with_security_check],
            ["Documentation", percent.with_documentation],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-lg border border-slate-200 p-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                {label}
              </p>
              <p className="mt-1 text-lg font-semibold text-slate-900">{value ?? 0}%</p>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full rounded-full bg-forge-500"
                  style={{ width: `${Math.min(100, Number(value) || 0)}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        {matrix.data.gap_report.length > 0 && (
          <div className="mt-4">
            <p className="label">Gap report (what the agents should still address)</p>
            <ul className="space-y-1 text-xs text-slate-600">
              {matrix.data.gap_report.map((gap) => (
                <li key={gap} className="rounded bg-amber-50 px-2.5 py-1.5 text-amber-900 ring-1 ring-amber-100">
                  {gap}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Card title="Requirements" subtitle="Select one to inspect its chain">
          <ul className="max-h-[26rem] space-y-1 overflow-y-auto pr-1">
            {requirements.map((node) => (
              <li key={node.ref}>
                <button
                  onClick={() => setSelected(node.ref)}
                  className={`w-full rounded-lg px-2.5 py-2 text-left text-xs transition-colors ${
                    selected === node.ref ? "bg-forge-50 text-forge-800" : "hover:bg-slate-50"
                  }`}
                >
                  <span className="font-mono font-semibold">{node.ref}</span>
                  <span className="ml-2 text-slate-500">{node.label.slice(0, 60)}</span>
                </button>
              </li>
            ))}
            {!requirements.length && (
              <li className="py-6 text-center text-xs text-slate-500">
                No requirements traced yet — run the workflow.
              </li>
            )}
          </ul>
        </Card>

        <Card
          title={`Chain for ${selected}`}
          subtitle={error || `${downstream.size} directly linked artefacts`}
        >
          {!chains.length && (
            <EmptyState
              title="No links recorded for this node"
              hint="Approve the earlier stages so the agents can attach code, tests, security checks and documentation to this requirement."
            />
          )}
          <ul className="space-y-2">
            {chains.map((link) => (
              <li key={link.id} className="flex flex-wrap items-center gap-2 text-xs">
                <span className={`chip ${TYPE_TONES[link.source_type] || "bg-slate-100 text-slate-600"}`}>
                  {link.source_ref}
                </span>
                <span className="text-slate-400">—{link.relation.replace(/_/g, " ")}→</span>
                <span className={`chip ${TYPE_TONES[link.target_type] || "bg-slate-100 text-slate-600"}`}>
                  {link.target_ref}
                </span>
                {link.target_label && (
                  <span className="truncate text-slate-500">{link.target_label.slice(0, 70)}</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="All trace links" subtitle={`${matrix.data.links.length} relationships stored`}>
        <div className="max-h-[24rem] overflow-auto">
          <table className="w-full min-w-[40rem] text-left text-[11px]">
            <thead className="sticky top-0 bg-white text-[10px] uppercase tracking-wide text-slate-400">
              <tr>
                <th className="py-2">Source</th>
                <th className="py-2">Relation</th>
                <th className="py-2">Target</th>
                <th className="py-2">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {matrix.data.links.slice(0, 300).map((link) => (
                <tr key={link.id}>
                  <td className="py-1.5">
                    <Chip label={link.source_type} tone={TYPE_TONES[link.source_type]} />
                    <span className="ml-2 font-mono text-slate-700">{link.source_ref}</span>
                  </td>
                  <td className="py-1.5 text-slate-500">{link.relation.replace(/_/g, " ")}</td>
                  <td className="py-1.5">
                    <Chip label={link.target_type} tone={TYPE_TONES[link.target_type]} />
                    <span className="ml-2 font-mono text-slate-700">{link.target_ref}</span>
                  </td>
                  <td className="py-1.5 text-slate-500">{Math.round((link.confidence || 1) * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
