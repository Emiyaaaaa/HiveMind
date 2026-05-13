"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api } from "@/lib/api";

export default function HomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents"], queryFn: api.listAgents });

  const [agentName, setAgentName] = useState("echo-bot");
  const [prompt, setPrompt] = useState("hello, agentflow");

  const createAgent = useMutation({
    mutationFn: () => api.createAgent({ name: agentName, adapter: "echo" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
  });

  const createRun = useMutation({
    mutationFn: async () => {
      const agent =
        agents.data?.find((a) => a.name === agentName) ??
        (await api.createAgent({ name: agentName, adapter: "echo" }));
      return api.createRun({ agent_id: agent.id, input: { prompt } });
    },
    onSuccess: (run) => {
      router.push(`/runs/${run.id}`);
    },
  });

  return (
    <div className="max-w-3xl mx-auto space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold">AgentFlow</h1>
        <p className="text-muted">
          A Python-first runtime for multi-agent systems. Define agents,
          launch runs, watch every step stream into the console.
        </p>
      </section>

      <section className="rounded-lg border border-border bg-surface p-5 space-y-4">
        <h2 className="font-medium">Quick launch</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs uppercase tracking-wide text-muted">
              Agent name
            </span>
            <input
              className="w-full rounded bg-bg border border-border px-3 py-2 text-sm"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
            />
          </label>
          <label className="space-y-1">
            <span className="text-xs uppercase tracking-wide text-muted">
              Prompt
            </span>
            <input
              className="w-full rounded bg-bg border border-border px-3 py-2 text-sm"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </label>
        </div>
        <div className="flex gap-3">
          <button
            className="rounded bg-accent text-bg px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-50"
            onClick={() => createRun.mutate()}
            disabled={createRun.isPending}
          >
            {createRun.isPending ? "Launching..." : "Launch run"}
          </button>
          <button
            className="rounded border border-border px-4 py-2 text-sm hover:bg-surface"
            onClick={() => createAgent.mutate()}
            disabled={createAgent.isPending}
          >
            Create agent only
          </button>
          <Link
            href="/runs"
            className="rounded border border-border px-4 py-2 text-sm hover:bg-surface"
          >
            Browse runs
          </Link>
        </div>
        {createRun.error ? (
          <p className="text-bad text-sm">{(createRun.error as Error).message}</p>
        ) : null}
      </section>

      <section>
        <h2 className="font-medium mb-3">Registered agents</h2>
        {agents.isLoading ? (
          <p className="text-muted">Loading…</p>
        ) : agents.data && agents.data.length > 0 ? (
          <ul className="divide-y divide-border rounded-lg border border-border bg-surface">
            {agents.data.map((a) => (
              <li key={a.id} className="px-4 py-3 flex items-center justify-between">
                <div>
                  <div className="font-medium">{a.name}</div>
                  <div className="text-xs text-muted">
                    adapter: <span className="font-mono">{a.adapter}</span>
                  </div>
                </div>
                <span className="text-xs text-muted font-mono">{a.id}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted">No agents yet. Create one above.</p>
        )}
      </section>
    </div>
  );
}
