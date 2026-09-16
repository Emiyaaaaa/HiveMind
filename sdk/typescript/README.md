# AgentFlow TypeScript SDK

Typed client for the AgentFlow `/v1` HTTP API. The OpenAPI contract lives in
[`openapi/openapi.yaml`](../../openapi/openapi.yaml).

## Install

```bash
cd sdk/typescript
npm install
npm run build
```

## Usage

```ts
import { AgentFlowClient, subscribeRunEvents } from "@agentflow/sdk";

const client = new AgentFlowClient({
  baseUrl: "http://localhost:8000",
  apiKey: "dev-admin",
});

const run = await client.createRun({
  agent_id: "01HZ...",
  input: { prompt: "hello" },
});

const subscription = subscribeRunEvents("http://localhost:8000", run.id, {
  apiKey: "dev-admin",
  onEvent: (event) => console.log(event.type, event.data),
});

// subscription.close() when done
```

`createRun` maps to `POST /v1/runs`. `subscribeRunEvents` wraps the SSE stream
at `GET /v1/events/{run_id}` (browser `EventSource` with reconnect).

### Human approval, retry and threads

```ts
import { AgentFlowClient } from "@agentflow/sdk";

const client = new AgentFlowClient({ baseUrl: "http://localhost:8000", apiKey: "dev-operator" });

// Conversation: the worker seeds later runs with the thread's recent turns.
const thread = await client.createThread({ agent_id: "01HZ...", title: "Support chat" });
let run = await client.createRun({
  agent_id: "01HZ...",
  input: { prompt: "refund order 42" },
  thread_id: thread.id,
});

// Resolves on succeeded / failed / cancelled *or* waiting_human.
run = await client.waitForRun(run.id, { timeoutMs: 120_000 });
if (run.status === "waiting_human") {
  run = await client.resumeRun(run.id, { input: { approval: "approved" } });
  run = await client.waitForRun(run.id, { timeoutMs: 120_000 });
}
if (run.status === "failed") {
  run = await client.retryRun(run.id); // latest checkpoint; rejects with 409 unless failed
}

const page = await client.listRunMessages(run.id, { limit: 50 }); // follow page.next_cursor
const audit = await client.getRunAudit(run.id);                    // cancel / resume trail
const transcript = await client.listThreadMessages(thread.id);     // cross-run, opaque cursor
```

| Method | Endpoint |
| --- | --- |
| `createRun({ agent_id, input, metadata, adapter, thread_id })` | `POST /v1/runs` |
| `getRun` / `cancelRun` | `GET` / `POST …/cancel` |
| `retryRun(runId, { checkpoint_index })` | `POST /v1/runs/{id}/retry` |
| `resumeRun(runId, { input })` | `POST /v1/runs/{id}/resume` |
| `waitForRun(runId, { timeoutMs, pollIntervalMs, until })` | polls `GET /v1/runs/{id}`; rejects with `RunTimeoutError` (carries the last `Run`) |
| `listRunMessages(runId, { cursor, limit })` | `GET /v1/runs/{id}/messages` |
| `getRunAudit(runId)` | `GET /v1/runs/{id}/audit` |
| `createThread` / `listThreads` / `getThread` / `listThreadRuns` / `listThreadMessages` | `/v1/threads…` |

## Tests

```bash
cd sdk/typescript && npm install && npm run build && npm test
```

Tests are `src/*.test.ts` on `node:test` with a scripted `fetch`; `npm run
build` compiles them next to the library in `dist/`.

Regenerate full REST stubs from the OpenAPI spec with
`scripts/gen/generate-sdks.sh`.
