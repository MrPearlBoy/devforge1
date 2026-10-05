import { useEffect, useState } from "react";
import Editor, { loader } from "@monaco-editor/react";

/**
 * Code viewer built on Monaco.
 *
 * Monaco itself is loaded lazily (from the bundled loader/CDN). If it cannot be fetched —
 * an offline lab machine, a locked-down browser — the component degrades to a styled
 * read-only <pre> block instead of failing: reviewing generated code must always work.
 */
let monacoState: "unknown" | "ready" | "unavailable" = "unknown";
const waiters: ((available: boolean) => void)[] = [];

function useMonacoAvailability(): boolean | null {
  const [available, setAvailable] = useState<boolean | null>(
    monacoState === "unknown" ? null : monacoState === "ready",
  );

  useEffect(() => {
    if (monacoState !== "unknown") {
      setAvailable(monacoState === "ready");
      return;
    }
    waiters.push(setAvailable);
    void loader
      .init()
      .then(() => {
        monacoState = "ready";
        waiters.forEach((notify) => notify(true));
      })
      .catch(() => {
        monacoState = "unavailable";
        waiters.forEach((notify) => notify(false));
      });
  }, []);

  return available;
}

export function CodeViewer({
  value,
  language = "plaintext",
  height = "60vh",
  readOnly = true,
  onChange,
}: {
  value: string;
  language?: string;
  height?: string;
  readOnly?: boolean;
  onChange?: (value: string) => void;
}) {
  const available = useMonacoAvailability();

  if (available === false) {
    return (
      <div>
        <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-800 ring-1 ring-amber-200">
          The code editor could not be loaded (no access to the editor assets). Showing a
          read-only view instead.
        </p>
        <pre
          className="overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-800"
          style={{ maxHeight: height }}
        >
          {value || "(empty file)"}
        </pre>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      {available === null ? (
        <pre
          className="overflow-auto bg-slate-50 p-3 font-mono text-[11px] leading-relaxed text-slate-700"
          style={{ height }}
        >
          {value || "(empty file)"}
        </pre>
      ) : (
        <Editor
          height={height}
          language={language}
          value={value}
          onChange={(next) => onChange?.(next ?? "")}
          theme="vs"
          options={{
            readOnly,
            minimap: { enabled: false },
            fontSize: 12.5,
            scrollBeyondLastLine: false,
            wordWrap: "on",
            renderWhitespace: "selection",
            automaticLayout: true,
          }}
        />
      )}
    </div>
  );
}
