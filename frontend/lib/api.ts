import type { Agent, Run } from "./types";
import { normalizeUsage } from "./usage";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function normalizeRun(run: Run): Run {
  return { ...run, usage: normalizeUsage(run.usage) };
}

export const api = {
  listRuns: async () => {
    const runs = await request<Run[]>("/v1/runs");
    return runs.map(normalizeRun);
  },
  getRun: async (id: string) => normalizeRun(await request<Run>(`/v1/runs/${id}`)),
  cancelRun: (id: string) =>
    request<void>(`/v1/runs/${id}/cancel`, { method: "POST" }),
  retryRun: async (id: string, body?: { checkpoint_index?: number }) =>
    normalizeRun(
      await request<Run>(`/v1/runs/${id}/retry`, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    ),
  resumeRun: async (id: string, body?: { input?: Record<string, unknown> }) =>
    normalizeRun(
      await request<Run>(`/v1/runs/${id}/resume`, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    ),
  createRun: async (body: {
    agent_id: string;
    input: Record<string, unknown>;
  }) =>
    normalizeRun(
      await request<Run>("/v1/runs", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    ),
  listAgents: () => request<Agent[]>("/v1/agents"),
  createAgent: (body: {
    name: string;
    adapter?: string;
    config?: Record<string, unknown>;
    description?: string;
  }) =>
    request<Agent>("/v1/agents", {
      method: "POST",
      body: JSON.stringify({ adapter: "echo", config: {}, ...body }),
    }),
};

export function eventStreamUrl(runId: string): string {
  return `/api/v1/events/${runId}`;
}
