/** Types mirroring the FastAPI contracts in `backend/app/schemas`. */

export type StageKey =
  | "REQUIREMENTS"
  | "ARCHITECTURE"
  | "DEVELOPMENT"
  | "TESTING"
  | "SECURITY"
  | "DOCUMENTATION"
  | "DELIVERY";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  slug: string;
  requirement_input: string;
  current_stage: StageKey;
  workflow_status: string;
  stage_status: string;
  progress_percent: number;
  tech_stack: string;
  tags: string[];
  workspace_path: string;
  owner_id: string;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProjectSummary extends Project {
  owner_name: string;
  active_run_id: string | null;
  pending_approvals: number;
  open_findings: number;
  last_test_status: string | null;
  github_connected: boolean;
}

export interface StageProgress {
  stage: StageKey;
  label: string;
  status: string;
  order: number;
  artifact_id: string | null;
  artifact_title: string;
  approval_id: string | null;
  approval_status: string | null;
}

export interface AgentActivity {
  agent_key: string;
  name: string;
  role: string;
  stage: string;
  status: string;
  execution_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  summary: string;
  error: string;
  mode: string;
  model: string;
}

export interface ArtifactSummary {
  id: string;
  project_id: string;
  type: string;
  stage: StageKey;
  title: string;
  summary: string;
  path: string;
  version: number;
  status: string;
  produced_by_agent_key: string | null;
  trace_refs: string[];
  created_at: string;
  updated_at: string;
}

export interface Artifact extends ArtifactSummary {
  content: string;
  data: Record<string, unknown>;
  run_id: string | null;
}

export interface Approval {
  id: string;
  project_id: string;
  run_id: string | null;
  artifact_id: string | null;
  stage: StageKey;
  gate: string;
  status: string;
  requested_by_agent_key: string | null;
  requested_at: string | null;
  decided_by_user_id: string | null;
  decided_at: string | null;
  comments: string;
  decision_meta: Record<string, unknown>;
  created_at: string;
  artifact_title: string;
  artifact_type: string;
  artifact_preview: string;
  requested_by_user_name: string;
  decided_by_user_name: string;
}

export interface WorkflowRun {
  id: string;
  project_id: string;
  run_number: number;
  status: string;
  engine: string;
  thread_id: string;
  current_stage: StageKey;
  current_node: string;
  awaiting_approval: boolean;
  pending_approval_id: string | null;
  stage_iterations: Record<string, number>;
  total_steps: number;
  max_stage_iterations: number;
  started_at: string | null;
  finished_at: string | null;
  last_error: string;
  created_at: string;
}

export interface WorkflowOverview {
  run: WorkflowRun | null;
  project_status: string;
  current_stage: StageKey;
  stages: StageProgress[];
  pending_approval: Approval | null;
  can_resume: boolean;
  iteration_budget: { max_stage_iterations: number; used: Record<string, number> };
}

export interface WorkflowStep {
  id: string;
  run_id: string;
  step_index: number;
  node: string;
  stage: string;
  status: string;
  summary: string;
  state: Record<string, unknown>;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  project_id: string | null;
  user_id: string | null;
  actor_type: string;
  actor_label: string;
  action: string;
  entity_type: string;
  entity_id: string;
  stage: string;
  summary: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface ActivityEntry {
  id: string;
  action: string;
  label: string;
  actor_type: string;
  actor_label: string;
  stage: string;
  summary: string;
  detail: Record<string, unknown>;
  entity_type: string;
  entity_id: string;
  created_at: string;
}

export interface TestResult {
  id: string;
  test_run_id: string;
  name: string;
  file_path: string;
  status: string;
  duration_ms: number;
  message: string;
  requirement_refs: string[];
}

export interface TestRun {
  id: string;
  project_id: string;
  run_id: string | null;
  artifact_id: string | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  command: string;
  provider: string;
  duration_ms: number;
  triggered_by: string;
  confirmed_by_user: boolean;
  report: Record<string, unknown>;
  created_at: string;
  results?: TestResult[];
  raw_output?: string;
}

export interface SecurityFinding {
  id: string;
  project_id: string;
  run_id: string | null;
  scan_id: string;
  rule_id: string;
  severity: string;
  category: string;
  title: string;
  description: string;
  file_path: string;
  line: number | null;
  evidence: string;
  recommendation: string;
  status: string;
  detected_by: string;
  trace_refs: string[];
  created_at: string;
}

export interface SecuritySummary {
  scan_id: string;
  artifact_id: string | null;
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
  open_total: number;
  files_scanned: number;
  created_at: string | null;
  disclaimer: string;
}

export interface TraceNode {
  ref: string;
  type: string;
  label: string;
  artifact_id: string | null;
}

export interface TraceLink {
  id: string;
  source_type: string;
  source_ref: string;
  source_label: string;
  target_type: string;
  target_ref: string;
  target_label: string;
  relation: string;
  confidence: number;
  note: string;
}

export interface TraceMatrix {
  nodes: TraceNode[];
  links: TraceLink[];
  coverage: Record<string, number> & { percent?: Record<string, number> };
  gap_report: string[];
}

export interface WorkspaceFile {
  path: string;
  size: number;
  language: string;
  modified_at: string | null;
  artifact_id: string | null;
}

export interface WorkspaceTree {
  root: string;
  groups: Record<string, WorkspaceFile[]>;
  total_files: number;
}

export interface WorkspaceFileContent {
  path: string;
  content: string;
  size: number;
  language: string;
  truncated: boolean;
}

export interface ChatMessage {
  id: string;
  project_id: string;
  agent_key: string | null;
  thread_id: string;
  role: string;
  content: string;
  user_id: string | null;
  execution_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface ProposedChange {
  path: string;
  op: string;
  description: string;
  diff: string;
  content: string;
  language: string;
  additions: number;
  deletions: number;
}

export interface ChatReply {
  message_id: string;
  agent_key: string;
  content: string;
  created_at: string;
  execution_id: string | null;
  mode: string;
  model: string;
  proposed_changes: ProposedChange[];
  approval_id: string | null;
  references: string[];
}

export interface AgentSpec {
  key: string;
  name: string;
  role: string;
  stage: StageKey;
  description: string;
  icon: string;
  order_index: number;
  capabilities: string[];
  output_artifact_types: string[];
}

export interface RepositoryStatus {
  connected: boolean;
  repository: {
    id: string;
    url: string;
    owner: string;
    name: string;
    default_branch: string;
    working_branch: string;
    auth_configured: boolean;
    token_hint: string;
    status: string;
    last_synced_at: string | null;
    last_commit_sha: string;
    provider: string;
  } | null;
  branch: string;
  is_clean?: boolean;
  changes: { path: string; status: string; staged: boolean }[];
  staged_count: number;
  untracked_count: number;
  ahead: number;
  behind: number;
  remote_url: string;
  last_operation: Record<string, unknown> | null;
  requires_confirmation: boolean;
  message: string;
}

export interface SyncPlan {
  branch: string;
  base_branch: string;
  commit_message: string;
  files: { path: string; status: string; staged: boolean }[];
  summary: string;
  requires_confirmation: boolean;
}

export interface DeliveryReadiness {
  ready: boolean;
  checklist: { item: string; done: boolean; detail?: string }[];
  completed_stages: string[];
  repository: Record<string, unknown> | null;
  branch: string;
  changed_files: number;
  pending_approval: Record<string, unknown> | null;
  requires_confirmation: boolean;
  message: string;
}

export interface GitOperation {
  id: string;
  operation: string;
  status: string;
  branch: string;
  commit_sha: string;
  message: string;
  confirmed_by_user: boolean;
  detail: Record<string, unknown>;
  error: string;
  created_at: string;
}

export interface PlatformConfig {
  mode: string;
  provider: string;
  model: string;
  execution_provider: string;
  execution_enabled: boolean;
  github_configured: boolean;
  vector_backend: string;
  max_stage_iterations: number;
}

export interface Dashboard {
  project: Project;
  stages: StageProgress[];
  active_run: WorkflowRun | null;
  pending_approval: Approval | null;
  approvals: Approval[];
  agent_activity: AgentActivity[];
  recent_activity: ActivityEntry[];
  artifacts: ArtifactSummary[];
  latest_test_run: TestRun | null;
  security_summary: SecuritySummary | Record<string, never>;
  repository: Record<string, unknown> | null;
  ai_config: PlatformConfig & { error?: string };
}
