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
  /** Continue a conversation: the worker seeds the adapter with the thread's recent turns. */
  thread_id?: string | null;
}

export interface RunRetryRequest {
  /** Older checkpoint to resume from; latest when omitted. */
  checkpoint_index?: number;
}

export interface RunResumeRequest {
  /** Merged into the run's persisted input, e.g. `{ approval: "approved" }`. */
  input?: Record<string, unknown>;
}

/**
 * One page of a run or thread transcript. `next_cursor` is a number for
 * `GET /v1/runs/{id}/messages` and an opaque string for
 * `GET /v1/threads/{id}/messages`; pass it back verbatim for older messages.
 */
export interface MessagePage<TCursor = number | string> {
  items: Record<string, unknown>[];
  next_cursor: TCursor | null;
  has_more: boolean;
}

export interface Thread {
  id: string;
  tenant_id: string;
  project_id?: string | null;
  agent_id: string;
  user_id?: string | null;
  title?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ThreadCreateRequest {
  agent_id: string;
  title?: string;
  user_id?: string;
  project_id?: string;
}

/** Cancel/resume governance record from `GET /v1/runs/{id}/audit`. */
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

export interface WaitForRunOptions {
  /** Give up after this many milliseconds (default 300 000). */
  timeoutMs?: number;
  /** Delay between polls in milliseconds (default 500). */
  pollIntervalMs?: number;
  /** Statuses that end the wait (default: terminal statuses plus `waiting_human`). */
  until?: readonly RunStatus[];
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
