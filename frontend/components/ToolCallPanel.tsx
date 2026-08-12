"use client";

import clsx from "clsx";
import { useMemo } from "react";

import type { Step, ToolCall } from "@/lib/types";

type ToolCallStatus = "pending" | "succeeded" | "failed";

interface ToolCallEntry {
  call: ToolCall;
  stepIndex: number;
  stepNode: string;
}

const statusStyle: Record<ToolCallStatus, string> = {
  pending: "border-muted/40 bg-muted/10 text-muted",
  succeeded: "border-good/40 bg-good/10 text-good",
  failed: "border-bad/40 bg-bad/10 text-bad",
};

function getStatus(call: ToolCall): ToolCallStatus {
  if (call.error) return "failed";
  if (call.result != null) return "succeeded";
  return "pending";
}

function formatLatency(ms: number | null): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) {
    return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  }
  const totalSeconds = Math.round(ms / 1000);
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}m ${secs}s`;
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  const text = useMemo(() => JSON.stringify(value, null, 2), [value]);

  return (
    <div className="space-y-1">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <pre className="max-h-72 overflow-auto rounded border border-border bg-bg p-3 text-xs font-mono whitespace-pre-wrap break-all text-muted">
        {text}
      </pre>
    </div>
  );
}

export function ToolCallPanel({ steps }: { steps: Step[] }) {
  const { entries, counts } = useMemo(() => {
    const entries: ToolCallEntry[] = [...steps]
      .sort((a, b) => a.index - b.index)
      .flatMap((step) =>
        step.tool_calls.map((call) => ({
          call,
          stepIndex: step.index,
          stepNode: step.node,
        })),
      );
    const counts: Record<ToolCallStatus, number> = {
      pending: 0,
      succeeded: 0,
      failed: 0,
    };
    for (const { call } of entries) counts[getStatus(call)] += 1;
    return { entries, counts };
  }, [steps]);

  return (
    <section className="rounded-lg border border-border bg-surface p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="font-medium">Tool calls</h2>
          <p className="text-xs text-muted">
            Inspect arguments, results, and errors across this run.
          </p>
        </div>
        {entries.length > 0 ? (
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="text-muted">{entries.length} total</span>
            <span className="text-good">{counts.succeeded} succeeded</span>
            <span className="text-bad">{counts.failed} failed</span>
            <span className="text-muted">{counts.pending} pending</span>
          </div>
        ) : null}
      </div>

      {entries.length === 0 ? (
        <p className="rounded border border-dashed border-border p-4 text-center text-xs text-muted">
          No tool calls recorded for this run.
        </p>
      ) : (
        <ol className="space-y-2">
          {entries.map(({ call, stepIndex, stepNode }) => {
            const status = getStatus(call);
            const latency = formatLatency(call.latency_ms);
            return (
              <li key={call.id}>
                <details className="group rounded border border-border bg-bg">
                  <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2.5 text-sm marker:content-none">
                    <span className="font-medium text-accent">{call.name}</span>
                    <span
                      className={clsx(
                        "rounded border px-1.5 py-0.5 text-[11px]",
                        statusStyle[status],
                      )}
                    >
                      {status}
                    </span>
                    {latency ? (
                      <span className="text-xs font-mono text-muted">
                        {latency}
                      </span>
                    ) : null}
                    <span className="ml-auto text-xs font-mono text-muted">
                      step #{stepIndex} · {stepNode}
                    </span>
                    <span
                      className="text-muted transition-transform group-open:rotate-90"
                      aria-hidden
                    >
                      ›
                    </span>
                  </summary>
                  <div className="space-y-3 border-t border-border p-3">
                    <JsonBlock label="Arguments" value={call.arguments} />
                    {call.result != null ? (
                      <JsonBlock label="Result" value={call.result} />
                    ) : null}
                    {call.error ? (
                      <div className="space-y-1">
                        <div className="text-xs uppercase tracking-wide text-bad">
                          Error
                        </div>
                        <pre className="rounded border border-bad/40 bg-bad/10 p-3 text-xs font-mono whitespace-pre-wrap break-words text-bad">
                          {call.error}
                        </pre>
                      </div>
                    ) : null}
                  </div>
                </details>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
