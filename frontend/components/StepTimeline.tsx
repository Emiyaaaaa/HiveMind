"use client";

import clsx from "clsx";
import { useMemo, useState } from "react";

import { CheckpointMarker } from "@/components/CheckpointMarker";
import { StatusBadge } from "@/components/StatusBadge";
import { formatCostUsd } from "@/lib/usage";
import type { Checkpoint, RunStatus, Step } from "@/lib/types";

interface Props {
  steps: Step[];
  checkpointsByStepId?: Map<string, Checkpoint[]>;
}

const statusDot: Record<RunStatus, string> = {
  pending: "bg-muted border-muted",
  running: "bg-accent border-accent animate-pulse",
  succeeded: "bg-good border-good",
  failed: "bg-bad border-bad",
  cancelled: "bg-muted border-muted",
  waiting_human: "bg-warn border-warn",
};

const statusBar: Record<RunStatus, string> = {
  pending: "bg-muted/40",
  running: "bg-accent/60",
  succeeded: "bg-good/60",
  failed: "bg-bad/60",
  cancelled: "bg-muted/40",
  waiting_human: "bg-warn/60",
};

const statusRail: Record<RunStatus, string> = {
  pending: "bg-border",
  running: "bg-accent/40",
  succeeded: "bg-good/40",
  failed: "bg-bad/40",
  cancelled: "bg-border",
  waiting_human: "bg-warn/40",
};

function formatLatency(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  const mins = Math.floor(ms / 60_000);
  const secs = Math.round((ms % 60_000) / 1000);
  return `${mins}m ${secs}s`;
}

function formatRelativeTime(iso: string): string {
  return new Date(iso).toLocaleTimeString();
}

/** Status transitions implied by step order (node → next node). */
function statusTransitions(steps: Step[]): string[] {
  if (steps.length === 0) return [];
  const parts: string[] = [];
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (i === 0) {
      parts.push(`${s.node} (${s.status})`);
    } else {
      parts.push(`→ ${s.node} (${s.status})`);
    }
  }
  return parts;
}

export function StepTimeline({ steps, checkpointsByStepId }: Props) {
  const sorted = useMemo(
    () => [...steps].sort((a, b) => a.index - b.index),
    [steps],
  );

  const maxLatency = useMemo(() => {
    let max = 0;
    for (const s of sorted) {
      if (s.latency_ms != null && s.latency_ms > max) max = s.latency_ms;
    }
    return max;
  }, [sorted]);

  const totalLatency = useMemo(
    () =>
      sorted.reduce(
        (sum, s) => sum + (s.latency_ms != null ? s.latency_ms : 0),
        0,
      ),
    [sorted],
  );

  const statusCounts = useMemo(() => {
    const counts: Partial<Record<RunStatus, number>> = {};
    for (const s of sorted) {
      counts[s.status] = (counts[s.status] ?? 0) + 1;
    }
    return counts;
  }, [sorted]);

  const flow = useMemo(() => statusTransitions(sorted), [sorted]);

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  if (sorted.length === 0) {
    return (
      <section className="rounded-lg border border-border bg-surface p-4">
        <h2 className="font-medium mb-2">Step timeline</h2>
        <p className="text-xs text-muted">No steps yet.</p>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="font-medium">Step timeline</h2>
          <p className="text-xs text-muted">
            {sorted.length} step{sorted.length === 1 ? "" : "s"}
            {totalLatency > 0 ? ` · Σ latency ${formatLatency(totalLatency)}` : ""}
            {maxLatency > 0 ? ` · max ${formatLatency(maxLatency)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {(Object.entries(statusCounts) as [RunStatus, number][]).map(
            ([status, count]) => (
              <span
                key={status}
                className="inline-flex items-center gap-1.5 text-xs text-muted"
              >
                <span
                  className={clsx(
                    "inline-block size-2 rounded-full border",
                    statusDot[status],
                  )}
                />
                {count} {status}
              </span>
            ),
          )}
        </div>
      </div>

      {flow.length > 1 ? (
        <div className="rounded border border-border bg-bg px-3 py-2 text-xs font-mono text-muted overflow-x-auto">
          <span className="text-muted/70 uppercase tracking-wide mr-2">
            Flow
          </span>
          {flow.map((part, i) => (
            <span key={i} className={i === 0 ? "text-text" : "text-muted"}>
              {i > 0 ? " " : ""}
              {part}
            </span>
          ))}
        </div>
      ) : null}

      {maxLatency > 0 ? (
        <div className="space-y-1.5">
          <div className="text-xs text-muted uppercase tracking-wide">
            Latency by node
          </div>
          <ol className="space-y-1.5">
            {sorted.map((s) => {
              const pct =
                s.latency_ms != null && maxLatency > 0
                  ? Math.max(2, (s.latency_ms / maxLatency) * 100)
                  : 0;
              return (
                <li key={`bar-${s.id}`} className="flex items-center gap-3 text-xs">
                  <span className="w-24 shrink-0 truncate font-mono text-muted">
                    #{s.index} {s.node}
                  </span>
                  <div className="flex-1 h-2 rounded bg-bg overflow-hidden">
                    <div
                      className={clsx(
                        "h-full rounded transition-[width] duration-300",
                        statusBar[s.status],
                      )}
                      style={{ width: `${pct}%` }}
                      title={formatLatency(s.latency_ms)}
                    />
                  </div>
                  <span className="w-16 shrink-0 text-right font-mono tabular-nums text-muted">
                    {formatLatency(s.latency_ms)}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      ) : null}

      <ol className="relative space-y-0">
        {sorted.map((s, i) => {
          const cps = checkpointsByStepId?.get(s.id) ?? [];
          const isOpen = expanded.has(s.id);
          const isLast = i === sorted.length - 1;
          const hasDetails =
            s.tool_calls.length > 0 ||
            s.output != null ||
            s.error != null ||
            Object.keys(s.input).length > 0;

          return (
            <li key={s.id} className="relative flex gap-3 pb-4 last:pb-0">
              <div className="flex flex-col items-center w-4 shrink-0">
                <span
                  className={clsx(
                    "size-3 rounded-full border-2 mt-1.5 z-10",
                    statusDot[s.status],
                  )}
                  aria-hidden
                />
                {!isLast ? (
                  <span
                    className={clsx(
                      "w-0.5 flex-1 mt-1 rounded-full",
                      statusRail[s.status],
                    )}
                    aria-hidden
                  />
                ) : null}
              </div>

              <div className="flex-1 min-w-0 rounded-lg border border-border bg-bg p-3 space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-muted font-mono">#{s.index}</span>
                  <span className="font-medium">{s.node}</span>
                  <StatusBadge status={s.status} />
                  {cps.map((cp) => (
                    <CheckpointMarker key={cp.id} checkpoint={cp} />
                  ))}
                  <span className="text-xs text-muted font-mono ml-auto tabular-nums">
                    {formatRelativeTime(s.created_at)}
                    {s.updated_at !== s.created_at
                      ? ` → ${formatRelativeTime(s.updated_at)}`
                      : ""}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-3 text-xs text-muted font-mono">
                  <span title="Step latency">
                    latency {formatLatency(s.latency_ms)}
                  </span>
                  {(s.tokens_in != null || s.tokens_out != null) && (
                    <span>
                      {s.tokens_in ?? 0}→{s.tokens_out ?? 0} tok
                    </span>
                  )}
                  {s.cost_usd != null && (
                    <span className="text-accent">
                      {formatCostUsd(s.cost_usd)}
                    </span>
                  )}
                  {s.tool_calls.length > 0 && (
                    <span>
                      {s.tool_calls.length} tool
                      {s.tool_calls.length === 1 ? "" : "s"}
                    </span>
                  )}
                </div>

                {s.error ? (
                  <div className="text-bad text-xs font-mono">{s.error}</div>
                ) : null}

                {hasDetails ? (
                  <button
                    type="button"
                    className="text-xs text-accent hover:underline"
                    onClick={() => toggle(s.id)}
                    aria-expanded={isOpen}
                  >
                    {isOpen ? "Hide details" : "Show details"}
                  </button>
                ) : null}

                {isOpen ? (
                  <div className="space-y-2 pt-1 border-t border-border">
                    {Object.keys(s.input).length > 0 ? (
                      <DetailBlock label="Input" value={s.input} />
                    ) : null}
                    {s.output ? (
                      <DetailBlock label="Output" value={s.output} />
                    ) : null}
                    {s.tool_calls.length > 0 ? (
                      <div className="space-y-1">
                        <div className="text-xs text-muted uppercase tracking-wide">
                          Tool calls
                        </div>
                        <ul className="space-y-1.5 text-xs font-mono">
                          {s.tool_calls.map((c) => (
                            <li
                              key={c.id}
                              className="rounded border border-border px-2 py-1.5 space-y-0.5"
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-accent">{c.name}</span>
                                {c.latency_ms != null && (
                                  <span className="text-muted">
                                    {formatLatency(c.latency_ms)}
                                  </span>
                                )}
                                {c.error ? (
                                  <span className="text-bad">error</span>
                                ) : c.result ? (
                                  <span className="text-good">ok</span>
                                ) : (
                                  <span className="text-muted">pending</span>
                                )}
                              </div>
                              <pre className="text-muted whitespace-pre-wrap break-all">
                                args: {JSON.stringify(c.arguments)}
                              </pre>
                              {c.result ? (
                                <pre className="text-muted whitespace-pre-wrap break-all">
                                  result: {JSON.stringify(c.result)}
                                </pre>
                              ) : null}
                              {c.error ? (
                                <div className="text-bad">error: {c.error}</div>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function DetailBlock({
  label,
  value,
}: {
  label: string;
  value: Record<string, unknown>;
}) {
  return (
    <div className="space-y-1">
      <div className="text-xs text-muted uppercase tracking-wide">{label}</div>
      <pre className="text-xs font-mono whitespace-pre-wrap text-muted break-all">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}
