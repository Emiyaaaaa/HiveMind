import type {
  Agent,
  AgentVersionDiff,
  Attachment,
  MessagePage,
  RegressionExecution,
  RegressionExecutionResults,
  Run,
  RunComparison,
  Thread,
  ThreadMessagePage,
} from "@/lib/types";
import { nextId } from "./ids";
import { MOCK_TENANT_ID } from "./seed";
import {
  appendAudit,
  cloneRun,
  createEmptyRun,
  defaultQuota,
  findAgent,
  findRun,
  findThread,
  getMockStore,
  nowIso,
  summarizeRun,
  upsertRun,
  type MockStore,
} from "./store";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function empty(status = 204): Response {
  return new Response(null, { status });
}

function error(status: number, detail: string): Response {
  return json({ detail }, status);
}

async function readJson<T>(request: Request): Promise<T> {
  try {
    return (await request.json()) as T;
  } catch {
    throw new Error("invalid_json");
  }
}

function pageMessages(
  messages: Run["messages"],
  cursor: number,
  limit: number,
): MessagePage {
  const items = messages
    .filter((m) => m.index >= cursor)
    .sort((a, b) => a.index - b.index)
    .slice(0, limit);
  const last = items[items.length - 1];
  const hasMore =
    last != null && messages.some((m) => m.index > last.index);
  return {
    items,
    next_cursor: hasMore && last ? last.index + 1 : null,
    has_more: hasMore,
  };
}

function computeDiff(
  from: { adapter: string; description: string | null; config: Record<string, unknown> },
  to: { adapter: string; description: string | null; config: Record<string, unknown> },
  fromVersion: number,
  toVersion: number,
): AgentVersionDiff {
  const added: Record<string, unknown> = {};
  const removed: Record<string, unknown> = {};
  const changed: Record<string, { from: unknown; to: unknown }> = {};
  const keys = new Set([
    ...Object.keys(from.config),
    ...Object.keys(to.config),
  ]);
  for (const key of keys) {
    const a = from.config[key];
    const b = to.config[key];
    if (!(key in from.config)) added[key] = b;
    else if (!(key in to.config)) removed[key] = a;
    else if (JSON.stringify(a) !== JSON.stringify(b)) {
      changed[key] = { from: a, to: b };
    }
  }
  return {
    from_version: fromVersion,
    to_version: toVersion,
    adapter:
      from.adapter === to.adapter
        ? null
        : { from: from.adapter, to: to.adapter },
    description:
      from.description === to.description
        ? null
        : { from: from.description, to: to.description },
    config: { added, removed, changed },
  };
}

function sideFromRun(run: Run, store: MockStore): RunComparison["baseline"] {
  const agent = findAgent(store, run.agent_id);
  return {
    run_id: run.id,
    agent_id: run.agent_id,
    agent_version: agent?.version ?? null,
    status: run.status,
    error: run.error,
  };
}

export async function handleMockApi(
  request: Request,
  pathParts: string[],
): Promise<Response> {
  const store = getMockStore();
  const method = request.method.toUpperCase();
  const url = new URL(request.url);
  const [a, b, c, d] = pathParts;

  try {
    // --- agents ---
    if (a === "agents" && !b && method === "GET") {
      return json(store.agents);
    }
    if (a === "agents" && !b && method === "POST") {
      const body = await readJson<{
        name: string;
        adapter?: string;
        config?: Record<string, unknown>;
        description?: string;
      }>(request);
      const at = nowIso();
      const agent: Agent = {
        id: nextId("agt"),
        tenant_id: MOCK_TENANT_ID,
        name: body.name,
        description: body.description ?? null,
        adapter: body.adapter ?? "echo",
        config: body.config ?? {},
        version: 1,
        created_at: at,
        updated_at: at,
      };
      store.agents.push(agent);
      store.quotas[agent.id] = defaultQuota(agent.id);
      store.versions[agent.id] = [
        {
          id: nextId("ver"),
          agent_id: agent.id,
          version: 1,
          description: agent.description,
          adapter: agent.adapter,
          config: agent.config,
          note: "created",
          created_at: at,
        },
      ];
      return json(agent, 201);
    }
    if (a === "agents" && b && c === "quota" && method === "GET") {
      const quota = store.quotas[b] ?? defaultQuota(b);
      if (!findAgent(store, b)) return error(404, "agent not found");
      return json(quota);
    }
    if (a === "agents" && b && !c && method === "PATCH") {
      const agent = findAgent(store, b);
      if (!agent) return error(404, "agent not found");
      const body = await readJson<{
        name?: string;
        description?: string | null;
        adapter?: string;
        config?: Record<string, unknown>;
        note?: string;
      }>(request);
      const at = nowIso();
      if (body.name != null) agent.name = body.name;
      if ("description" in body) agent.description = body.description ?? null;
      if (body.adapter != null) agent.adapter = body.adapter;
      if (body.config != null) agent.config = body.config;
      agent.version += 1;
      agent.updated_at = at;
      const versions = store.versions[agent.id] ?? [];
      versions.push({
        id: nextId("ver"),
        agent_id: agent.id,
        version: agent.version,
        description: agent.description,
        adapter: agent.adapter,
        config: agent.config,
        note: body.note ?? null,
        created_at: at,
      });
      store.versions[agent.id] = versions;
      return json(agent);
    }
    if (a === "agents" && b && c === "versions" && !d && method === "GET") {
      if (!findAgent(store, b)) return error(404, "agent not found");
      return json(store.versions[b] ?? []);
    }
    if (a === "agents" && b && c === "versions" && d === "diff" && method === "GET") {
      const fromV = Number(url.searchParams.get("from"));
      const toV = Number(url.searchParams.get("to"));
      const versions = store.versions[b] ?? [];
      const from = versions.find((v) => v.version === fromV);
      const to = versions.find((v) => v.version === toV);
      if (!from || !to) return error(404, "version not found");
      return json(computeDiff(from, to, fromV, toV));
    }
    if (a === "agents" && b && c === "versions" && d && method === "GET") {
      const version = Number(d);
      const found = (store.versions[b] ?? []).find((v) => v.version === version);
      if (!found) return error(404, "version not found");
      return json(found);
    }
    if (
      a === "agents" &&
      b &&
      c === "versions" &&
      d &&
      pathParts[4] === "restore" &&
      method === "POST"
    ) {
      const agent = findAgent(store, b);
      const version = Number(d);
      const snap = (store.versions[b] ?? []).find((v) => v.version === version);
      if (!agent || !snap) return error(404, "version not found");
      const at = nowIso();
      agent.description = snap.description;
      agent.adapter = snap.adapter;
      agent.config = structuredClone(snap.config);
      agent.version += 1;
      agent.updated_at = at;
      const versions = store.versions[agent.id] ?? [];
      versions.push({
        id: nextId("ver"),
        agent_id: agent.id,
        version: agent.version,
        description: agent.description,
        adapter: agent.adapter,
        config: agent.config,
        note: `restored from v${version}`,
        created_at: at,
      });
      store.versions[agent.id] = versions;
      return json(agent);
    }

    // --- runs ---
    if (a === "runs" && !b && method === "GET") {
      return json(store.runs.map(summarizeRun));
    }
    if (a === "runs" && !b && method === "POST") {
      const body = await readJson<{
        agent_id: string;
        input: Record<string, unknown>;
        thread_id?: string;
      }>(request);
      const agent = findAgent(store, body.agent_id);
      if (!agent) return error(404, "agent not found");
      const run = createEmptyRun({
        agent_id: agent.id,
        adapter: agent.adapter,
        input: body.input ?? {},
        thread_id: body.thread_id,
      });
      upsertRun(store, run);
      store.pendingSimulations.add(run.id);
      if (body.thread_id) {
        const thread = findThread(store, body.thread_id);
        if (thread) {
          thread.updated_at = nowIso();
          const msgs = store.threadMessages[thread.id] ?? [];
          msgs.push({
            ...run.messages[0],
            run_id: run.id,
          });
          store.threadMessages[thread.id] = msgs;
        }
      }
      return json(cloneRun(run), 201);
    }
    if (a === "runs" && b && !c && method === "GET") {
      const run = findRun(store, b);
      if (!run) return error(404, "run not found");
      return json(cloneRun(run));
    }
    if (a === "runs" && b && c === "messages" && method === "GET") {
      const run = findRun(store, b);
      if (!run) return error(404, "run not found");
      const cursor = Number(url.searchParams.get("cursor") ?? "0");
      const limit = Number(url.searchParams.get("limit") ?? "50");
      return json(pageMessages(run.messages, cursor, limit));
    }
    if (a === "runs" && b && c === "audit" && method === "GET") {
      if (!findRun(store, b)) return error(404, "run not found");
      return json(store.audit[b] ?? []);
    }
    if (a === "runs" && b && c === "cancel" && method === "POST") {
      const run = findRun(store, b);
      if (!run) return error(404, "run not found");
      if (["succeeded", "failed", "cancelled"].includes(run.status)) {
        return error(409, `run already ${run.status}`);
      }
      run.status = "cancelled";
      run.error = run.error ?? "cancelled";
      run.updated_at = nowIso();
      for (const step of run.steps) {
        if (step.status === "running" || step.status === "pending" || step.status === "waiting_human") {
          step.status = "cancelled";
          step.updated_at = run.updated_at;
        }
      }
      store.pendingSimulations.delete(run.id);
      appendAudit(store, run.id, "cancel");
      upsertRun(store, run);
      return empty();
    }
    if (a === "runs" && b && c === "resume" && method === "POST") {
      const run = findRun(store, b);
      if (!run) return error(404, "run not found");
      if (run.status !== "waiting_human") {
        return error(409, "run is not waiting for human input");
      }
      const body = await readJson<{ input?: Record<string, unknown> }>(request);
      const decision =
        typeof body.input?.approval === "string"
          ? body.input.approval
          : typeof body.input?.route === "string"
            ? body.input.route
            : "approved";
      const at = nowIso();
      run.updated_at = at;
      appendAudit(store, run.id, "resume", { input: body.input ?? {} });

      if (decision === "rejected") {
        run.status = "cancelled";
        run.error = "rejected by human";
        run.output = {
          ...(run.output ?? {}),
          approval: "rejected",
          note: body.input?.note ?? null,
        };
        for (const step of run.steps) {
          if (step.status === "waiting_human") {
            step.status = "cancelled";
            step.updated_at = at;
          }
        }
      } else {
        run.status = "succeeded";
        run.error = null;
        run.output = {
          ...(run.output ?? {}),
          approval: "approved",
          note: body.input?.note ?? null,
          reply:
            typeof run.output?.reply === "string"
              ? run.output.reply
              : "Refund approved and submitted.",
        };
        for (const step of run.steps) {
          if (step.status === "waiting_human") {
            step.status = "succeeded";
            step.output = { approved: true };
            step.updated_at = at;
          }
        }
        run.messages.push({
          id: nextId("msg"),
          index: run.messages.length,
          step_id: null,
          role: "assistant",
          name: null,
          content:
            decision === "approved"
              ? "Approved. I've submitted the refund and notified the customer."
              : "Decision recorded.",
          tool_call_id: null,
          extra: {},
          created_at: at,
        });
      }
      upsertRun(store, run);
      return json(cloneRun(run));
    }
    if (a === "runs" && b && c === "retry" && method === "POST") {
      const run = findRun(store, b);
      if (!run) return error(404, "run not found");
      const body = await readJson<{ checkpoint_index?: number }>(request);
      const agent = findAgent(store, run.agent_id);
      const retry = createEmptyRun({
        agent_id: run.agent_id,
        adapter: agent?.adapter ?? run.adapter,
        input: {
          ...run.input,
          retry_of: run.id,
          checkpoint_index: body.checkpoint_index ?? null,
        },
        thread_id: run.thread_id,
      });
      retry.status = "pending";
      upsertRun(store, retry);
      store.pendingSimulations.add(retry.id);
      return json(cloneRun(retry), 201);
    }

    // --- threads ---
    if (a === "threads" && !b && method === "GET") {
      return json(store.threads);
    }
    if (a === "threads" && !b && method === "POST") {
      const body = await readJson<{
        agent_id: string;
        title?: string;
        user_id?: string;
      }>(request);
      if (!findAgent(store, body.agent_id)) return error(404, "agent not found");
      const at = nowIso();
      const thread: Thread = {
        id: nextId("thr"),
        tenant_id: MOCK_TENANT_ID,
        project_id: null,
        agent_id: body.agent_id,
        user_id: body.user_id ?? null,
        title: body.title ?? null,
        created_at: at,
        updated_at: at,
      };
      store.threads.unshift(thread);
      store.threadMessages[thread.id] = [];
      return json(thread, 201);
    }
    if (a === "threads" && b && !c && method === "GET") {
      const thread = findThread(store, b);
      if (!thread) return error(404, "thread not found");
      return json(thread);
    }
    if (a === "threads" && b && c === "messages" && method === "GET") {
      if (!findThread(store, b)) return error(404, "thread not found");
      const all = store.threadMessages[b] ?? [];
      const limit = Number(url.searchParams.get("limit") ?? "100");
      const cursor = url.searchParams.get("cursor");
      let start = 0;
      if (cursor) {
        const idx = all.findIndex((m) => m.id === cursor);
        start = idx >= 0 ? idx + 1 : 0;
      }
      const items = all.slice(start, start + limit);
      const hasMore = start + limit < all.length;
      const page: ThreadMessagePage = {
        items,
        next_cursor: hasMore ? items[items.length - 1]?.id ?? null : null,
        has_more: hasMore,
      };
      return json(page);
    }
    if (a === "threads" && b && c === "runs" && method === "GET") {
      if (!findThread(store, b)) return error(404, "thread not found");
      return json(
        store.runs.filter((r) => r.thread_id === b).map(summarizeRun),
      );
    }

    // --- attachments ---
    if (a === "attachments" && !b && method === "POST") {
      const form = await request.formData();
      const file = form.get("file");
      if (!(file instanceof File)) return error(400, "file required");
      const caption = form.get("caption");
      const at = nowIso();
      const id = nextId("att");
      const attachment: Attachment = {
        id,
        tenant_id: MOCK_TENANT_ID,
        run_id: null,
        message_id: null,
        media_type: file.type || "application/octet-stream",
        filename: file.name,
        size_bytes: file.size,
        sha256: "demo-sha256",
        caption: typeof caption === "string" ? caption : null,
        url: `/api/v1/attachments/${id}/content`,
        created_at: at,
        updated_at: at,
      };
      store.attachments[id] = attachment;
      return json(attachment, 201);
    }
    if (a === "attachments" && b && !c && method === "GET") {
      const att = store.attachments[b];
      if (!att) return error(404, "attachment not found");
      return json(att);
    }
    if (a === "attachments" && b && c === "content" && method === "GET") {
      const att = store.attachments[b];
      if (!att) return error(404, "attachment not found");
      return new Response(`demo content for ${att.filename}`, {
        headers: {
          "Content-Type": att.media_type,
          "Content-Disposition": `inline; filename="${att.filename}"`,
        },
      });
    }

    // --- comparisons / regression ---
    if (a === "run-comparisons" && b === "preview" && method === "POST") {
      const body = await readJson<{
        baseline_run_id: string;
        candidate_run_id: string;
      }>(request);
      const baseline = findRun(store, body.baseline_run_id);
      const candidate = findRun(store, body.candidate_run_id);
      if (!baseline || !candidate) return error(404, "run not found");
      const comparison: RunComparison = {
        baseline: sideFromRun(baseline, store),
        candidate: sideFromRun(candidate, store),
        agent_version_changed:
          sideFromRun(baseline, store).agent_version !==
          sideFromRun(candidate, store).agent_version,
        status_changed: baseline.status !== candidate.status,
        error_changed: baseline.error !== candidate.error,
        input_changed:
          JSON.stringify(baseline.input) !== JSON.stringify(candidate.input),
        output_changed:
          JSON.stringify(baseline.output) !== JSON.stringify(candidate.output),
      };
      return json(comparison);
    }

    if (a === "regression-executions" && !b && method === "POST") {
      const body = await readJson<{ baseline_run_ids: string[] }>(request);
      const ids = body.baseline_run_ids ?? [];
      if (ids.length === 0) return error(400, "baseline_run_ids required");
      for (const id of ids) {
        if (!findRun(store, id)) return error(404, `run not found: ${id}`);
      }
      const first = findRun(store, ids[0])!;
      const agent = findAgent(store, first.agent_id);
      const executionId = nextId("rex");
      const cases = ids.map((baseline_run_id) => ({
        baseline_run_id,
        candidate_run_id: nextId("run"),
      }));
      const execution: RegressionExecution = {
        execution_id: executionId,
        candidate_agent_version: agent?.version ?? 1,
        status: "running",
        total_cases: cases.length,
        completed_cases: 0,
        cases,
      };
      store.executions[executionId] = execution;

      // Complete asynchronously so the UI can poll.
      setTimeout(() => {
        const current = store.executions[executionId];
        if (!current) return;
        current.status = "completed";
        current.completed_cases = current.total_cases;
        const results: RegressionExecutionResults = {
          execution_id: executionId,
          passed: true,
          total_cases: current.total_cases,
          passed_cases: current.total_cases,
          failed_cases: 0,
          cases: current.cases.map((pair) => {
            const baseline = findRun(store, pair.baseline_run_id);
            const pass = baseline?.status === "succeeded";
            return {
              baseline_run_id: pair.baseline_run_id,
              candidate_run_id: pair.candidate_run_id,
              passed: pass,
              failures: pass
                ? []
                : [
                    {
                      code: "status_mismatch",
                      message: `baseline status was ${baseline?.status ?? "missing"}`,
                    },
                  ],
            };
          }),
        };
        results.failed_cases = results.cases.filter((c) => !c.passed).length;
        results.passed_cases = results.cases.filter((c) => c.passed).length;
        results.passed = results.failed_cases === 0;
        store.results[executionId] = results;
      }, 1800);

      return json(execution, 201);
    }

    if (a === "regression-executions" && b && !c && method === "GET") {
      const exec = store.executions[b];
      if (!exec) return error(404, "execution not found");
      return json(exec);
    }
    if (a === "regression-executions" && b && c === "results" && method === "GET") {
      const exec = store.executions[b];
      if (!exec) return error(404, "execution not found");
      if (exec.status !== "completed") {
        return error(409, "execution not completed");
      }
      const results = store.results[b];
      if (!results) return error(404, "results not found");
      return json(results);
    }

    return error(404, `no mock handler for ${method} /v1/${pathParts.join("/")}`);
  } catch (err) {
    if (err instanceof Error && err.message === "invalid_json") {
      return error(400, "invalid JSON body");
    }
    console.error("[mock]", err);
    return error(500, "mock handler error");
  }
}
