import type { Checkpoint, Message, Run, RunEvent, RunStatus, RunUsage, Step, ToolCall } from "./types";

export const RUN_EVENT_TYPES = [
  "run.created",
  "run.started",
  "run.completed",
  "run.failed",
  "run.cancelled",
  "run.waiting_human",
  "step.started",
  "step.updated",
  "step.completed",
  "step.failed",
  "token.delta",
  "message.created",
  "tool_call.started",
  "tool_call.completed",
  "checkpoint.created",
  "log",
] as const;

export const TERMINAL_RUN_EVENTS = new Set([
  "run.completed",
  "run.failed",
  "run.cancelled",
]);

const LIVE_RUN_STATUSES = new Set<RunStatus>(["pending", "running"]);

export function isLiveRunStatus(status: RunStatus): boolean {
  return LIVE_RUN_STATUSES.has(status);
}

export function isTerminalRunEvent(type: string): boolean {
  return TERMINAL_RUN_EVENTS.has(type);
}

/** Events that may leave client-side placeholders out of sync with the API. */
export function shouldReconcileRun(type: string): boolean {
  return type !== "token.delta" && type !== "log";
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asOptionalRecord(value: unknown): Record<string, unknown> | null {
  if (value == null) return null;
  return asRecord(value);
}

function asUsage(value: unknown): RunUsage | null {
  const raw = asRecord(value);
  if (
    typeof raw.tokens_in !== "number" &&
    typeof raw.tokens_out !== "number" &&
    typeof raw.cost_usd !== "number"
  ) {
    return null;
  }
  return {
    tokens_in: typeof raw.tokens_in === "number" ? raw.tokens_in : 0,
    tokens_out: typeof raw.tokens_out === "number" ? raw.tokens_out : 0,
    cost_usd: typeof raw.cost_usd === "number" ? raw.cost_usd : 0,
    latency_ms: typeof raw.latency_ms === "number" ? raw.latency_ms : null,
  };
}

export function aggregateUsageFromSteps(steps: Step[]): RunUsage {
  let tokensIn = 0;
  let tokensOut = 0;
  let costUsd = 0;
  let latencyMs = 0;
  let hasLatency = false;

  for (const step of steps) {
    tokensIn += step.tokens_in ?? 0;
    tokensOut += step.tokens_out ?? 0;
    costUsd += step.cost_usd ?? 0;
    if (step.latency_ms != null) {
      latencyMs += step.latency_ms;
      hasLatency = true;
    }
  }

  return {
    tokens_in: tokensIn,
    tokens_out: tokensOut,
    cost_usd: costUsd,
    latency_ms: hasLatency ? latencyMs : null,
  };
}

function findStep(steps: Step[], index: number): Step | undefined {
  return steps.find((step) => step.index === index);
}

function upsertStep(steps: Step[], step: Step): Step[] {
  const next = steps.some((item) => item.index === step.index)
    ? steps.map((item) => (item.index === step.index ? step : item))
    : [...steps, step];
  return next.sort((a, b) => a.index - b.index);
}

function patchStep(
  steps: Step[],
  index: number,
  patch: Partial<Step>,
  at: string,
): Step[] {
  const existing = findStep(steps, index);
  if (!existing) return steps;
  return upsertStep(steps, {
    ...existing,
    ...patch,
    updated_at: at,
  });
}

function appendMessage(messages: Message[], data: Record<string, unknown>, at: string): Message[] {
  const index =
    typeof data.index === "number" ? data.index : messages.length > 0
      ? Math.max(...messages.map((message) => message.index)) + 1
      : 0;

  if (messages.some((message) => message.index === index)) {
    return messages;
  }

  const role = data.role;
  const message: Message = {
    id: `sse-msg-${index}`,
    index,
    role:
      role === "system" ||
      role === "user" ||
      role === "assistant" ||
      role === "tool"
        ? role
        : "assistant",
    name: typeof data.name === "string" ? data.name : null,
    content: typeof data.content === "string" ? data.content : "",
    tool_call_id:
      typeof data.tool_call_id === "string" ? data.tool_call_id : null,
    extra: asRecord(data.extra),
    created_at: at,
  };

  return [...messages, message].sort((a, b) => a.index - b.index);
}

function appendToolCall(step: Step, data: Record<string, unknown>): ToolCall {
  return {
    id: `sse-tc-${step.index}-${step.tool_calls.length}`,
    name: typeof data.name === "string" ? data.name : "tool",
    arguments: asRecord(data.arguments),
    result: null,
    error: null,
    latency_ms: null,
  };
}

function patchToolCall(
  step: Step,
  data: Record<string, unknown>,
  at: string,
): Step {
  const name = typeof data.name === "string" ? data.name : "";
  const toolCalls = [...step.tool_calls];
  let index = toolCalls.findIndex((call) => call.name === name);
  if (index === -1) {
    toolCalls.push(appendToolCall(step, data));
    index = toolCalls.length - 1;
  }

  toolCalls[index] = {
    ...toolCalls[index],
    result:
      "result" in data
        ? (data.result as Record<string, unknown> | null)
        : toolCalls[index].result,
    error:
      typeof data.error === "string" ? data.error : toolCalls[index].error,
    latency_ms:
      typeof data.latency_ms === "number"
        ? data.latency_ms
        : toolCalls[index].latency_ms,
  };

  return { ...step, tool_calls: toolCalls, updated_at: at };
}

function appendCheckpoint(
  checkpoints: Checkpoint[],
  data: Record<string, unknown>,
  at: string,
): Checkpoint[] {
  const index =
    typeof data.index === "number"
      ? data.index
      : checkpoints.length > 0
        ? Math.max(...checkpoints.map((cp) => cp.index)) + 1
        : 0;

  if (checkpoints.some((cp) => cp.index === index)) {
    return checkpoints;
  }

  return [
    ...checkpoints,
    {
      id: `sse-cp-${index}`,
      index,
      label: typeof data.label === "string" ? data.label : null,
      created_at: at,
    },
  ].sort((a, b) => a.index - b.index);
}

/** Apply a single SSE event to a full run snapshot for optimistic UI updates. */
export function applyRunEvent(run: Run, event: RunEvent): Run {
  const { type, data, at } = event;
  let next: Run = { ...run, updated_at: at };

  switch (type) {
    case "run.started":
      return { ...next, status: "running" };
    case "run.completed": {
      const usage = asUsage(data.usage);
      return {
        ...next,
        status: "succeeded",
        output: "output" in data ? asOptionalRecord(data.output) : run.output,
        error: null,
        usage: usage ?? next.usage,
      };
    }
    case "run.failed":
      return {
        ...next,
        status: "failed",
        error: typeof data.error === "string" ? data.error : run.error,
      };
    case "run.cancelled":
      return {
        ...next,
        status: "cancelled",
        error:
          typeof data.error === "string" ? data.error : (run.error ?? "cancelled"),
      };
    case "run.waiting_human":
      return {
        ...next,
        status: "waiting_human",
        output: "output" in data ? asOptionalRecord(data.output) : run.output,
      };
    case "step.started": {
      const index = data.index;
      if (typeof index !== "number") return next;
      const step: Step = {
        id: findStep(run.steps, index)?.id ?? `sse-step-${index}`,
        index,
        node: typeof data.node === "string" ? data.node : "",
        status: "running",
        input: asRecord(data.input),
        output: findStep(run.steps, index)?.output ?? null,
        error: findStep(run.steps, index)?.error ?? null,
        latency_ms: findStep(run.steps, index)?.latency_ms ?? null,
        tokens_in: findStep(run.steps, index)?.tokens_in ?? null,
        tokens_out: findStep(run.steps, index)?.tokens_out ?? null,
        cost_usd: findStep(run.steps, index)?.cost_usd ?? null,
        tool_calls: findStep(run.steps, index)?.tool_calls ?? [],
        created_at: findStep(run.steps, index)?.created_at ?? at,
        updated_at: at,
      };
      const steps = upsertStep(run.steps, step);
      return {
        ...next,
        steps,
        usage: aggregateUsageFromSteps(steps),
      };
    }
    case "step.updated":
    case "step.completed":
    case "step.failed": {
      const index = data.index;
      if (typeof index !== "number") return next;
      const existing = findStep(run.steps, index);
      if (!existing) return next;

      const status: RunStatus =
        type === "step.failed"
          ? "failed"
          : type === "step.completed"
            ? "succeeded"
            : existing.status;

      const steps = patchStep(run.steps, index, {
        status,
        output:
          type === "step.completed" && "output" in data
            ? asOptionalRecord(data.output)
            : existing.output,
        error:
          type === "step.failed" && typeof data.error === "string"
            ? data.error
            : existing.error,
        latency_ms:
          typeof data.latency_ms === "number"
            ? data.latency_ms
            : existing.latency_ms,
        tokens_in:
          typeof data.tokens_in === "number"
            ? data.tokens_in
            : existing.tokens_in,
        tokens_out:
          typeof data.tokens_out === "number"
            ? data.tokens_out
            : existing.tokens_out,
        cost_usd:
          typeof data.cost_usd === "number" ? data.cost_usd : existing.cost_usd,
      }, at);

      return {
        ...next,
        steps,
        usage: aggregateUsageFromSteps(steps),
      };
    }
    case "message.created":
      return {
        ...next,
        messages: appendMessage(run.messages, data, at),
      };
    case "tool_call.started": {
      const stepIndex = data.step_index;
      if (typeof stepIndex !== "number") return next;
      const step = findStep(run.steps, stepIndex);
      if (!step) return next;
      const updated = patchToolCall(step, data, at);
      return {
        ...next,
        steps: upsertStep(run.steps, updated),
      };
    }
    case "tool_call.completed": {
      const stepIndex = data.step_index;
      if (typeof stepIndex !== "number") return next;
      const step = findStep(run.steps, stepIndex);
      if (!step) return next;
      const updated = patchToolCall(step, data, at);
      return {
        ...next,
        steps: upsertStep(run.steps, updated),
      };
    }
    case "checkpoint.created":
      return {
        ...next,
        checkpoints: appendCheckpoint(run.checkpoints, data, at),
      };
    default:
      return next;
  }
}

/** Patch list rows with run-level fields only (avoid inflating list payloads). */
export function patchRunInList(runs: Run[], event: RunEvent): Run[] {
  const index = runs.findIndex((run) => run.id === event.run_id);
  if (index === -1) return runs;

  const current = runs[index];
  const patched = applyRunEvent(current, event);
  const next = [...runs];
  next[index] = {
    ...current,
    status: patched.status,
    output: patched.output,
    error: patched.error,
    usage: patched.usage,
    updated_at: patched.updated_at,
  };
  return next;
}
