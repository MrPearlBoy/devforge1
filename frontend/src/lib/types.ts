export interface FileNode {
  path: string;
  size: number;
  type: string;
}

export interface StreamEvent {
  type: string;
  stage?: string | null;
  message: string;
  payload?: Record<string, unknown> | null;
  ts?: string | null;
  project_id?: string;
}

export interface Endpoint {
  method: string;
  path: string;
  description: string;
  request_body?: string;
  response?: string;
}

export interface ModuleDesign {
  name: string;
  responsibility: string;
  files: string[];
}

export interface RequirementSpec {
  project_name: string;
  overview: string;
  functional_requirements: string[];
  user_stories: { id: string; title: string; story: string; acceptance_criteria: string[] }[];
  non_functional_requirements: string[];
  out_of_scope: string[];
}

export interface ArchitectureSpec {
  summary: string;
  tech_stack: Record<string, string>;
  directory_structure: string;
  api_endpoints: Endpoint[];
  modules: ModuleDesign[];
  data_model: string;
}

export interface CodeArtifact {
  summary: string;
  files: { path: string; description: string; size: number }[];
  run_instructions: string;
}

export interface TestReport {
  passed: boolean;
  total: number;
  passed_count: number;
  failed_count: number;
  exit_code: number;
  duration_s: number;
  summary: string;
  failures: string[];
  output?: string;
}

export interface SecurityReport {
  clean: boolean;
  tool: string;
  findings: { severity: string; category: string; message: string; file?: string; line?: number | null }[];
}

export interface DocsArtifact {
  readme: string;
  api_documentation: string;
  architecture_summary: string;
}

export interface GitInfo {
  committed: boolean;
  hash?: string | null;
  branch?: string;
  files?: number;
  commit_message?: string;
  reason?: string;
}

export interface TestRun {
  run_number: number;
  passed: boolean;
  failed: number;
  total: number;
  summary: string;
  duration_s: number;
  ts: string | null;
}

export interface ProjectSnapshot {
  id: string;
  name: string;
  task: string;
  stage: string;
  status: string;
  awaiting_gate: string | null;
  llm_provider: string;
  error: string | null;
  created_at: string | null;
  iterations: Record<string, number>;
  artifacts: {
    requirement?: RequirementSpec;
    architecture?: ArchitectureSpec;
    code?: CodeArtifact;
    tests?: TestReport;
    security?: SecurityReport;
    docs?: DocsArtifact;
    git?: GitInfo;
  };
  files: FileNode[];
  events: StreamEvent[];
  test_runs: TestRun[];
}

export type Role = "developer" | "architect" | "tester" | "pm";
export type TabKey = "code" | "specs" | "tests" | "security" | "docs" | "audit";
