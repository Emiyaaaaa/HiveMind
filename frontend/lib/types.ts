export type RunStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "waiting_human";

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  latency_ms: number | null;
}

export interface Step {
  id: string;
  index: number;
  node: string;
  status: RunStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  tool_calls: ToolCall[];
  created_at: string;
  updated_at: string;
}

export interface RunUsage {
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number | null;
  step_count: number;
  failed_step_count: number;
  tool_call_count: number;
  failed_tool_call_count: number;
}

export interface Message {
  id: string;
  index: number;
  step_id: string | null;
  role: "system" | "user" | "assistant" | "tool";
  name: string | null;
  content: string;
  tool_call_id: string | null;
  extra: Record<string, unknown>;
  created_at: string;
}

export interface MessagePage {
  items: Message[];
  next_cursor: number | null;
  has_more: boolean;
}

export interface Attachment {
  id: string;
  tenant_id: string;
  run_id: string | null;
  message_id: string | null;
  media_type: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  caption: string | null;
  url: string;
  created_at: string;
  updated_at: string;
}

export interface Checkpoint {
  id: string;
  index: number;
  label: string | null;
  created_at: string;
}

export interface RunAuditEvent {
  id: string;
  tenant_id: string;
  run_id: string;
  action: "cancel" | "resume";
  actor_subject: string;
  actor_role: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface Run {
  id: string;
  tenant_id: string;
  agent_id: string;
  thread_id?: string | null;
  adapter: string;
  status: RunStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  steps: Step[];
  messages: Message[];
  messages_truncated?: boolean;
  checkpoints: Checkpoint[];
  usage: RunUsage;
}

export interface Thread {
  id: string;
  tenant_id: string;
  project_id: string | null;
  agent_id: string;
  user_id: string | null;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThreadMessage extends Message {
  run_id: string;
}

export interface ThreadMessagePage {
  items: ThreadMessage[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  adapter: string;
  config: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface AgentQuotaStatus {
  agent_id: string;
  active: boolean;
  enforce: boolean;
  period: "day" | "week" | "month" | null;
  period_key: string | null;
  period_start: string | null;
  period_end: string | null;
  max_tokens: number | null;
  max_cost_usd: number | null;
  used_tokens: number;
  used_tokens_in: number;
  used_tokens_out: number;
  used_cost_usd: number;
  run_count: number;
  remaining_tokens: number | null;
  remaining_cost_usd: number | null;
  exceeded: boolean;
}

export interface AgentVersion {
  id: string;
  agent_id: string;
  version: number;
  description: string | null;
  adapter: string;
  config: Record<string, unknown>;
  note: string | null;
  created_at: string;
}

export interface AgentVersionDiff {
  from_version: number;
  to_version: number;
  adapter: { from: string; to: string } | null;
  description: { from: string | null; to: string | null } | null;
  config: {
    added: Record<string, unknown>;
    removed: Record<string, unknown>;
    changed: Record<string, { from: unknown; to: unknown }>;
  };
}

export interface RunEvent {
  type: string;
  run_id: string;
  at: string;
  data: Record<string, unknown>;
}

export interface RunComparisonSide {
  run_id: string;
  agent_id: string;
  agent_version: number | null;
  status: string;
  error: string | null;
}

export interface RunComparison {
  baseline: RunComparisonSide;
  candidate: RunComparisonSide;
  agent_version_changed: boolean;
  status_changed: boolean;
  error_changed: boolean;
  input_changed: boolean;
  output_changed: boolean;
}

export interface RegressionRunPair {
  baseline_run_id: string;
  candidate_run_id: string;
}

export interface RegressionExecution {
  execution_id: string;
  candidate_agent_version: number;
  status: "pending" | "running" | "completed";
  total_cases: number;
  completed_cases: number;
  cases: RegressionRunPair[];
}

export interface RegressionFailure {
  code: string;
  message: string;
}

export interface RegressionCaseResult {
  baseline_run_id: string;
  candidate_run_id: string;
  passed: boolean;
  failures: RegressionFailure[];
}

export interface RegressionExecutionResults {
  execution_id: string;
  passed: boolean;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  cases: RegressionCaseResult[];
}
