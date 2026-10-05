/**
 * Thin typed API client.
 *
 * Uses the Vite same-origin proxy locally, and the configured FastAPI origin in production.
 * The JWT is attached from local storage and never logged.
 */
import type {
  AgentSpec,
  Approval,
  Artifact,
  ArtifactSummary,
  AuditEntry,
  ChatMessage,
  ChatReply,
  Dashboard,
  DeliveryReadiness,
  GitOperation,
  PlatformConfig,
  Project,
  ProjectSummary,
  RepositoryStatus,
  SecurityFinding,
  SecuritySummary,
  SyncPlan,
  TestRun,
  TokenResponse,
  TraceMatrix,
  User,
  WorkflowOverview,
  WorkflowRun,
  WorkflowStep,
  WorkspaceFileContent,
  WorkspaceTree,
} from "../types/api";

/**
 * Optional production API origin. Local development keeps using the Vite proxy;
 * Vercel builds set this to the deployed FastAPI origin (without a trailing slash).
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").trim().replace(/\/+$/, "");
export const isBackendApiConfigured = !import.meta.env.PROD || Boolean(API_BASE_URL);

const TOKEN_KEY = "devforge.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  code: string;
  detail: Record<string, unknown>;

  constructor(status: number, message: string, code = "error", detail = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { query?: Record<string, string | number | boolean | undefined> } = {},
): Promise<T> {
  const { query, ...init } = options;
  if (import.meta.env.PROD && !API_BASE_URL) {
    throw new ApiError(
      503,
      "This production build has no backend API configured. Set VITE_API_BASE_URL and redeploy.",
      "api_not_configured",
    );
  }
  const url = new URL(`${API_BASE_URL}${path}`, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
  }

  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  const response = await fetch(url.toString(), { ...init, headers });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (!response.ok) {
    const error = (payload as { error?: { message?: string; code?: string; detail?: Record<string, unknown> } })?.error;
    const message =
      error?.message ||
      (typeof payload === "string" ? payload : `Request failed (${response.status})`);
    throw new ApiError(response.status, message, error?.code || "error", error?.detail || {});
  }
  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const json = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  // ---------------------------------------------------------------- platform
  health: () => request<Record<string, unknown>>("/api/health"),
  config: () => request<PlatformConfig>("/api/config"),

  // -------------------------------------------------------------------- auth
  register: (body: { email: string; password: string; full_name?: string }) =>
    request<TokenResponse>("/api/auth/register", json(body)),
  login: (body: { email: string; password: string }) =>
    request<TokenResponse>("/api/auth/login", json(body)),
  me: () => request<User>("/api/auth/me"),

  // ---------------------------------------------------------------- projects
  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (body: {
    name: string;
    description?: string;
    requirement_input: string;
    tech_stack?: string;
    tags?: string[];
  }) => request<Project>("/api/projects", json(body)),
  updateProject: (id: string, body: Partial<Project>) =>
    request<Project>(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteProject: (id: string) =>
    request<{ detail: string }>(`/api/projects/${id}`, { method: "DELETE" }),
  dashboard: (id: string) => request<Dashboard>(`/api/projects/${id}/dashboard`),

  // ---------------------------------------------------------------- workflow
  workflowOverview: (id: string) => request<WorkflowOverview>(`/api/projects/${id}/workflow`),
  startWorkflow: (id: string, instructions = "", restart = false) =>
    request<WorkflowRun>(`/api/projects/${id}/workflow/start`, json({ instructions, restart })),
  resumeWorkflow: (id: string, comments = "") =>
    request<WorkflowRun>(`/api/projects/${id}/workflow/resume`, json({ comments })),
  workflowRuns: (id: string) => request<WorkflowRun[]>(`/api/projects/${id}/workflow/runs`),
  workflowSteps: (id: string, runId: string) =>
    request<WorkflowStep[]>(`/api/projects/${id}/workflow/runs/${runId}/steps`),

  // ---------------------------------------------------------------- approvals
  approvals: (id: string) => request<Approval[]>(`/api/projects/${id}/approvals`),
  pendingApprovals: (id: string) => request<Approval[]>(`/api/projects/${id}/approvals/pending`),
  approve: (approvalId: string, body: { comments?: string; instructions?: string; edited_content?: string }) =>
    request<Approval>(`/api/approvals/${approvalId}/approve`, json(body)),
  reject: (approvalId: string, body: { comments?: string; instructions?: string }) =>
    request<Approval>(`/api/approvals/${approvalId}/reject`, json(body)),
  requestChanges: (approvalId: string, body: { comments: string; instructions?: string }) =>
    request<Approval>(`/api/approvals/${approvalId}/changes`, json(body)),

  // ---------------------------------------------------------------- artifacts
  artifacts: (id: string, stage?: string) =>
    request<ArtifactSummary[]>(`/api/projects/${id}/artifacts`, { query: { stage } }),
  artifact: (artifactId: string) => request<Artifact>(`/api/artifacts/${artifactId}`),
  saveArtifact: (artifactId: string, body: { content?: string; title?: string; change_reason?: string }) =>
    request<Artifact>(`/api/artifacts/${artifactId}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),

  // ----------------------------------------------------------------- agents
  agents: () => request<AgentSpec[]>("/api/agents/specs"),
  agentStatus: (id: string) =>
    request<
      {
        agent_key: string;
        name: string;
        stage: string;
        status: string;
        execution_id: string | null;
        started_at: string | null;
        finished_at: string | null;
        duration_ms: number;
        result: string;
        error: string;
        mode: string;
        model: string;
        total_tokens: number;
      }[]
    >(`/api/projects/${id}/agents/status`),
  executions: (id: string, limit = 50) =>
    request<
      {
        id: string;
        agent_key: string;
        stage: string;
        trigger: string;
        status: string;
        mode: string;
        provider: string;
        llm_model: string;
        duration_ms: number;
        input_summary: string;
        output_summary: string;
        error: string;
        created_at: string;
      }[]
    >(`/api/projects/${id}/executions`, { query: { limit } }),

  // ------------------------------------------------------------------- chat
  chat: (id: string, body: { message: string; agent_key?: string; thread_id?: string; allow_code_proposals?: boolean }) =>
    request<ChatReply>(`/api/projects/${id}/chat`, json(body)),
  chatHistory: (id: string, threadId = "default") =>
    request<ChatMessage[]>(`/api/projects/${id}/chat`, { query: { thread_id: threadId } }),
  chatThreads: (id: string) =>
    request<{ thread_id: string; agent_key: string | null; message_count: number; last_message_at: string; last_preview: string }[]>(
      `/api/projects/${id}/chat/threads`,
    ),

  // -------------------------------------------------------------- workspace
  workspace: (id: string) => request<WorkspaceTree>(`/api/projects/${id}/workspace`),
  workspaceFile: (id: string, path: string) =>
    request<WorkspaceFileContent>(`/api/projects/${id}/workspace/file`, { query: { path } }),

  // ------------------------------------------------------------------ tests
  testRuns: (id: string) => request<TestRun[]>(`/api/projects/${id}/tests`),
  latestTestRun: (id: string) => request<TestRun | null>(`/api/projects/${id}/tests/latest`),
  testRun: (testRunId: string) => request<TestRun>(`/api/tests/${testRunId}`),
  runTests: (id: string, target = "") =>
    request<TestRun>(`/api/projects/${id}/tests/run`, json({ target, confirm_execution: true })),
  runTestingAgent: (id: string) =>
    request<TestRun>(`/api/projects/${id}/tests/agent`, json({ confirm_execution: true })),

  // --------------------------------------------------------------- security
  securitySummary: (id: string) => request<SecuritySummary>(`/api/projects/${id}/security/summary`),
  findings: (id: string, filters: { finding_status?: string; severity?: string } = {}) =>
    request<SecurityFinding[]>(`/api/projects/${id}/security/findings`, { query: filters }),
  triageFinding: (findingId: string, body: { status: string; comment?: string }) =>
    request<SecurityFinding>(`/api/security/findings/${findingId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  runSecurityScan: (id: string) =>
    request<SecuritySummary>(`/api/projects/${id}/security/scan`, json({ include_ai_review: true })),
  remediate: (id: string, findingId: string) =>
    request<{ execution_id: string; approval_id: string; summary: string; proposed_files: string[] }>(
      `/api/projects/${id}/security/findings/${findingId}/remediate`,
      { method: "POST" },
    ),
  sandbox: (id: string) =>
    request<{
      provider: string;
      available: boolean;
      isolation: string;
      limits: Record<string, number>;
      allowed_commands: string[];
      working_directory: string;
      note: string;
    }>(`/api/projects/${id}/sandbox`),

  // ------------------------------------------------------------------ trace
  trace: (id: string) => request<TraceMatrix>(`/api/projects/${id}/trace`),
  traceChain: (id: string, ref: string) =>
    request<{ root: { ref: string; type: string; label: string }; links: TraceMatrix["links"]; nodes: TraceMatrix["nodes"] }>(
      `/api/projects/${id}/trace/ref/${encodeURIComponent(ref)}`,
    ),

  // --------------------------------------------------------------- activity
  activity: (id: string, limit = 100) =>
    request<AuditEntry[]>(`/api/projects/${id}/activity`, { query: { limit } }),
  activitySummary: (id: string) =>
    request<{ total: number; by_action: Record<string, number>; labels: Record<string, string> }>(
      `/api/projects/${id}/activity/summary`,
    ),

  // ----------------------------------------------------------------- github
  repository: (id: string) => request<RepositoryStatus>(`/api/projects/${id}/repository`),
  connectRepository: (id: string, body: { url: string; token?: string; default_branch?: string; clone?: boolean }) =>
    request<Record<string, unknown>>(`/api/projects/${id}/repository`, json(body)),
  disconnectRepository: (id: string) =>
    request<{ detail: string }>(`/api/projects/${id}/repository`, { method: "DELETE" }),
  initRepository: (id: string) =>
    request<Record<string, unknown>>(`/api/projects/${id}/repository/init`, { method: "POST" }),
  syncPlan: (id: string, message = "") =>
    request<SyncPlan>(`/api/projects/${id}/repository/plan`, { query: { message } }),
  commit: (id: string, body: { message: string; paths?: string[]; confirm: true }) =>
    request<{ sha: string; branch: string; files: number }>(
      `/api/projects/${id}/repository/commit`,
      json(body),
    ),
  push: (id: string, body: { branch?: string; confirm: true; create_pull_request?: boolean; pr_title?: string }) =>
    request<Record<string, unknown>>(`/api/projects/${id}/repository/push`, json(body)),
  gitOperations: (id: string) => request<GitOperation[]>(`/api/projects/${id}/repository/operations`),
  commits: (id: string) =>
    request<{ sha: string; message: string; author: string; date: string }[]>(
      `/api/projects/${id}/repository/commits`,
    ),
  delivery: (id: string) => request<DeliveryReadiness>(`/api/projects/${id}/repository/delivery`),

  // ----------------------------------------------------------------- events
  eventStreamUrl: (id: string) =>
    `/api/projects/${id}/events${getToken() ? `?token=${encodeURIComponent(getToken() as string)}` : ""}`,
  recentEvents: (id: string) =>
    request<{ type: string; timestamp: string; payload: Record<string, unknown> }[]>(
      `/api/projects/${id}/events/recent`,
    ),
};

export type Api = typeof api;
