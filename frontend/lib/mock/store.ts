import type {
  Agent,
  AgentQuotaStatus,
  AgentVersion,
  Attachment,
  Message,
  RegressionExecution,
  RegressionExecutionResults,
  Run,
  RunAuditEvent,
  RunEvent,
  Thread,
  ThreadMessage,
} from "@/lib/types";
import { nextId, resetIdSeq } from "./ids";
import {
  MOCK_TENANT_ID,
  buildSeedAgents,
  buildSeedAudit,
  buildSeedQuotas,
  buildSeedRegressions,
  buildSeedRuns,
  buildSeedThreadMessages,
  buildSeedThreads,
  buildSeedVersions,
} from "./seed";

export type MockStore = {
  agents: Agent[];
  quotas: Record<string, AgentQuotaStatus>;
  versions: Record<string, AgentVersion[]>;
  threads: Thread[];
  threadMessages: Record<string, ThreadMessage[]>;
  runs: Run[];
  audit: Record<string, RunAuditEvent[]>;
  attachments: Record<string, Attachment>;
  executions: Record<string, RegressionExecution>;
  results: Record<string, RegressionExecutionResults>;
  /** Buffered SSE events per run (newest appended). */
  events: Record<string, RunEvent[]>;
  /** Runs that should animate when an SSE client connects. */
  pendingSimulations: Set<string>;
};

type GlobalMock = typeof globalThis & {
  __agentflowMockStore?: MockStore;
};

function createStore(): MockStore {
  resetIdSeq();
  const seeded = buildSeedRegressions();
  return {
    agents: buildSeedAgents(),
    quotas: buildSeedQuotas(),
    versions: buildSeedVersions(),
    threads: buildSeedThreads(),
    threadMessages: buildSeedThreadMessages(),
    runs: buildSeedRuns(),
    audit: buildSeedAudit(),
    attachments: {},
    executions: seeded.executions,
    results: seeded.results,
    events: {},
    pendingSimulations: new Set(),
  };
}

export function getMockStore(): MockStore {
  const g = globalThis as GlobalMock;
  if (!g.__agentflowMockStore) {
    g.__agentflowMockStore = createStore();
  }
  return g.__agentflowMockStore;
}

export function resetMockStore(): MockStore {
  const g = globalThis as GlobalMock;
  g.__agentflowMockStore = createStore();
  return g.__agentflowMockStore;
}

export function nowIso(): string {
  return new Date().toISOString();
}

export function cloneRun(run: Run): Run {
  return structuredClone(run);
}

export function findAgent(store: MockStore, id: string): Agent | undefined {
  return store.agents.find((a) => a.id === id);
}

export function findRun(store: MockStore, id: string): Run | undefined {
  return store.runs.find((r) => r.id === id);
}

export function findThread(store: MockStore, id: string): Thread | undefined {
  return store.threads.find((t) => t.id === id);
}

export function upsertRun(store: MockStore, run: Run): void {
  const idx = store.runs.findIndex((r) => r.id === run.id);
  if (idx === -1) {
    store.runs.unshift(run);
  } else {
    store.runs[idx] = run;
  }
}

export function appendAudit(
  store: MockStore,
  runId: string,
  action: "cancel" | "resume",
  detail: Record<string, unknown> = {},
): void {
  const list = store.audit[runId] ?? [];
  list.push({
    id: nextId("aud"),
    tenant_id: MOCK_TENANT_ID,
    run_id: runId,
    action,
    actor_subject: "demo-operator",
    actor_role: "admin",
    detail,
    created_at: nowIso(),
  });
  store.audit[runId] = list;
}

export function appendEvent(store: MockStore, event: RunEvent): void {
  const list = store.events[event.run_id] ?? [];
  list.push(event);
  store.events[event.run_id] = list;
}

export function defaultQuota(agentId: string): AgentQuotaStatus {
  return {
    agent_id: agentId,
    active: false,
    enforce: false,
    period: null,
    period_key: null,
    period_start: null,
    period_end: null,
    max_tokens: null,
    max_cost_usd: null,
    used_tokens: 0,
    used_tokens_in: 0,
    used_tokens_out: 0,
    used_cost_usd: 0,
    run_count: 0,
    remaining_tokens: null,
    remaining_cost_usd: null,
    exceeded: false,
  };
}

export function createEmptyRun(partial: {
  agent_id: string;
  adapter: string;
  input: Record<string, unknown>;
  thread_id?: string | null;
}): Run {
  const at = nowIso();
  const prompt =
    typeof partial.input.prompt === "string"
      ? partial.input.prompt
      : JSON.stringify(partial.input);
  return {
    id: nextId("run"),
    tenant_id: MOCK_TENANT_ID,
    agent_id: partial.agent_id,
    thread_id: partial.thread_id ?? null,
    adapter: partial.adapter,
    status: "pending",
    input: partial.input,
    output: null,
    error: null,
    created_at: at,
    updated_at: at,
    steps: [],
    messages: [
      {
        id: nextId("msg"),
        index: 0,
        step_id: null,
        role: "user",
        name: null,
        content: prompt,
        tool_call_id: null,
        extra: {},
        created_at: at,
      },
    ],
    messages_truncated: false,
    checkpoints: [],
    usage: {
      tokens_in: 0,
      tokens_out: 0,
      cost_usd: 0,
      latency_ms: null,
      step_count: 0,
      failed_step_count: 0,
      tool_call_count: 0,
      failed_tool_call_count: 0,
    },
  };
}

export function summarizeRun(run: Run): Run {
  // List endpoints typically return full runs in this console; keep messages.
  return cloneRun(run);
}

export type { Message };
