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
  tool_calls: ToolCall[];
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  index: number;
  role: "system" | "user" | "assistant" | "tool";
  name: string | null;
  content: string;
  tool_call_id: string | null;
  extra: Record<string, unknown>;
  created_at: string;
}

export interface Checkpoint {
  id: string;
  index: number;
  label: string | null;
  created_at: string;
}

export interface Run {
  id: string;
  agent_id: string;
  adapter: string;
  status: RunStatus;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  steps: Step[];
  messages: Message[];
  checkpoints: Checkpoint[];
}

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  adapter: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RunEvent {
  type: string;
  run_id: string;
  at: string;
  data: Record<string, unknown>;
}
