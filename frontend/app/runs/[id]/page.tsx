"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";

import { CheckpointMarker } from "@/components/CheckpointMarker";
import { CheckpointPanel } from "@/components/CheckpointPanel";
import { EventStream } from "@/components/EventStream";
import { StatusBadge } from "@/components/StatusBadge";
import { TokenCostSummary } from "@/components/TokenCostSummary";
import { checkpointsByStep } from "@/lib/checkpoints";
import { formatCostUsd } from "@/lib/usage";
import { api } from "@/lib/api";

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function RunDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["run", id],
    queryFn: () => api.getRun(id),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (status === "running" || status === "pending") return 2_000;
      return false;
    },
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelRun(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", id] }),
  });

  if (run.isLoading) return <p className="text-muted">Loading…</p>;
  if (run.error || !run.data)
    return <p className="text-bad">Failed to load run: {String(run.error)}</p>;

  const r = run.data;
  const isLive = r.status === "running" || r.status === "pending";
  const stepCheckpoints = checkpointsByStep(r.steps, r.checkpoints);

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="text-xs text-muted font-mono">{r.id}</div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold">
              Run · <span className="font-mono">{r.adapter}</span>
            </h1>
            <StatusBadge status={r.status} />
          </div>
          <div className="text-xs text-muted">
            agent <span className="font-mono">{r.agent_id}</span> · created{" "}
            {new Date(r.created_at).toLocaleString()}
          </div>
        </div>
        <div className="flex gap-2">
          {isLive && (
            <button
              className="rounded border border-bad/40 text-bad px-3 py-1.5 text-sm hover:bg-bad/10"
              onClick={() => cancel.mutate()}
            >
              Cancel
            </button>
          )}
          <Link
            href="/runs"
            className="rounded border border-border px-3 py-1.5 text-sm hover:bg-surface"
          >
            Back
          </Link>
        </div>
      </header>

      {r.error ? (
        <div className="rounded border border-bad/40 bg-bad/10 p-3 text-bad text-sm font-mono">
          {r.error}
        </div>
      ) : null}

      <section className="rounded-lg border border-border bg-surface p-4 space-y-3">
        <h2 className="font-medium">Token &amp; cost</h2>
        <TokenCostSummary usage={r.usage} steps={r.steps} />
      </section>

      <CheckpointPanel
        runId={id}
        status={r.status}
        checkpoints={r.checkpoints}
      />

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface p-4 space-y-2">
          <h2 className="font-medium">Input</h2>
          <pre className="text-xs font-mono whitespace-pre-wrap text-muted">
            {JSON.stringify(r.input, null, 2)}
          </pre>
        </div>
        <div className="rounded-lg border border-border bg-surface p-4 space-y-2">
          <h2 className="font-medium">Output</h2>
          <pre className="text-xs font-mono whitespace-pre-wrap text-muted">
            {r.output ? JSON.stringify(r.output, null, 2) : "—"}
          </pre>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-medium">Steps</h2>
        <ol className="space-y-2">
          {r.steps.map((s) => {
            const cps = stepCheckpoints.get(s.id) ?? [];
            return (
            <li
              key={s.id}
              className="rounded-lg border border-border bg-surface p-3 space-y-2"
            >
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="text-muted font-mono">#{s.index}</span>
                <span className="font-medium">{s.node}</span>
                <StatusBadge status={s.status} />
                {cps.map((cp) => (
                  <CheckpointMarker key={cp.id} checkpoint={cp} />
                ))}
                {s.latency_ms != null && (
                  <span className="text-xs text-muted">{s.latency_ms}ms</span>
                )}
                {(s.tokens_in != null || s.tokens_out != null) && (
                  <span className="text-xs text-muted font-mono">
                    {s.tokens_in ?? 0}→{s.tokens_out ?? 0} tok
                  </span>
                )}
                {s.cost_usd != null && (
                  <span className="text-xs text-accent font-mono">
                    {formatCostUsd(s.cost_usd)}
                  </span>
                )}
              </div>
              {s.tool_calls.length > 0 && (
                <ul className="space-y-1 text-xs font-mono">
                  {s.tool_calls.map((c) => (
                    <li key={c.id} className="text-muted">
                      <span className="text-accent">{c.name}(</span>
                      {JSON.stringify(c.arguments)}
                      <span className="text-accent">)</span>
                      {c.result ? ` → ${JSON.stringify(c.result)}` : ""}
                      {c.error ? (
                        <span className="text-bad"> error: {c.error}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
              {s.output ? (
                <pre className="text-xs font-mono whitespace-pre-wrap text-muted">
                  {JSON.stringify(s.output, null, 2)}
                </pre>
              ) : null}
              {s.error ? <div className="text-bad text-xs">{s.error}</div> : null}
            </li>
            );
          })}
        </ol>
      </section>

      <section className="space-y-3">
        <h2 className="font-medium">Messages</h2>
        <ol className="space-y-2">
          {r.messages.map((m) => (
            <li
              key={m.id}
              className="rounded border border-border bg-surface p-3 text-sm"
            >
              <div className="text-xs uppercase tracking-wide text-muted mb-1">
                {m.role}
                {m.name ? ` · ${m.name}` : ""}
              </div>
              <div className="whitespace-pre-wrap">{m.content}</div>
            </li>
          ))}
        </ol>
      </section>

      <EventStream
        runId={id}
        onTerminal={() => queryClient.invalidateQueries({ queryKey: ["run", id] })}
      />
    </div>
  );
}
