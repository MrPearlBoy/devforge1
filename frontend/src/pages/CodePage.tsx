import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../services/api";
import { useApi, relativeTime } from "../hooks/useApi";
import { Card, EmptyState, ErrorNote, Loading } from "../components/ui";
import { CodeViewer } from "../components/CodeViewer";

const GROUP_ORDER = [
  "backend",
  "frontend",
  "tests",
  "requirements",
  "architecture",
  "security",
  "documentation",
  "root",
];

/** Generated workspace browser with Monaco preview. */
export function CodePage() {
  const { projectId = "" } = useParams();
  const tree = useApi(() => api.workspace(projectId), [projectId]);
  const [selected, setSelected] = useState<string>("");
  const [content, setContent] = useState<{ text: string; language: string; size: number; truncated: boolean } | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [error, setError] = useState("");

  const groups = useMemo(() => {
    const entries = Object.entries(tree.data?.groups || {});
    return entries.sort(
      ([a], [b]) => (GROUP_ORDER.indexOf(a) + 1 || 99) - (GROUP_ORDER.indexOf(b) + 1 || 99),
    );
  }, [tree.data]);

  useEffect(() => {
    if (!selected && tree.data) {
      const first = groups.flatMap(([, files]) => files)[0];
      if (first) setSelected(first.path);
    }
  }, [tree.data, groups, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setLoadingFile(true);
    api
      .workspaceFile(projectId, selected)
      .then((file) => {
        if (!cancelled)
          setContent({ text: file.content, language: file.language, size: file.size, truncated: file.truncated });
      })
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not read the file."))
      .finally(() => !cancelled && setLoadingFile(false));
    return () => {
      cancelled = true;
    };
  }, [projectId, selected]);

  if (tree.loading && !tree.data) return <Loading label="Loading workspace…" />;
  if (!tree.data) return <ErrorNote message={tree.error || "Workspace unavailable."} />;

  if (!tree.data.total_files) {
    return (
      <EmptyState
        title="The workspace is empty"
        hint="Run the workflow (or approve the Developer Agent's change set) and the generated project files will appear here."
      />
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
      <Card
        title="Workspace"
        subtitle={`${tree.data.total_files} files · ${tree.data.root.split("/").slice(-1)[0]}`}
      >
        <div className="max-h-[34rem] space-y-3 overflow-y-auto pr-1">
          {groups.map(([group, files]) => (
            <div key={group}>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {group} ({files.length})
              </p>
              <ul className="space-y-0.5">
                {files.map((file) => (
                  <li key={file.path}>
                    <button
                      onClick={() => setSelected(file.path)}
                      className={`w-full truncate rounded px-2 py-1 text-left font-mono text-[11px] transition-colors ${
                        selected === file.path
                          ? "bg-forge-50 text-forge-800"
                          : "text-slate-600 hover:bg-slate-50"
                      }`}
                      title={file.path}
                    >
                      {file.path}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Card>

      <Card
        title={selected || "Select a file"}
        subtitle={
          content
            ? `${content.size} bytes · ${content.language}${content.truncated ? " · truncated for display" : ""}${
                tree.data.groups
                  ? (() => {
                      const file = Object.values(tree.data.groups)
                        .flat()
                        .find((item) => item.path === selected);
                      return file?.modified_at ? ` · updated ${relativeTime(file.modified_at)}` : "";
                    })()
                  : ""
              }`
            : undefined
        }
      >
        <ErrorNote message={error} />
        {loadingFile && <Loading label="Reading file…" />}
        {content && !loadingFile && (
          <CodeViewer value={content.text} language={content.language} height="62vh" />
        )}
      </Card>
    </div>
  );
}
