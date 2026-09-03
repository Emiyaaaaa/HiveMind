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
- **Auth (optional).** When `AGENTFLOW_AUTH_ENABLED=true`, every `/v1/*`
  endpoint except `GET /v1/health` requires
  `Authorization: Bearer <api-key>` or `X-Api-Key: <api-key>`. Each key maps
  to an organization (`tenant_id`) and role (`viewer` | `operator` | `admin`).
  Keys may additionally be constrained to one project or one Agent using
  `key:organization:role[:project_id[:agent_id]]`; a narrower scope is never
  allowed to access a sibling resource and returns 404. Missing key → 401;
  insufficient role within an allowed scope → 403.
  Auth is **off by default** for local development.

### Roles

| Role | Capabilities |
| --- | --- |
| `viewer` | List/get agents, runs, versions, SSE |
| `operator` | viewer + create/cancel/retry/resume runs |
| `admin` | operator + create/update/restore agents + data erasure / retention purge |

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

`adapters` lists whatever is registered at runtime, so it also contains any
adapter plugin installed through the `agentflow.adapters` entry-point group.

### `POST /v1/agents` → 201

Request:

```json
{
  "name": "writer",
  "description": "optional",
  "adapter": "echo",
  "config": {},
  "project_id": "01HZ..."
}
```

Response: a full `Agent` record (see schema below). Returns 409 if `name`
already exists.

### `POST /v1/projects` → 201

Organization administrators create projects with `name` and optional
`description`. `GET /v1/projects` lists only projects visible to the current
organization/project scope; `GET /v1/projects/{id}` returns one visible project.

### `GET /v1/agents` → 200

Response: `Agent[]` ordered by `created_at` descending.

### `GET /v1/agents/{id}` → 200

Response: `Agent`. 404 if missing.

### `PATCH /v1/agents/{id}` → 200

Partial update. When `adapter`, `config`, or `description` change, `version`
increments and a row is appended to `agent_versions`. Name-only updates do
not bump the version. Optional `note` is stored on the new snapshot.

Request (all fields optional):

```json
{
  "name": "writer-v2",
  "description": "optional",
  "adapter": "langgraph",
  "config": { "model": "openai/gpt-4o-mini" },
  "note": "enable langgraph"
}
```

Response: updated `Agent`. 404 if missing; 409 if `name` collides.

### `GET /v1/agents/{id}/versions` → 200

Response: `AgentVersion[]` ordered by `version` descending.

### `GET /v1/agents/{id}/versions/{version}` → 200

Response: `AgentVersion`. 404 if agent or version missing.

### `GET /v1/agents/{id}/versions/diff?from=1&to=2` → 200

Response: `AgentVersionDiff` comparing two snapshots (adapter / description /
config added·removed·changed).

### `POST /v1/agents/{id}/versions/{version}/restore` → 200

Copy the snapshot's adapter/config/description onto the live agent as a **new**
version (does not delete history). No-op (no bump) when already identical.

### `POST /v1/threads` → 201

Request:

```json
{
  "agent_id": "01HZ...",
  "title": "Support chat",
  "user_id": "user-42",
  "project_id": null
}
```

Creates a conversation thread scoped to the agent (and tenant). `title` and
`user_id` are optional. `project_id` defaults to the agent's project when
omitted. Returns 404 if the agent is not visible to the caller.

### `GET /v1/threads?limit=50` → 200

Response: `Thread[]` for the caller's tenant/project/agent scope, newest first.

### `GET /v1/threads/{id}` → 200

Response: one `Thread`. 404 if missing or not visible (including cross-tenant).

### `GET /v1/threads/{id}/messages?cursor=&limit=50` → 200

Merged transcript across all Runs in the thread, ordered by run time then
message index. Each item includes `run_id` plus the usual Message fields.
The first response is the newest page; `next_cursor` is an opaque
`run.created_at|index|id` key for older pages. 404 if the thread is not visible.

### `GET /v1/threads/{id}/runs?limit=50` → 200

Response: `Run[]` belonging to the thread, oldest first. 404 if the thread is
not visible.

### `POST /v1/runs` → 202

Request:

```json
{
  "agent_id": "01HZ...",
  "input": { "prompt": "hi" },
  "metadata": {},
  "adapter": "echo",
  "thread_id": "01HZ..."
}
```

`metadata`, `adapter`, and `thread_id` are optional. When `adapter` is omitted
the agent's default adapter is used. When `thread_id` is set, the run is linked
to that thread and the worker seeds prior thread turns into
`AdapterContext.thread_messages` (window-trimmed). Returns 404 if the thread is
missing, belongs to another tenant/agent, or is otherwise not visible.

The server replaces the reserved `_agentflow`
metadata namespace and records the agent's current version as
`_agentflow.agent_version`; client-supplied values in that namespace are never
trusted.

The Python worker resolves a pinned run through
`agent_id + _agentflow.agent_version` and executes the corresponding immutable
`AgentVersion.config` snapshot. A pinned run fails explicitly if that snapshot
is missing. Only legacy runs without a version pin fall back to the agent's
current config.

Response: a full `Run` record. The run is created with status `pending` and
a background job is dispatched to a worker; the response returns before the
adapter has finished. Clients should poll `/v1/runs/{id}` or subscribe to
`/v1/events/{id}` for terminal status.

Returns 404 if the agent does not exist.

### `GET /v1/runs?limit=50` → 200

Response: `Run[]` ordered by `created_at` descending. `limit` clamps to a
sensible upper bound on the server (default 50).

### `GET /v1/runs/{id}` → 200

Response: a `Run` populated with `steps`, a **preview** of `messages` (most
recent *K*, default 50), and `checkpoints`. When older messages exist,
`messages_truncated` is `true`; use `GET /v1/runs/{id}/messages` to page
backward. 404 if missing.

### `GET /v1/runs/{id}/messages?cursor=&limit=50` → 200

Cursor-paginated run transcript in ascending `index` order. Omit `cursor` to
fetch the newest page; pass `next_cursor` from a prior response to load older
messages (`index` exclusive upper bound). `limit` clamps on the server
(default 50, max 200).

Response:

```json
{
  "items": [/* Message */],
  "next_cursor": 12,
  "has_more": true
}
```

404 if the run does not exist.

### `POST /v1/runs/{id}/cancel` → 204

Signals the worker to cancel the run. Idempotent; returns 204 whether or not
the run is already in a terminal state. Returns 404 if the run does not exist.

### `POST /v1/runs/{id}/retry` → 202

Re-queues a **failed** run for another worker attempt. The latest checkpoint is
used when present; pass an explicit index to resume from an older snapshot.

Request (optional body):

```json
{
  "checkpoint_index": 0
}
```

Response: a full `Run` record with status `pending` (worker will transition to
`running`). Returns **404** if the run does not exist, **409** if status is not
`failed` or the checkpoint index is missing.

### `POST /v1/runs/{id}/resume` → 202

Continues a run in **`waiting_human`** after human approval. The optional body
is merged into the run's persisted `input` and forwarded to the adapter via
resume metadata.

Request (optional body):

```json
{
  "input": { "approval": "approved" }
}
```

Response: a full `Run` record with status `pending`. Returns **404** if missing,
**409** if status is not `waiting_human`.

### `POST /v1/run-comparisons/preview` → 200

Returns a read-only summary comparison of two terminal runs. It does not
persist a comparison or execute either run again.

Request:

```json
{
  "baseline_run_id": "01HZ...A",
  "candidate_run_id": "01HZ...B"
}
```

Both runs must exist, have different IDs, belong to the same Agent, and be in
`succeeded`, `failed`, or `cancelled`. The response contains each Run's ID,
Agent ID, pinned AgentVersion, status and error, plus boolean flags indicating
whether the version, status, error, input or output changed. A `null` version
identifies a historical Run without a version pin. Output changes are
diagnostic only and do not fail regression cases.

The endpoint intentionally does not compute field-level JSON changes, align
Steps, or aggregate token, cost and latency metrics. Those records remain
available from the normal Run read endpoint.

Returns **404** when either run is missing, **409** while either run is not
terminal, and **422** for identical run IDs or runs owned by different agents.

### `POST /v1/regression-executions` → 202

Starts an ephemeral regression execution from 1–100 terminal baseline Runs.
All baselines must belong to the same Agent. The Java API resolves that
Agent's current immutable version snapshot once, copies each baseline input
into a new candidate Run pinned to that one version, and dispatches the
candidates through the normal Python Worker queue.

Request:

```json
{
  "baseline_run_ids": ["01HZ...A", "01HZ...B"]
}
```

Candidate version metadata is server-owned and cannot be supplied by the
client. Duplicate IDs are rejected and a request is limited to 100 Runs to
avoid accidentally flooding the worker queue.

The response contains one temporary `execution_id`, the fixed candidate Agent
version, total/completed counts, and baseline/candidate Run ID pairs. The
execution manifest is JSON stored at
`agentflow:regression:execution:{execution_id}` in Redis and expires after 30
days. Runs, Steps, outputs, metrics, and AgentVersion snapshots remain in
Postgres. No regression database table is created.

Returns **404** if a baseline Run or current AgentVersion snapshot is missing,
**409** if a baseline is non-terminal, **422** for duplicate IDs or mixed
Agents, and **503** if the temporary Redis manifest cannot be stored.

### `GET /v1/regression-executions/{execution_id}` → 200

Loads the Run pairs from Redis, reads candidate Run states from Postgres, and
returns current progress. Redis is not treated as the source of truth for Run
status. Overall status is `pending`, `running`, or `completed`, with only total
and completed counts returned. Failed and cancelled candidates are terminal
and therefore count as completed cases.

Returns **404** when the manifest is missing or has expired.

### `GET /v1/regression-executions/{execution_id}/results` → 200

Available after every candidate Run is terminal. Each pair is evaluated with
the existing Run-comparison service. A case passes when status and error are
unchanged; output differences remain diagnostic and do not fail LLM-backed
cases. The response includes per-case pass/fail reasons and total passed and
failed counts; callers can use the standalone comparison endpoint for the
simple version, status, error, input and output change summary.

Returns **409** while any candidate Run is non-terminal and **404** when the
manifest is missing or expired. Results are computed from Postgres on demand;
they are not persisted separately.

### `GET /v1/events/{run_id}` → 200 `text/event-stream`

Server-Sent Events stream of `RunEvent` records. Stays open until the run
reaches a terminal state (`run.completed`, `run.failed`, `run.cancelled`) or
the client disconnects. The server sends `event: ping` heartbeats roughly
every 15 seconds.

On reconnect, send the standard `Last-Event-ID` header or `?last_event_id=`
query parameter to replay missed events before resuming the live stream. Each
persisted frame includes an SSE `id` field; the log is stored in Redis Stream
`agentflow:run:{run_id}:log` (or in-memory when Redis is unset).

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
`run.waiting_human`,
`step.started`, `step.updated`, `step.completed`, `step.failed`, `token.delta`,
`message.created`, `tool_call.started`, `tool_call.completed`,
`checkpoint.created`, `log`.

`token.delta` is SSE-only (not persisted). Payload:

```json
{ "step_index": 0, "delta": "Hel", "role": "assistant" }
```

`step.updated` flushes deferred metrics on a running step (tokens, latency)
before `step.completed`:

```json
{ "index": 0, "tokens_in": 42, "tokens_out": 128, "cost_usd": 0.00012, "latency_ms": 1200 }
```

`tool_call.started` / `tool_call.completed` share a stable ``call_id`` (ULID,
also the persisted ``ToolCall.id``) so parallel or same-name invocations
within one step associate correctly:

```json
{ "step_index": 0, "name": "echo", "arguments": { "text": "hi" }, "call_id": "01HZ..." }
```

```json
{ "step_index": 0, "name": "echo", "call_id": "01HZ...", "result": { "text": "hi" }, "error": null, "latency_ms": 12 }
```

Adapters should pass the ``call_id`` returned from ``emit_tool_call_started``
into ``emit_tool_call_completed``. When ``call_id`` is omitted on completed,
the runtime falls back to the oldest incomplete call with a matching name.

``message.created`` — adapters emit ``step_index``; the runtime resolves it to
the persisted ``step_id`` (nullable when omitted). Broadcast payload:

```json
{
  "role": "assistant",
  "content": "hello",
  "step_index": 0,
  "index": 3,
  "step_id": "01HZ...",
  "extra": {}
}
```

### `POST /v1/runs/{run_id}/erase` → 200

Admin-only GDPR-style erasure of run working memory: deletes all ``Message`` and
``Checkpoint`` rows, clears ``output`` and ``_resume`` metadata, and drops the
Redis event replay stream. Step rows are kept for audit. Returns **409** while
the run is ``pending`` or ``running``.

```json
{ "run_id": "01HZ...", "messages_deleted": 12, "checkpoints_deleted": 4 }
```

### `POST /v1/organization/erase` → 200

Admin-only tenant-wide erasure for the authenticated ``tenant_id``.

```json
{
  "tenant_id": "default",
  "runs_processed": 42,
  "messages_deleted": 900,
  "checkpoints_deleted": 120
}
```

### `POST /v1/retention/purge` → 200

Admin-only TTL purge for terminal runs older than
``AGENTFLOW_DATA_RETENTION_TENANT_TTL_DAYS`` (0 = disabled). The Python worker
also runs this sweep in the background when TTL is configured.

```json
{
  "tenant_id": "default",
  "runs_purged": 5,
  "messages_deleted": 80,
  "checkpoints_deleted": 10
}
```

Optional body: ``{ "tenant_id": "default", "dry_run": false }``.

## Schemas

### `Agent`

```ts
{
  id: string;
  tenant_id: string;
  project_id: string | null;
  name: string;
  description: string | null;
  adapter: string;
  config: Record<string, unknown>;
  version: number;
  created_at: string;
  updated_at: string;
}
```

`tenant_id` is assigned from the caller's API key (or `"default"` when auth
is disabled). Agent `name` is unique **per tenant**.

### `AgentVersion`

```ts
{
  id: string;
  agent_id: string;
  version: number;
  description: string | null;
  adapter: string;
  config: Record<string, unknown>;
  note: string | null;
  created_at: string;
}
```

### `AgentVersionDiff`

```ts
{
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
```

### `Run`

```ts
{
  id: string;
  tenant_id: string;
  project_id: string | null;
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
  messages_truncated?: boolean;
  checkpoints: Checkpoint[];
  usage: RunUsage;
}
```

### `RunUsage`

Aggregated token, cost, and structural metrics for a run. Computed from
`steps` when present; otherwise read from `metadata.usage` (written when the
run reaches a terminal state).

```ts
{
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  latency_ms: number | null;
  step_count: number;
  failed_step_count: number;
  tool_call_count: number;
  failed_tool_call_count: number;
}
```

`step_count` / `tool_call_count` (and their failed counterparts) summarize
graph shape without opening the full step list — useful for run lists and
ops dashboards.
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
  cost_usd: number | null;
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
  step_id: string | null;
  role: "system" | "user" | "assistant" | "tool";
  name: string | null;
  content: string;
  tool_call_id: string | null;
  extra: Record<string, unknown>;
  created_at: string;
}
```

### `MessagePage`

```ts
{
  items: Message[];
  next_cursor: number | null;
  has_more: boolean;
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

- **Event bus** — Redis pub/sub channel `agentflow:run:{run_id}` for live
  delivery, plus Redis Stream `agentflow:run:{run_id}:log` for durable
  `Last-Event-ID` replay. The worker `XADD`s persisted events (skipping
  ephemeral `token.delta`) then `PUBLISH`es an `{id, event}` envelope. The
  API server replays the stream on subscribe/reconnect, then forwards live
  pub/sub frames to SSE clients.

- **State of truth** — Postgres. All run/step/message/tool_call/checkpoint
  rows are written by the worker; the API server reads them on GET endpoints.
  Only `Run.status = pending|cancelled` may be written by the API, and only
  before the worker picks up the job.
