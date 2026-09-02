export type RunStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "waiting_human";

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

export interface Run {
  id: string;
  tenant_id: string;
  project_id?: string | null;
  agent_id: string;
  adapter: string;
  status: RunStatus;
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  steps: Record<string, unknown>[];
  messages: Record<string, unknown>[];
  messages_truncated?: boolean;
  checkpoints: Record<string, unknown>[];
  usage: RunUsage;
}

export interface RunCreateRequest {
  agent_id: string;
  input?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  adapter?: string | null;
}

export interface RunEvent {
  type: string;
  run_id: string;
  at: string;
  data: Record<string, unknown>;
}

export interface AgentFlowClientOptions {
  baseUrl?: string;
  apiKey?: string;
  fetch?: typeof fetch;
}

export interface SubscribeRunEventsOptions {
  apiKey?: string;
  lastEventId?: string | null;
  fetch?: typeof fetch;
  onEvent?: (event: RunEvent, eventId?: string) => void;
}

export interface RunEventSubscription {
  close: () => void;
}
