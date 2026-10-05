import type { ProjectSnapshot } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string; llm_provider: string }>("/health"),
  listProjects: () => request<ProjectSnapshot[]>("/projects"),
  getProject: (id: string) => request<ProjectSnapshot>(`/projects/${id}`),
  createProject: (name: string, task: string) =>
    request<ProjectSnapshot>("/projects", { method: "POST", body: JSON.stringify({ name, task }) }),
  startWorkflow: (id: string) => request<{ started: boolean; stage: string; status: string }>(`/projects/${id}/start`, { method: "POST" }),
  submitApproval: (id: string, gate: string, decision: string, comment: string) =>
    request<{ recorded: boolean }>(`/projects/${id}/approvals`, {
      method: "POST",
      body: JSON.stringify({ gate, decision, comment }),
    }),
  pendingGate: (id: string) =>
    request<{ pending: boolean; gate: string | null; title: string | null; status: string }>(
      `/projects/${id}/approvals/pending`
    ),
  listFiles: (id: string) => request<{ path: string; size: number }[]>(`/projects/${id}/files`),
  readFile: (id: string, path: string) =>
    request<{ path: string; content: string }>(`/projects/${id}/files/content?path=${encodeURIComponent(path)}`),
  retest: (id: string) => request<Record<string, unknown>>(`/projects/${id}/execution/retest`, { method: "POST" }),
  rescan: (id: string) => request<Record<string, unknown>>(`/projects/${id}/execution/rescan`, { method: "POST" }),
  logs: (id: string, limit = 300) => request<Record<string, unknown>[]>(`/projects/${id}/execution/logs?limit=${limit}`),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
};

export type StreamEvent = {
  type: string;
  stage?: string | null;
  message: string;
  payload?: Record<string, unknown> | null;
  ts?: string | null;
  project_id?: string;
};

/**
 * Live workflow event stream (Server-Sent Events).
 * Events are JSON frames: data: {"type": ..., "message": ..., "payload": {...}}
 */
export class WorkflowStream {
  private es: EventSource | null = null;
  private projectId: string;
  private onEvent: (e: StreamEvent) => void;

  constructor(projectId: string, onEvent: (e: StreamEvent) => void) {
    this.projectId = projectId;
    this.onEvent = onEvent;
  }

  connect() {
    this.disconnect();
    const es = new EventSource(`/api/projects/${this.projectId}/events`);
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as StreamEvent;
        if (data.type) this.onEvent(data);
      } catch {
        /* ignore malformed keep-alive frames */
      }
    };
    es.onerror = () => {
      /* EventSource reconnects automatically (retry: 3000 from server) */
    };
    this.es = es;
  }

  disconnect() {
    this.es?.close();
    this.es = null;
  }
}
