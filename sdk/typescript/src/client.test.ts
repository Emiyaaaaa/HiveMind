/** AgentFlowClient against a scripted `fetch` (no server needed). */
import assert from "node:assert/strict";
import { test } from "node:test";

import { AgentFlowClient, RunTimeoutError } from "./client.js";
import type { Run } from "./types.js";

function run(status: Run["status"] = "pending", extra: Partial<Run> = {}): Run {
  return {
    id: "01RUN",
    tenant_id: "default",
    agent_id: "01AGENT",
    adapter: "echo",
    status,
    input: { prompt: "hi" },
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    steps: [],
    messages: [],
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
    ...extra,
  };
}

interface Recorded {
  method: string;
  url: string;
  body: unknown;
  headers: Record<string, string>;
}

/** Scripted fetch: each entry answers one call in order. */
function fakeFetch(responses: Array<[number, unknown]>) {
  const calls: Recorded[] = [];
  const impl: typeof fetch = async (input, init) => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key] = value;
    });
    calls.push({
      method: init?.method ?? "GET",
      url: String(input),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      headers,
    });
    const [status, payload] = responses.length > 1 ? responses.shift()! : responses[0]!;
    return new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { impl, calls };
}

const BASE = "http://api.test";

test("createRun forwards thread_id and the API key", async () => {
  const { impl, calls } = fakeFetch([[202, run("pending", { thread_id: "01THREAD" } as Partial<Run>)]]);
  const client = new AgentFlowClient({ baseUrl: BASE, apiKey: "k", fetch: impl });

  const created = await client.createRun({
    agent_id: "01AGENT",
    input: { prompt: "hi" },
    thread_id: "01THREAD",
  });

  assert.equal(created.status, "pending");
  assert.equal(calls[0]!.url, `${BASE}/v1/runs`);
  assert.deepEqual(calls[0]!.body, {
    agent_id: "01AGENT",
    input: { prompt: "hi" },
    thread_id: "01THREAD",
  });
  assert.equal(calls[0]!.headers["x-api-key"], "k");
});

test("retryRun / resumeRun post optional bodies and surface 409", async () => {
  const { impl, calls } = fakeFetch([
    [202, run()],
    [202, run()],
    [409, { detail: "run is not failed" }],
  ]);
  const client = new AgentFlowClient({ baseUrl: BASE, fetch: impl });

  await client.retryRun("01RUN", { checkpoint_index: 2 });
  await client.resumeRun("01RUN", { input: { approval: "approved" } });
  await assert.rejects(client.retryRun("01RUN"), /409/);

  assert.equal(calls[0]!.url, `${BASE}/v1/runs/01RUN/retry`);
  assert.deepEqual(calls[0]!.body, { checkpoint_index: 2 });
  assert.equal(calls[1]!.url, `${BASE}/v1/runs/01RUN/resume`);
  assert.deepEqual(calls[1]!.body, { input: { approval: "approved" } });
  assert.deepEqual(calls[2]!.body, {});
});

test("waitForRun stops on waiting_human, then on the terminal status", async () => {
  const { impl, calls } = fakeFetch([
    [200, run("running")],
    [200, run("waiting_human")],
    [200, run("succeeded", { output: { reply: "ok" } })],
  ]);
  const client = new AgentFlowClient({ baseUrl: BASE, fetch: impl });

  const paused = await client.waitForRun("01RUN", { pollIntervalMs: 0 });
  assert.equal(paused.status, "waiting_human");
  const done = await client.waitForRun("01RUN", { pollIntervalMs: 0 });
  assert.equal(done.status, "succeeded");
  assert.deepEqual(done.output, { reply: "ok" });
  assert.equal(calls.length, 3);
});

test("waitForRun rejects with RunTimeoutError carrying the last run", async () => {
  const { impl } = fakeFetch([[200, run("running")]]);
  const client = new AgentFlowClient({ baseUrl: BASE, fetch: impl });

  await assert.rejects(
    client.waitForRun("01RUN", { timeoutMs: 0, pollIntervalMs: 0 }),
    (error: unknown) => error instanceof RunTimeoutError && error.run.status === "running",
  );
});

test("message pages and audit use query params and typed results", async () => {
  const { impl, calls } = fakeFetch([
    [200, { items: [{ index: 2 }], next_cursor: 2, has_more: true }],
    [200, [{ id: "01A", action: "resume", run_id: "01RUN" }]],
  ]);
  const client = new AgentFlowClient({ baseUrl: BASE, fetch: impl });

  const page = await client.listRunMessages("01RUN", { cursor: 4, limit: 2 });
  assert.equal(page.next_cursor, 2);
  assert.equal(calls[0]!.url, `${BASE}/v1/runs/01RUN/messages?cursor=4&limit=2`);

  const audit = await client.getRunAudit("01RUN");
  assert.equal(audit[0]!.action, "resume");
  assert.equal(calls[1]!.url, `${BASE}/v1/runs/01RUN/audit`);
});

test("threads: create, get, runs and cross-run messages", async () => {
  const thread = {
    id: "01THREAD",
    tenant_id: "default",
    agent_id: "01AGENT",
    title: "Support",
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
  };
  const { impl, calls } = fakeFetch([
    [201, thread],
    [200, thread],
    [200, [run("succeeded"), run("pending")]],
    [200, { items: [{ run_id: "01RUN", index: 0 }], next_cursor: "k|0|x", has_more: true }],
  ]);
  const client = new AgentFlowClient({ baseUrl: BASE, fetch: impl });

  const created = await client.createThread({ agent_id: "01AGENT", title: "Support" });
  assert.equal(created.id, "01THREAD");
  assert.deepEqual(calls[0]!.body, { agent_id: "01AGENT", title: "Support" });
  assert.equal((await client.getThread("01THREAD")).title, "Support");
  assert.equal((await client.listThreadRuns("01THREAD", { limit: 10 })).length, 2);
  assert.equal(calls[2]!.url, `${BASE}/v1/threads/01THREAD/runs?limit=10`);
  const page = await client.listThreadMessages("01THREAD", { cursor: "k|1|y" });
  assert.equal(page.next_cursor, "k|0|x");
  assert.equal(calls[3]!.url, `${BASE}/v1/threads/01THREAD/messages?cursor=k%7C1%7Cy`);
});
