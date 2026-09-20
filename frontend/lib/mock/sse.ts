import type { Run, RunEvent, Step } from "@/lib/types";
import { SEED_RUN_IDS } from "./seed";
import {
  appendEvent,
  cloneRun,
  findRun,
  getMockStore,
  nowIso,
  upsertRun,
  type MockStore,
} from "./store";
import { nextId } from "./ids";

function event(
  runId: string,
  type: string,
  data: Record<string, unknown> = {},
): RunEvent {
  return {
    type,
    run_id: runId,
    at: nowIso(),
    data,
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function usageFrom(run: Run) {
  let tokens_in = 0;
  let tokens_out = 0;
  let cost_usd = 0;
  let latency_ms = 0;
  let hasLatency = false;
  let failed_step_count = 0;
  let tool_call_count = 0;
  let failed_tool_call_count = 0;
  for (const step of run.steps) {
    tokens_in += step.tokens_in ?? 0;
    tokens_out += step.tokens_out ?? 0;
    cost_usd += step.cost_usd ?? 0;
    if (step.latency_ms != null) {
      latency_ms += step.latency_ms;
      hasLatency = true;
    }
    if (step.status === "failed") failed_step_count += 1;
    for (const call of step.tool_calls ?? []) {
      tool_call_count += 1;
      if (call.error) failed_tool_call_count += 1;
    }
  }
  return {
    tokens_in,
    tokens_out,
    cost_usd,
    latency_ms: hasLatency ? latency_ms : null,
    step_count: run.steps.length,
    failed_step_count,
    tool_call_count,
    failed_tool_call_count,
  };
}

async function emit(
  store: MockStore,
  runId: string,
  ev: RunEvent,
  push: (ev: RunEvent) => void,
): Promise<void> {
  appendEvent(store, ev);
  push(ev);
  await sleep(180);
}

function ensureStep(run: Run, partial: Partial<Step> & { index: number; node: string }): Step {
  const existing = run.steps.find((s) => s.index === partial.index);
  if (existing) {
    Object.assign(existing, partial, { updated_at: nowIso() });
    return existing;
  }
  const step: Step = {
    id: nextId("stp"),
    index: partial.index,
    node: partial.node,
    status: partial.status ?? "running",
    input: partial.input ?? {},
    output: partial.output ?? null,
    error: partial.error ?? null,
    latency_ms: partial.latency_ms ?? null,
    tokens_in: partial.tokens_in ?? null,
    tokens_out: partial.tokens_out ?? null,
    cost_usd: partial.cost_usd ?? null,
    tool_calls: partial.tool_calls ?? [],
    created_at: nowIso(),
    updated_at: nowIso(),
  };
  run.steps.push(step);
  run.steps.sort((a, b) => a.index - b.index);
  return step;
}

/** Finish the seeded live review run when an SSE client connects. */
async function simulateSeedLiveRun(
  store: MockStore,
  run: Run,
  push: (ev: RunEvent) => void,
): Promise<void> {
  const runId = run.id;
  await emit(store, runId, event(runId, "run.started"), push);

  const lintStep = run.steps.find((s) => s.index === 1);
  if (lintStep) {
    await emit(
      store,
      runId,
      event(runId, "tool_call.completed", {
        step_index: 1,
        call_id: "tc_lint_1",
        name: "run_linter",
        result: { errors: 0, warnings: 2 },
        latency_ms: 1400,
      }),
      push,
    );
    lintStep.tool_calls = lintStep.tool_calls.map((c) =>
      c.id === "tc_lint_1"
        ? {
            ...c,
            result: { errors: 0, warnings: 2 },
            latency_ms: 1400,
          }
        : c,
    );
    lintStep.status = "succeeded";
    lintStep.output = { errors: 0, warnings: 2 };
    lintStep.tokens_out = 80;
    lintStep.latency_ms = 1400;
    lintStep.cost_usd = 0.003;
    lintStep.updated_at = nowIso();
    await emit(
      store,
      runId,
      event(runId, "step.completed", {
        index: 1,
        node: "lint",
        output: lintStep.output,
        latency_ms: 1400,
        tokens_in: lintStep.tokens_in,
        tokens_out: lintStep.tokens_out,
        cost_usd: lintStep.cost_usd,
      }),
      push,
    );
  }

  ensureStep(run, {
    index: 2,
    node: "review",
    status: "running",
    input: {},
  });
  await emit(
    store,
    runId,
    event(runId, "step.started", { index: 2, node: "review", input: {} }),
    push,
  );

  const chunks = [
    "Overall the mock demo wiring looks solid. ",
    "I would keep the seed data realistic (done) and ",
    "ensure SSE completes newly launched runs.",
  ];
  for (const delta of chunks) {
    await emit(
      store,
      runId,
      event(runId, "token.delta", {
        step_index: 2,
        part: "text",
        delta,
      }),
      push,
    );
  }

  const reply = chunks.join("");
  run.messages.push({
    id: nextId("msg"),
    index: run.messages.length,
    step_id: run.steps.find((s) => s.index === 2)?.id ?? null,
    role: "assistant",
    name: null,
    content: reply,
    tool_call_id: null,
    extra: {},
    created_at: nowIso(),
  });
  await emit(
    store,
    runId,
    event(runId, "message.created", {
      id: run.messages[run.messages.length - 1].id,
      index: run.messages.length - 1,
      role: "assistant",
      content: reply,
      step_id: run.messages[run.messages.length - 1].step_id,
    }),
    push,
  );

  const review = run.steps.find((s) => s.index === 2)!;
  review.status = "succeeded";
  review.output = { reply };
  review.tokens_in = 900;
  review.tokens_out = 140;
  review.cost_usd = 0.012;
  review.latency_ms = 2100;
  review.updated_at = nowIso();
  await emit(
    store,
    runId,
    event(runId, "step.completed", {
      index: 2,
      node: "review",
      output: { reply },
      latency_ms: 2100,
      tokens_in: 900,
      tokens_out: 140,
      cost_usd: 0.012,
    }),
    push,
  );

  run.status = "succeeded";
  run.output = { reply };
  run.usage = usageFrom(run);
  run.updated_at = nowIso();
  upsertRun(store, run);
  await emit(
    store,
    runId,
    event(runId, "run.completed", {
      output: run.output,
      usage: run.usage,
    }),
    push,
  );
}

/** Animate a newly created (or retried) run to completion. */
async function simulateNewRun(
  store: MockStore,
  run: Run,
  push: (ev: RunEvent) => void,
): Promise<void> {
  const runId = run.id;
  const prompt =
    typeof run.input.prompt === "string"
      ? run.input.prompt
      : JSON.stringify(run.input);

  run.status = "running";
  run.updated_at = nowIso();
  upsertRun(store, run);
  await emit(store, runId, event(runId, "run.started"), push);

  ensureStep(run, {
    index: 0,
    node: run.adapter === "echo" ? "echo" : "respond",
    status: "running",
    input: { prompt },
  });
  await emit(
    store,
    runId,
    event(runId, "step.started", {
      index: 0,
      node: run.steps[0].node,
      input: { prompt },
    }),
    push,
  );

  const reply =
    run.adapter === "echo"
      ? prompt
      : `Demo response for: ${prompt.slice(0, 180)}`;

  if (run.adapter !== "echo") {
    for (const delta of ["Thinking… ", reply.slice(0, 40), reply.slice(40)]) {
      if (!delta) continue;
      await emit(
        store,
        runId,
        event(runId, "token.delta", {
          step_index: 0,
          part: "text",
          delta,
        }),
        push,
      );
    }
  }

  run.messages.push({
    id: nextId("msg"),
    index: run.messages.length,
    step_id: run.steps[0]?.id ?? null,
    role: "assistant",
    name: null,
    content: reply,
    tool_call_id: null,
    extra: {},
    created_at: nowIso(),
  });
  await emit(
    store,
    runId,
    event(runId, "message.created", {
      id: run.messages[run.messages.length - 1].id,
      index: run.messages.length - 1,
      role: "assistant",
      content: reply,
      step_id: run.messages[run.messages.length - 1].step_id,
    }),
    push,
  );

  const step = run.steps[0];
  step.status = "succeeded";
  step.output = { text: reply };
  step.tokens_in = Math.max(8, Math.ceil(prompt.length / 4));
  step.tokens_out = Math.max(8, Math.ceil(reply.length / 4));
  step.cost_usd = run.adapter === "echo" ? 0 : 0.0024;
  step.latency_ms = 320;
  step.updated_at = nowIso();
  await emit(
    store,
    runId,
    event(runId, "step.completed", {
      index: 0,
      node: step.node,
      output: step.output,
      latency_ms: step.latency_ms,
      tokens_in: step.tokens_in,
      tokens_out: step.tokens_out,
      cost_usd: step.cost_usd,
    }),
    push,
  );

  if (run.adapter !== "echo") {
    run.checkpoints.push({
      id: nextId("cp"),
      index: 0,
      label: "after_respond",
      created_at: nowIso(),
    });
    await emit(
      store,
      runId,
      event(runId, "checkpoint.created", {
        index: 0,
        label: "after_respond",
      }),
      push,
    );
  }

  run.status = "succeeded";
  run.output = { text: reply };
  run.error = null;
  run.usage = usageFrom(run);
  run.updated_at = nowIso();
  upsertRun(store, run);
  await emit(
    store,
    runId,
    event(runId, "run.completed", {
      output: run.output,
      usage: run.usage,
    }),
    push,
  );
}

export async function streamMockRunEvents(
  runId: string,
  request: Request,
): Promise<Response> {
  const store = getMockStore();
  const run = findRun(store, runId);
  if (!run) {
    return new Response(JSON.stringify({ detail: "run not found" }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }

  const encoder = new TextEncoder();
  let closed = false;
  let eventId = 0;

  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (ev: RunEvent) => {
        if (closed) return;
        eventId += 1;
        const payload = `id: ${eventId}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev)}\n\n`;
        controller.enqueue(encoder.encode(payload));
      };

      const sendComment = (text: string) => {
        if (closed) return;
        controller.enqueue(encoder.encode(`: ${text}\n\n`));
      };

      request.signal.addEventListener("abort", () => {
        closed = true;
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      });

      sendComment("mock connected");

      // Replay any buffered events for reconnecting clients.
      const buffered = store.events[runId] ?? [];
      for (const ev of buffered) {
        send(ev);
      }

      const shouldSimulateNew = store.pendingSimulations.has(runId);
      const shouldSimulateSeedLive =
        runId === SEED_RUN_IDS.runningLive &&
        (run.status === "running" || run.status === "pending") &&
        buffered.length === 0;

      if (shouldSimulateNew || shouldSimulateSeedLive) {
        store.pendingSimulations.delete(runId);
        const live = cloneRun(findRun(store, runId)!);
        try {
          if (shouldSimulateSeedLive) {
            await simulateSeedLiveRun(store, live, send);
          } else {
            await simulateNewRun(store, live, send);
          }
        } catch (err) {
          console.error("[mock sse]", err);
        }
      } else if (
        run.status === "running" ||
        run.status === "pending" ||
        run.status === "waiting_human"
      ) {
        // Keep the stream open with heartbeats for waiting/running rows.
        while (!closed) {
          sendComment(`ping ${Date.now()}`);
          await sleep(12_000);
          const latest = findRun(store, runId);
          if (
            !latest ||
            ["succeeded", "failed", "cancelled"].includes(latest.status)
          ) {
            break;
          }
        }
      }

      if (!closed) {
        try {
          controller.close();
        } catch {
          /* ignore */
        }
      }
    },
    cancel() {
      closed = true;
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
