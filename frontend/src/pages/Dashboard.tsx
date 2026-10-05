import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  Bot,
  CheckCircle2,
  ClipboardList,
  Code2,
  FlaskConical,
  GitBranch,
  GitCommit,
  Hammer,
  ListChecks,
  Loader2,
  Network,
  Play,
  Plus,
  RefreshCw,
  Rocket,
  ScanSearch,
  ShieldCheck,
  Trash2,
  User,
  XCircle,
} from "lucide-react";
import ApprovalModal from "../components/ApprovalModal";
import CodeViewer from "../components/CodeViewer";
import LogsConsole from "../components/LogsConsole";
import PipelineVisualizer from "../components/PipelineVisualizer";
import StatusBadge from "../components/StatusBadge";
import { Markdown } from "../lib/markdown";
import { api, WorkflowStream, type StreamEvent } from "../lib/api";
import type { FileNode, ProjectSnapshot, Role, TabKey } from "../lib/types";

const ROLES: { key: Role; label: string; icon: typeof User }[] = [
  { key: "developer", label: "Developer", icon: Code2 },
  { key: "architect", label: "Architect", icon: Network },
  { key: "tester", label: "Tester", icon: FlaskConical },
  { key: "pm", label: "Project Manager", icon: ClipboardList },
];

const ROLE_DEFAULT_TAB: Record<Role, TabKey> = {
  developer: "code",
  architect: "specs",
  tester: "tests",
  pm: "audit",
};

const TABS: { key: TabKey; label: string; icon: typeof Code2 }[] = [
  { key: "code", label: "Code", icon: Code2 },
  { key: "specs", label: "Specs", icon: ClipboardList },
  { key: "tests", label: "Tests", icon: FlaskConical },
  { key: "security", label: "Security", icon: ShieldCheck },
  { key: "docs", label: "Docs", icon: BookOpen },
  { key: "audit", label: "Audit", icon: ListChecks },
];

export default function Dashboard() {
  const [projects, setProjects] = useState<ProjectSnapshot[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snap, setSnap] = useState<ProjectSnapshot | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [role, setRole] = useState<Role>("developer");
  const [tab, setTab] = useState<TabKey>("code");
  const [files, setFiles] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [modalGate, setModalGate] = useState<string | null>(null);
  const [modalBusy, setModalBusy] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const toastTimer = useRef<number | null>(null);

  const showToast = useCallback((kind: "ok" | "err", text: string) => {
    setToast({ kind, text });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 5000);
  }, []);

  const refreshProjects = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      return list;
    } catch {
      return null;
    }
  }, []);

  const refreshSnapshot = useCallback(async (id: string) => {
    try {
      const s = await api.getProject(id);
      setSnap(s);
      setFiles(s.files);
      return s;
    } catch {
      return null;
    }
  }, []);

  // initial load
  useEffect(() => {
    refreshProjects().then((list) => {
      if (list && list.length > 0) setSelectedId((cur) => cur ?? list[0].id);
    });
  }, [refreshProjects]);

  // stream + polling for the selected project
  useEffect(() => {
    if (!selectedId) {
      setSnap(null);
      setEvents([]);
      return;
    }
    let cancelled = false;
    setEvents([]);
    setModalGate(null);
    setSelectedFile(null);
    setFileContent(null);

    refreshSnapshot(selectedId).then((s) => {
      if (cancelled) return;
      if (s) {
        setEvents(s.events);
        setModalGate(s.awaiting_gate);
      }
    });

    const stream = new WorkflowStream(selectedId, (e) => {
      if (cancelled) return;
      setEvents((prev) => {
        const next = [...prev, e];
        return next.length > 500 ? next.slice(next.length - 500) : next;
      });
      if (e.type === "approval_requested") setModalGate((e.payload?.gate as string) ?? null);
      if (e.type === "approval_recorded") setModalGate(null);
      if (["file", "git", "done", "error", "artifact"].includes(e.type)) refreshSnapshot(selectedId);
    });
    stream.connect();

    const poll = window.setInterval(() => refreshSnapshot(selectedId), 6000);
    return () => {
      cancelled = true;
      stream.disconnect();
      window.clearInterval(poll);
    };
  }, [selectedId, refreshSnapshot]);

  // keep the selected file sensible as the workspace changes
  useEffect(() => {
    if (!selectedFile && files.length > 0) {
      const pick = files.find((f) => f.path.startsWith("src/") && f.path.endsWith(".py"))?.path
        ?? files.find((f) => f.path === "README.md")?.path
        ?? files[0]?.path;
      if (pick) setSelectedFile(pick);
    }
    if (selectedFile && !files.some((f) => f.path === selectedFile)) {
      setSelectedFile(null);
      setFileContent(null);
    }
  }, [files, selectedFile]);

  // load file content
  useEffect(() => {
    if (!selectedId || !selectedFile) {
      setFileContent(null);
      return;
    }
    let cancelled = false;
    setFileLoading(true);
    api
      .readFile(selectedId, selectedFile)
      .then((r) => !cancelled && setFileContent(r.content))
      .catch((e) => !cancelled && setFileContent(String(e.message ?? e)))
      .finally(() => !cancelled && setFileLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selectedId, selectedFile]);

  // role switch → default tab
  const switchRole = (r: Role) => {
    setRole(r);
    setTab(ROLE_DEFAULT_TAB[r]);
  };

  const startWorkflow = async (id: string) => {
    setBusy(true);
    try {
      const r = await api.startWorkflow(id);
      if (!r.started) showToast("err", "Workflow is already running.");
      else showToast("ok", `Workflow started at stage '${r.stage}'.`);
      await refreshSnapshot(id);
      await refreshProjects();
    } catch (e) {
      showToast("err", e instanceof Error ? e.message : "failed to start workflow");
    } finally {
      setBusy(false);
    }
  };

  const decide = async (gate: string, decision: "approved" | "rejected" | "changes_requested", comment: string) => {
    if (!selectedId) return;
    setModalBusy(true);
    try {
      await api.submitApproval(selectedId, gate, decision, comment);
      setModalGate(null);
      showToast("ok", `Gate '${gate}' ${decision.replace("_", " ")} recorded.`);
      await refreshSnapshot(selectedId);
      await refreshProjects();
    } catch (e) {
      showToast("err", e instanceof Error ? e.message : "approval failed");
    } finally {
      setModalBusy(false);
    }
  };

  const deleteProject = async (id: string) => {
    if (!window.confirm("Delete this project and its workspace?")) return;
    try {
      await api.deleteProject(id);
      if (selectedId === id) setSelectedId(null);
      await refreshProjects();
      showToast("ok", "Project deleted.");
    } catch (e) {
      showToast("err", e instanceof Error ? e.message : "delete failed");
    }
  };

  const snapStage = snap?.stage ?? "created";
  const snapStatus = snap?.status ?? "idle";
  const started = !["created", "idle"].includes(snapStage) || ["running", "waiting_approval", "completed", "failed", "interrupted"].includes(snapStatus);

  return (
    <div className="mx-auto flex min-h-screen max-w-[1500px] flex-col gap-4 p-4">
      {/* ── header ─────────────────────────────────────────────── */}
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-900/40">
            <Hammer size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-base font-bold leading-none tracking-tight">DevForge</h1>
            <p className="mt-0.5 text-[11px] text-slate-500">multi-agent AI software engineering</p>
          </div>
        </div>

        <div className="mx-2 hidden h-8 w-px bg-ink-700 sm:block" />

        <select
          value={selectedId ?? ""}
          onChange={(e) => setSelectedId(e.target.value || null)}
          className="h-9 max-w-[280px] rounded-lg border border-ink-700 bg-ink-900 px-2.5 text-sm text-slate-200 focus:border-indigo-500 focus:outline-none"
        >
          <option value="">— select project —</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} · {p.stage}
            </option>
          ))}
        </select>

        {snap && (
          <>
            <StatusBadge status={snapStatus} />
            <span className="chip bg-ink-800 text-slate-400">
              <Bot size={11} /> LLM: {snap.llm_provider || "—"}
            </span>
            <button className="btn-ghost h-9" onClick={() => startWorkflow(snap.id)} disabled={busy || snapStatus === "completed" || snapStatus === "running"}>
              {snapStatus === "running" ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {snapStatus === "running" ? "Running…" : snapStatus === "completed" ? "Completed" : started ? "Resume" : "Start Workflow"}
            </button>
            <button className="btn-ghost h-9" onClick={() => deleteProject(snap.id)} title="delete project">
              <Trash2 size={14} className="text-rose-400" />
            </button>
          </>
        )}

        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
            {ROLES.map((r) => {
              const Icon = r.icon;
              return (
                <button
                  key={r.key}
                  onClick={() => switchRole(r.key)}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    role === r.key ? "bg-ink-700 text-slate-100" : "text-slate-500 hover:text-slate-300"
                  }`}
                  title={`${r.label} view`}
                >
                  <Icon size={13} />
                  <span className="hidden md:inline">{r.label}</span>
                </button>
              );
            })}
          </div>
          <button className="btn-primary h-9" onClick={async () => { setShowNew(true); await refreshProjects(); }}>
            <Plus size={15} /> New Project
          </button>
        </div>
      </header>

      {/* ── pipeline ───────────────────────────────────────────── */}
      <PipelineVisualizer
        stage={snapStage}
        status={snapStatus}
        awaitingGate={snap?.awaiting_gate ?? null}
        iterations={snap?.iterations ?? {}}
      />

      {/* ── main grid ──────────────────────────────────────────── */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[1fr_400px]">
        <section className="panel flex min-h-[520px] flex-col p-3">
          {!snap && (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-slate-600">
              <Activity size={28} />
              <p className="text-sm">Select a project or create a new one to start the multi-agent pipeline.</p>
            </div>
          )}

          {snap && !started && (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
              <Rocket size={30} className="text-indigo-400" />
              <h2 className="text-lg font-semibold">{snap.name}</h2>
              <p className="max-w-md text-sm text-slate-400">“{snap.task}”</p>
              <button className="btn-primary mt-2 h-10 px-5" onClick={() => startWorkflow(snap.id)} disabled={busy}>
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                Start Multi-Agent Workflow
              </button>
              <p className="text-xs text-slate-600">Requirement → Architecture → Coding → Testing → Security → Documentation → Delivery</p>
            </div>
          )}

          {snap && started && (
            <>
              {/* tabs */}
              <div className="mb-3 flex flex-wrap items-center gap-1">
                {TABS.map((t) => {
                  const Icon = t.icon;
                  const active = tab === t.key;
                  return (
                    <button
                      key={t.key}
                      onClick={() => setTab(t.key)}
                      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                        active ? "bg-indigo-500/20 text-indigo-200" : "text-slate-500 hover:bg-ink-800 hover:text-slate-300"
                      }`}
                    >
                      <Icon size={13} /> {t.label}
                    </button>
                  );
                })}
                {snap.error && (
                  <span className="ml-auto flex items-center gap-1.5 rounded-lg bg-rose-500/10 px-2.5 py-1 text-[11px] text-rose-300">
                    <XCircle size={12} /> {snap.error}
                  </span>
                )}
              </div>

              <div className="min-h-0 flex-1">
                {tab === "code" && (
                  <CodeViewer
                    files={files}
                    selected={selectedFile}
                    content={fileContent}
                    loading={fileLoading}
                    onSelect={setSelectedFile}
                  />
                )}
                {tab === "specs" && <SpecsTab snap={snap} />}
                {tab === "tests" && <TestsTab snap={snap} />}
                {tab === "security" && <SecurityTab snap={snap} />}
                {tab === "docs" && <DocsTab snap={snap} />}
                {tab === "audit" && <AuditTab events={events} snap={snap} />}
              </div>
            </>
          )}
        </section>

        {/* live logs */}
        <aside className="panel min-h-[320px] p-1 xl:min-h-0">
          <div className="flex h-full min-h-[300px] p-1.5">
            <LogsConsole events={events} />
          </div>
        </aside>
      </div>

      {/* ── approval modal ─────────────────────────────────────── */}
      {modalGate && snap && (
        <ApprovalModal
          gate={modalGate}
          summary={gateSummary(snap, modalGate)}
          busy={modalBusy}
          onDecide={decide}
        />
      )}

      {/* ── new project form ───────────────────────────────────── */}
      {showNew && (
        <NewProjectForm
          onClose={() => setShowNew(false)}
          onCreated={async (id) => {
            setShowNew(false);
            setSelectedId(id);
            await refreshProjects();
            await startWorkflow(id);
          }}
          onError={(m) => showToast("err", m)}
        />
      )}

      {/* toast */}
      {toast && (
        <div
          className={`fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 rounded-lg border px-4 py-2 text-sm shadow-xl ${
            toast.kind === "ok"
              ? "border-emerald-500/40 bg-emerald-950/90 text-emerald-200"
              : "border-rose-500/40 bg-rose-950/90 text-rose-200"
          }`}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}

/* ──────────────────────────────────────────────────────────────────────── */

function gateSummary(snap: ProjectSnapshot, gate: string): string {
  const a = snap.artifacts;
  if (gate === "requirement" && a.requirement)
    return `${a.requirement.functional_requirements.length} functional requirements · ${a.requirement.user_stories.length} user stories · ${a.requirement.non_functional_requirements.length} NFRs`;
  if (gate === "architecture" && a.architecture)
    return `${a.architecture.api_endpoints.length} API endpoints · ${a.architecture.modules.length} modules · stack: ${Object.values(a.architecture.tech_stack).slice(0, 2).join(", ")}`;
  if (gate === "code" && a.code) return `${a.code.files.length} files written to the workspace — inspect them in the Code tab`;
  if (gate === "docs" && a.docs) return "README.md + docs/api.md + docs/architecture.md generated from the actual code";
  return "";
}

/* ── Specs tab ──────────────────────────────────────────────────────── */
function SpecsTab({ snap }: { snap: ProjectSnapshot }) {
  const a = snap.artifacts;
  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 overflow-y-auto pr-1 lg:grid-cols-2">
      <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-4">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-indigo-300">
          <ClipboardList size={14} /> Software Requirements
        </h3>
        {a.requirement ? (
          <div className="space-y-3 text-sm">
            <p className="text-slate-400">{a.requirement.overview}</p>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Functional</p>
              <ul className="space-y-1">
                {a.requirement.functional_requirements.map((fr, i) => (
                  <li key={i} className="flex gap-2 text-slate-300">
                    <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-400" /> {fr}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">User stories</p>
              <div className="space-y-2">
                {a.requirement.user_stories.map((us) => (
                  <div key={us.id} className="rounded-md border border-ink-800 bg-ink-900/60 p-2 text-xs">
                    <p className="font-medium text-slate-200">
                      {us.id} — {us.title}
                    </p>
                    <p className="mt-0.5 italic text-slate-500">{us.story}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-600">No requirements yet.</p>
        )}
      </div>

      <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-4">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-violet-300">
          <Network size={14} /> Architecture
        </h3>
        {a.architecture ? (
          <div className="space-y-3 text-sm">
            <p className="text-slate-400">{a.architecture.summary}</p>
            <table className="w-full text-xs">
              <tbody>
                {Object.entries(a.architecture.tech_stack).map(([k, v]) => (
                  <tr key={k} className="border-b border-ink-800/60">
                    <td className="py-1 pr-3 font-medium text-slate-400">{k}</td>
                    <td className="py-1 text-slate-300">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div>
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">API endpoints</p>
              <div className="flex flex-wrap gap-1.5">
                {a.architecture.api_endpoints.map((ep, i) => (
                  <span key={i} className="chip bg-ink-800 font-mono text-[10.5px] text-slate-300">
                    <span className="text-indigo-300">{ep.method}</span> {ep.path}
                  </span>
                ))}
              </div>
            </div>
            <pre className="overflow-x-auto rounded-md bg-ink-900 p-2 font-mono text-[10.5px] leading-relaxed text-slate-400">
              {a.architecture.directory_structure}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-slate-600">No architecture yet.</p>
        )}
      </div>
    </div>
  );
}

/* ── Tests tab ──────────────────────────────────────────────────────── */
function TestsTab({ snap }: { snap: ProjectSnapshot }) {
  const t = snap.artifacts.tests;
  const runs = snap.test_runs;
  return (
    <div className="h-full space-y-3 overflow-y-auto pr-1">
      {!t && <p className="p-4 text-sm text-slate-600">No test runs yet — the Testing Agent generates and executes the suite.</p>}
      {t && (
        <div className={`rounded-lg border p-4 ${t.passed ? "border-emerald-500/40 bg-emerald-500/5" : "border-rose-500/40 bg-rose-500/5"}`}>
          <div className="flex items-center gap-3">
            {t.passed ? (
              <CheckCircle2 size={26} className="text-emerald-400" />
            ) : (
              <XCircle size={26} className="text-rose-400" />
            )}
            <div>
              <p className="text-base font-semibold text-slate-100">
                {t.passed ? "All tests passed" : "Tests failing"} — {t.summary}
              </p>
              <p className="text-xs text-slate-400">
                {t.passed_count}/{t.total} passed · exit code {t.exit_code} · {t.duration_s}s in the sandbox
              </p>
            </div>
          </div>
          {t.failures && t.failures.length > 0 && (
            <div className="mt-3 rounded-md bg-ink-950 p-2 font-mono text-[11px] text-rose-300">
              {t.failures.map((f, i) => (
                <div key={i}>{f}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {runs.length > 0 && (
        <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-3">
          <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <FlaskConical size={13} /> Run history (latest {runs.length})
          </p>
          {runs.map((r, i) => (
            <div key={i} className="flex items-center gap-3 border-b border-ink-800/50 py-1.5 text-xs last:border-0">
              <span className={r.passed ? "text-emerald-400" : "text-rose-400"}>{r.passed ? "✓" : "✗"}</span>
              <span className="text-slate-400">run #{r.run_number}</span>
              <span className="text-slate-300">{r.summary}</span>
              <span className="ml-auto text-slate-600">{r.duration_s}s</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Security tab ───────────────────────────────────────────────────── */
const SEV_CLS: Record<string, string> = {
  HIGH: "bg-rose-500/15 text-rose-300",
  MEDIUM: "bg-amber-400/15 text-amber-300",
  LOW: "bg-sky-500/15 text-sky-300",
  INFO: "bg-slate-500/15 text-slate-400",
};

function SecurityTab({ snap }: { snap: ProjectSnapshot }) {
  const s = snap.artifacts.security;
  return (
    <div className="h-full space-y-3 overflow-y-auto pr-1">
      {!s && <p className="p-4 text-sm text-slate-600">No scan yet — the Security Agent runs after tests pass.</p>}
      {s && (
        <div className={`rounded-lg border p-4 ${s.clean ? "border-emerald-500/40 bg-emerald-500/5" : "border-rose-500/40 bg-rose-500/5"}`}>
          <div className="flex items-center gap-3">
            <ShieldCheck size={26} className={s.clean ? "text-emerald-400" : "text-rose-400"} />
            <div>
              <p className="text-base font-semibold">
                {s.clean ? "Security scan clean" : "Security findings require a fix loop"}
              </p>
              <p className="text-xs text-slate-400">
                scanned with <span className="font-mono text-slate-300">{s.tool}</span> · {s.findings.length} finding(s)
              </p>
            </div>
          </div>
        </div>
      )}
      {s && s.findings.length > 0 && (
        <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-3">
          {s.findings.map((f, i) => (
            <div key={i} className="flex items-start gap-2 border-b border-ink-800/50 py-2 text-xs last:border-0">
              <span className={`chip mt-0.5 shrink-0 ${SEV_CLS[f.severity] ?? SEV_CLS.INFO}`}>{f.severity}</span>
              <div className="min-w-0">
                <p className="text-slate-200">{f.message}</p>
                <p className="mt-0.5 font-mono text-[10.5px] text-slate-500">
                  {f.category}
                  {f.file ? ` · ${f.file}${f.line ? `:${f.line}` : ""}` : ""}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
      {s && s.clean && (
        <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-3 text-xs text-slate-500">
          <p className="flex items-center gap-2 font-semibold text-slate-400">
            <ScanSearch size={13} /> Scanner coverage
          </p>
          <p className="mt-1">
            hardcoded secrets · SQL string interpolation · eval/exec · os.system · subprocess shell=True · unsafe pickle/yaml · weak hashes (md5/sha1) · TLS verify disabled.
            HIGH severity blocks the pipeline and triggers the Coding Agent fix loop (D5).
          </p>
        </div>
      )}
    </div>
  );
}

/* ── Docs tab ───────────────────────────────────────────────────────── */
function DocsTab({ snap }: { snap: ProjectSnapshot }) {
  const d = snap.artifacts.docs;
  const [sub, setSub] = useState<"readme" | "api" | "arch">("readme");
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      {!d ? (
        <p className="p-4 text-sm text-slate-600">No docs yet — the Documentation Agent generates them after the security scan.</p>
      ) : (
        <>
          <div className="flex gap-1">
            {(
              [
                ["readme", "README.md"],
                ["api", "docs/api.md"],
                ["arch", "docs/architecture.md"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setSub(k)}
                className={`rounded-lg px-3 py-1.5 font-mono text-xs ${
                  sub === k ? "bg-indigo-500/20 text-indigo-200" : "text-slate-500 hover:bg-ink-800 hover:text-slate-300"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-ink-700/60 bg-ink-950 p-4">
            <Markdown source={sub === "readme" ? d.readme : sub === "api" ? d.api_documentation : d.architecture_summary} />
          </div>
        </>
      )}
    </div>
  );
}

/* ── Audit tab ──────────────────────────────────────────────────────── */
function AuditTab({ events, snap }: { events: StreamEvent[]; snap: ProjectSnapshot }) {
  const g = snap.artifacts.git;
  const rows = useMemo(() => events.filter((e) => !["state"].includes(e.type)), [events]);
  return (
    <div className="h-full space-y-3 overflow-y-auto pr-1">
      {g && (
        <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-4">
          <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <GitCommit size={13} /> Delivery
          </p>
          <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div>
              <p className="text-slate-500">Commit</p>
              <p className="mt-0.5 font-mono text-cyan-300">{g.hash ? g.hash.slice(0, 10) : "—"}</p>
            </div>
            <div>
              <p className="text-slate-500">Branch</p>
              <p className="mt-0.5 flex items-center gap-1 font-mono text-slate-300">
                <GitBranch size={11} /> {g.branch ?? "main"}
              </p>
            </div>
            <div>
              <p className="text-slate-500">Files</p>
              <p className="mt-0.5 font-mono text-slate-300">{g.files ?? "—"}</p>
            </div>
            <div>
              <p className="text-slate-500">CI workflow</p>
              <p className="mt-0.5 font-mono text-emerald-300">.github/workflows/ci.yml</p>
            </div>
          </div>
        </div>
      )}
      <div className="rounded-lg border border-ink-700/60 bg-ink-950 p-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Audit trail ({rows.length} events)</p>
        <div className="space-y-1.5">
          {[...rows].reverse().map((e, i) => (
            <div key={i} className="flex items-start gap-2 border-b border-ink-800/40 pb-1.5 text-xs last:border-0">
              <span className="w-24 shrink-0 pt-0.5 text-right font-mono text-[10px] leading-5 text-slate-600">
                {e.ts ? new Date(e.ts).toTimeString().slice(0, 8) : ""}
              </span>
              <span className="w-32 shrink-0 truncate font-medium text-indigo-300/90">{e.type}</span>
              <span className="min-w-0 break-words text-slate-300">{e.message}</span>
            </div>
          ))}
          {rows.length === 0 && <p className="text-slate-600">No events yet.</p>}
        </div>
      </div>
    </div>
  );
}

/* ── New project form ───────────────────────────────────────────────── */
function NewProjectForm({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
  onError: (msg: string) => void;
}) {
  const [name, setName] = useState("");
  const [task, setTask] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (name.trim().length < 2 || task.trim().length < 10) {
      onError("Name needs 2+ chars; task description needs 10+ chars.");
      return;
    }
    setSaving(true);
    try {
      const p = await api.createProject(name.trim(), task.trim());
      onCreated(p.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : "failed to create project");
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
      <div className="panel w-full max-w-xl p-5">
        <h2 className="text-base font-semibold">New DevForge project</h2>
        <p className="mt-1 text-xs text-slate-500">
          The Requirement Agent turns your task into an SRS. The pipeline then proceeds through architecture, coding, testing, security, docs and git delivery — pausing at each human approval gate.
        </p>
        <label className="mt-4 block text-xs font-medium text-slate-400">Project name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. URL Shortener Service"
          className="mt-1 w-full rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
        />
        <label className="mt-3 block text-xs font-medium text-slate-400">Task description (Requirement Agent input)</label>
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={4}
          placeholder="Build a URL shortener service with CRUD for links, click counters, expiry and a REST-style API."
          className="mt-1 w-full resize-none rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={submit} disabled={saving}>
            {saving ? <Loader2 size={15} className="animate-spin" /> : <Rocket size={15} />}
            Create & Start
          </button>
        </div>
      </div>
    </div>
  );
}
