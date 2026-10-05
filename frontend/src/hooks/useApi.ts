import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../services/api";

interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
  setData: (value: T | null) => void;
}

/** Fetch-on-mount helper with polling support (used for live workflow status). */
export function useApi<T>(
  loader: () => Promise<T>,
  deps: unknown[] = [],
  options: { pollMs?: number; enabled?: boolean } = {},
): AsyncState<T> {
  const { pollMs = 0, enabled = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState("");
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    if (!enabled) return;
    try {
      const value = await loaderRef.current();
      setData(value);
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void reload();
    if (!pollMs || !enabled) return;
    const timer = window.setInterval(() => void reload(), pollMs);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs, enabled, reload]);

  return { data, loading, error, reload, setData };
}

/** Human-readable label for any status string the API returns. */
export function statusLabel(status: string): string {
  return (status || "UNKNOWN")
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function statusTone(status: string): string {
  switch ((status || "").toUpperCase()) {
    case "COMPLETED":
    case "APPROVED":
    case "PASSED":
    case "SUCCEEDED":
    case "FIXED":
    case "IDLE":
      return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
    case "RUNNING":
    case "IN_PROGRESS":
    case "IN_REVIEW":
      return "bg-forge-50 text-forge-700 ring-1 ring-forge-200";
    case "AWAITING_APPROVAL":
    case "PENDING":
    case "TODO":
    case "ACKNOWLEDGED":
      return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
    case "FAILED":
    case "REJECTED":
    case "ERROR":
    case "OPEN":
    case "CRITICAL":
    case "HIGH":
      return "bg-rose-50 text-rose-700 ring-1 ring-rose-200";
    case "CHANGES_REQUESTED":
      return "bg-orange-50 text-orange-700 ring-1 ring-orange-200";
    case "PAUSED":
    case "FALSE_POSITIVE":
      return "bg-slate-100 text-slate-600 ring-1 ring-slate-200";
    case "MEDIUM":
      return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
    case "LOW":
    case "INFO":
      return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
    default:
      return "bg-slate-100 text-slate-600 ring-1 ring-slate-200";
  }
}

export function formatDuration(ms: number): string {
  if (!ms) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  return date.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value.endsWith("Z") || value.includes("+") ? value : `${value}Z`);
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86_400)} d ago`;
}
