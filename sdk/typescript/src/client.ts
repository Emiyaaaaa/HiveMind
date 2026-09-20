/**
 * Typed REST client for the Hivemind `/v1` API.
 *
 * Covers the run lifecycle end to end: create, poll/wait, cancel, retry a
 * failed run, resume a `waiting_human` run after approval, page through the
 * transcript, read the cancel/resume audit trail, and drive multi-run
 * conversations through threads. Live streaming lives in `events.ts`.
 */
import type {
  AgentFlowClientOptions,
  MessagePage,
  Run,
  RunAuditEvent,
  RunCreateRequest,
  RunResumeRequest,
  RunRetryRequest,
  RunStatus,
  Thread,
  ThreadCreateRequest,
  WaitForRunOptions,
} from "./types.js";

const TERMINAL_STATUSES: readonly RunStatus[] = ["succeeded", "failed", "cancelled"];
const DEFAULT_WAIT_UNTIL: readonly RunStatus[] = [...TERMINAL_STATUSES, "waiting_human"];

/** `waitForRun` gave up before the run reached a wanted status; carries the last `Run`. */
export class RunTimeoutError extends Error {
  readonly run: Run;

  constructor(run: Run, timeoutMs: number) {
    super(`run ${run.id} still ${run.status} after ${timeoutMs}ms`);
    this.name = "RunTimeoutError";
    this.run = run;
  }
}

function authHeaders(apiKey?: string): Record<string, string> {
  return apiKey ? { "X-Api-Key": apiKey } : {};
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${text}`);
  }
  return (await response.json()) as T;
}

function withQuery(path: string, params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

export class AgentFlowClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: AgentFlowClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  private get(path: string): Promise<Response> {
    return this.fetchImpl(`${this.baseUrl}${path}`, { headers: authHeaders(this.apiKey) });
  }

  private post(path: string, body?: unknown): Promise<Response> {
    return this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...authHeaders(this.apiKey),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  // -- runs -----------------------------------------------------------------

  /** `POST /v1/runs` — enqueue a run; pass `thread_id` to continue a conversation. */
  async createRun(request: RunCreateRequest): Promise<Run> {
    return readJson<Run>(await this.post("/v1/runs", request));
  }

  async getRun(runId: string): Promise<Run> {
    return readJson<Run>(await this.get(`/v1/runs/${runId}`));
  }

  async cancelRun(runId: string): Promise<void> {
    const response = await this.post(`/v1/runs/${runId}/cancel`);
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`${response.status} ${response.statusText}: ${text}`);
    }
  }

  /** `POST /v1/runs/{id}/retry` — re-queue a **failed** run (409 otherwise). */
  async retryRun(runId: string, request: RunRetryRequest = {}): Promise<Run> {
    return readJson<Run>(await this.post(`/v1/runs/${runId}/retry`, request));
  }

  /** `POST /v1/runs/{id}/resume` — continue a `waiting_human` run after approval (409 otherwise). */
  async resumeRun(runId: string, request: RunResumeRequest = {}): Promise<Run> {
    return readJson<Run>(await this.post(`/v1/runs/${runId}/resume`, request));
  }

  /**
   * Poll `GET /v1/runs/{id}` until the status is in `until`.
   *
   * Stops on `waiting_human` by default so an approval flow can inspect the
   * run, call `resumeRun` and wait again. Use `subscribeRunEvents` for
   * step-level progress. Rejects with `RunTimeoutError` on timeout.
   */
  async waitForRun(runId: string, options: WaitForRunOptions = {}): Promise<Run> {
    const timeoutMs = options.timeoutMs ?? 300_000;
    const pollIntervalMs = options.pollIntervalMs ?? 500;
    const until = new Set<RunStatus>(options.until ?? DEFAULT_WAIT_UNTIL);
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const run = await this.getRun(runId);
      if (until.has(run.status)) return run;
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw new RunTimeoutError(run, timeoutMs);
      // Never sleep past the deadline: timeoutMs=100 with pollIntervalMs=10000
      // must reject after ~100ms, not 10s.
      await new Promise((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remaining)));
    }
  }

  /** `GET /v1/runs/{id}/messages` — newest page first; follow `next_cursor` for older ones. */
  async listRunMessages(
    runId: string,
    params: { cursor?: number; limit?: number } = {},
  ): Promise<MessagePage<number>> {
    return readJson(await this.get(withQuery(`/v1/runs/${runId}/messages`, params)));
  }

  /** `GET /v1/runs/{id}/audit` — cancel/resume records, oldest first. */
  async getRunAudit(runId: string): Promise<RunAuditEvent[]> {
    return readJson(await this.get(`/v1/runs/${runId}/audit`));
  }

  // -- threads --------------------------------------------------------------

  /** `POST /v1/threads` — open a conversation for `createRun({ thread_id })`. */
  async createThread(request: ThreadCreateRequest): Promise<Thread> {
    return readJson<Thread>(await this.post("/v1/threads", request));
  }

  /** `GET /v1/threads` — threads visible to the caller, newest first. */
  async listThreads(params: { limit?: number } = {}): Promise<Thread[]> {
    return readJson(await this.get(withQuery("/v1/threads", params)));
  }

  async getThread(threadId: string): Promise<Thread> {
    return readJson<Thread>(await this.get(`/v1/threads/${threadId}`));
  }

  /** `GET /v1/threads/{id}/runs` — runs in the thread, oldest first. */
  async listThreadRuns(threadId: string, params: { limit?: number } = {}): Promise<Run[]> {
    return readJson(await this.get(withQuery(`/v1/threads/${threadId}/runs`, params)));
  }

  /** `GET /v1/threads/{id}/messages` — cross-run transcript; items carry `run_id`, cursor is opaque. */
  async listThreadMessages(
    threadId: string,
    params: { cursor?: string; limit?: number } = {},
  ): Promise<MessagePage<string>> {
    return readJson(await this.get(withQuery(`/v1/threads/${threadId}/messages`, params)));
  }

  // -- misc -----------------------------------------------------------------

  async health(): Promise<{ status: string; version: string; adapters: string[] }> {
    const response = await this.fetchImpl(`${this.baseUrl}/v1/health`);
    return readJson(response);
  }
}
