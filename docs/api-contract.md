# Frontend ↔ Backend API Contract (v1)

This document freezes the HTTP surface that the Next.js console relies on
(see [`frontend/lib/api.ts`](../frontend/lib/api.ts)). The Java/Spring Boot
server in [`backend-java/`](../backend-java/) implements these endpoints.

The Next.js dev server proxies `/api/*` → `${AGENTFLOW_API_URL}/*`
(see [`frontend/next.config.mjs`](../frontend/next.config.mjs)). All paths
below are relative to that backend root.

## Conventions

- Timestamps are ISO-8601 with timezone offset (`2026-05-13T06:00:00+00:00`).
- IDs are ULIDs encoded as 26-character strings.
- JSON keys use `snake_case`. The frontend types in
  [`frontend/lib/types.ts`](../frontend/lib/types.ts) are the source of truth.
- Errors return `{"detail": "<message>"}` with a non-2xx status code.

## Endpoints

### `GET /v1/health`

Health probe.

```json
{
  "status": "ok",
  "version": "0.1.0",
  "adapters": ["echo", "langgraph"]
}
```

### `POST /v1/agents` → 201

Request:

```json
{
  "name": "writer",
  "description": "optional",
  "adapter": "echo",
  "config": {}
}
```

Response: a full `Agent` record (see schema below). Returns 409 if `name`
already exists.

### `GET /v1/agents` → 200

Response: `Agent[]` ordered by `created_at` descending.

### `GET /v1/agents/{id}` → 200

Response: `Agent`. 404 if missing.

### `POST /v1/runs` → 202

Request:

```json
{
  "agent_id": "01HZ...",
  "input": { "prompt": "hi" },
  "metadata": {},
  "adapter": "echo"
}
```

`metadata` and `adapter` are optional. When `adapter` is omitted the agent's
default adapter is used.

Response: a full `Run` record. The run is created with status `pending` and
a background job is dispatched to a worker; the response returns before the
adapter has finished. Clients should poll `/v1/runs/{id}` or subscribe to
`/v1/events/{id}` for terminal status.

Returns 404 if the agent does not exist.

### `GET /v1/runs?limit=50` → 200

Response: `Run[]` ordered by `created_at` descending. `limit` clamps to a
sensible upper bound on the server (default 50).

### `GET /v1/runs/{id}` → 200

Response: a `Run` populated with `steps`, `messages`, and `checkpoints`.
404 if missing.

### `POST /v1/runs/{id}/cancel` → 204

Signals the worker to cancel the run. Idempotent; returns 204 whether or not
the run is already in a terminal state. Returns 404 if the run does not exist.

### `GET /v1/events/{run_id}` → 200 `text/event-stream`

Server-Sent Events stream of `RunEvent` records. Stays open until the run
reaches a terminal state (`run.completed`, `run.failed`, `run.cancelled`) or
the client disconnects. The server sends `event: ping` heartbeats roughly
every 15 seconds.

Each SSE frame uses the event type as the SSE `event` field and the JSON
payload below as `data`:

```json
{
  "type": "step.started",
  "run_id": "01HZ...",
  "at": "2026-05-13T06:00:00+00:00",
  "data": { "index": 0, "node": "plan" }
}
```

The supported `type` values are:

`run.created`, `run.started`, `run.completed`, `run.failed`, `run.cancelled`,
`step.started`, `step.completed`, `step.failed`, `message.created`,
`tool_call.started`, `tool_call.completed`, `checkpoint.created`, `log`.

## Schemas

### `Agent`

```ts
{
  id: string;
  name: string;
  description: string | null;
  adapter: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}
```

### `Run`

```ts
{
  id: string;
  agent_id: string;
  adapter: string;
  status: "pending" | "running" | "succeeded" | "failed" | "cancelled" | "waiting_human";
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  steps: Step[];
  messages: Message[];
  checkpoints: Checkpoint[];
}
```

### `Step`

```ts
{
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
```

### `Message`

```ts
{
  id: string;
  index: number;
  role: "system" | "user" | "assistant" | "tool";
  name: string | null;
  content: string;
  tool_call_id: string | null;
  extra: Record<string, unknown>;
  created_at: string;
}
```

### `ToolCall`

```ts
{
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  latency_ms: number | null;
}
```

### `Checkpoint`

```ts
{
  id: string;
  index: number;
  label: string | null;
  created_at: string;
}
```

## API ↔ worker protocol (internal)

The HTTP contract above is the only surface the frontend sees. Between the
Java API and the Python worker we use Redis as the broker:

- **Job queue** — Redis stream `agentflow:jobs:runs` (default). The API
  server pushes JSON job payloads with `XADD <stream> * payload <json>`;
  the worker consumes them with `XREADGROUP` inside the
  `agentflow-workers` consumer group and explicitly `XACK`s after the run
  reaches a terminal state. Pending entries left behind by a crashed
  worker are recovered with `XAUTOCLAIM`; entries that exceed
  `AGENTFLOW_JOB_STREAM_MAX_DELIVERIES` (default 5) are routed to the
  `agentflow:jobs:runs:dlq` stream and ACKed off the main stream.

  This gives the broker at-least-once semantics: a worker that dies
  mid-execute does not lose the job.

  Set `AGENTFLOW_JOBS_IMPL=list` on the Java side and
  `AGENTFLOW_REDIS_QUEUE_IMPL=list` on the Python worker to fall back to
  the `LPUSH` + `BRPOP` protocol (at-most-once).

  Payload (identical in both modes — the streams mode wraps it in a
  single-field map record `{"payload": "<json>"}` so Python's
  `RunJob.from_json` is reused unchanged):

  ```json
  {
    "run_id": "01HZ...",
    "agent_id": "01HZ...",
    "adapter": "echo",
    "enqueued_at": "2026-05-13T06:00:00+00:00"
  }
  ```

- **Cancel signal** — Redis key `agentflow:cancel:{run_id}` with value `"1"`
  and a 24h TTL. The API server writes the key on `POST /v1/runs/{id}/cancel`.
  The worker checks the key before starting the adapter and at each event
  emission; on the cancellation signal it stops the adapter and writes
  `RunStatus.CANCELLED`.

- **Event bus** — Redis pub/sub channel `agentflow:run:{run_id}`. The worker
  publishes `RunEvent` JSON payloads on every state change. The API server
  subscribes to forward them to SSE clients.

- **State of truth** — Postgres. All run/step/message/tool_call/checkpoint
  rows are written by the worker; the API server reads them on GET endpoints.
  Only `Run.status = pending|cancelled` may be written by the API, and only
  before the worker picks up the job.
